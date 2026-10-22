"""Build a SQL preview and an Alembic module from a validated plan.

The generator reads structured operations, the snapshot fingerprint, and the
risk assessment. It does not read the natural-language request or schema
comments, and it does not connect to a database.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from app.schemas.artifacts import (
    ArtifactReversibility,
    MigrationArtifact,
    OperationReversibility,
)
from app.schemas.domain import SchemaSnapshot
from app.schemas.planning import MigrationProposal, PlanOperation
from app.schemas.risk import RiskAssessment
from app.services.risk_engine import assess_risk
from app.services.sql_safety import ALLOWED_COLUMN_TYPES, contains_untrusted_sql, target_problems

ARTIFACTS_DIR = Path(__file__).resolve().parents[2] / "artifacts" / "generated"
_VERSIONS_DIR = Path(__file__).resolve().parents[2] / "alembic" / "versions"
_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")
_TYPE_SQL = {
    "text": "TEXT",
    "integer": "INTEGER",
    "bigint": "BIGINT",
    "boolean": "BOOLEAN",
    "timestamptz": "TIMESTAMP WITH TIME ZONE",
}
_TYPE_ALEMBIC = {
    "text": "sa.Text()",
    "integer": "sa.Integer()",
    "bigint": "sa.BigInteger()",
    "boolean": "sa.Boolean()",
    "timestamptz": "postgresql.TIMESTAMP(timezone=True)",
}
_COLUMN_LOSS = "Recreating a dropped column does not recover its former values."


class ArtifactRejectedError(Exception):
    """The plan cannot become an artifact. `code` is a stable API error."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class _Rendered:
    upgrade_sql: str
    downgrade_sql: str
    upgrade_code: str
    downgrade_code: str
    reversibility: OperationReversibility
    uses_timestamptz: bool


def generate_migration(
    snapshot: SchemaSnapshot,
    proposal: MigrationProposal,
    assessment: RiskAssessment,
    output_dir: Path | None = None,
) -> MigrationArtifact:
    """Write a review artifact. The same operations produce the SQL and the module."""
    directory = _safe_output_dir(output_dir)
    _require_provenance(snapshot, proposal, assessment)
    _require_eligible(assessment)
    rendered = [_render(snapshot, operation, assessment) for operation in proposal.operations]
    migration_id = _migration_id(snapshot, proposal.operations)
    summary = " ".join(operation.summary for operation in proposal.operations)
    sql_preview = "\n".join(item.upgrade_sql for item in rendered)
    downgrade_sql = "\n".join(item.downgrade_sql for item in rendered)
    details = [item.reversibility for item in rendered]
    alembic_source = _alembic_source(
        migration_id=migration_id,
        source_id=snapshot.source_id,
        fingerprint=snapshot.fingerprint,
        summary=summary,
        upgrade="\n\n".join(item.upgrade_code for item in rendered),
        downgrade="\n\n".join(item.downgrade_code for item in rendered),
        uses_timestamptz=any(item.uses_timestamptz for item in rendered),
    )
    artifact = MigrationArtifact(
        migration_id=migration_id,
        source_id=snapshot.source_id,
        schema_name=snapshot.schema_name,
        schema_fingerprint=snapshot.fingerprint,
        summary=summary,
        status="generated",
        applied=False,
        operation_ids=[operation.id for operation in proposal.operations],
        sql_preview=sql_preview,
        downgrade_sql=downgrade_sql,
        alembic_source=alembic_source,
        reversibility=_overall_reversibility(details),
        operation_reversibility=details,
        checksum="",
        location="",
    )
    checksum = _checksum(artifact)
    location = (directory / f"{migration_id}.py").as_posix()
    artifact = artifact.model_copy(update={"checksum": checksum, "location": location})
    py_path = directory / f"{migration_id}.py"
    json_path = directory / f"{migration_id}.json"
    py_path.write_text(alembic_source, encoding="utf-8", newline="\n")
    json_path.write_text(artifact.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n")
    return artifact


def verify_artifact(artifact: MigrationArtifact) -> bool:
    """True when the stored checksum matches the canonical artifact body."""
    return artifact.checksum == _checksum(artifact)


def canonical_artifact_json(artifact: MigrationArtifact) -> str:
    """Checksum input. Location and checksum are excluded so edits to SQL still fail."""
    body = artifact.model_dump(mode="json", exclude={"checksum", "location"})
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _checksum(artifact: MigrationArtifact) -> str:
    digest = hashlib.sha256(canonical_artifact_json(artifact).encode("ascii")).hexdigest()
    return f"sha256:{digest}"


def _require_provenance(
    snapshot: SchemaSnapshot,
    proposal: MigrationProposal,
    assessment: RiskAssessment,
) -> None:
    same_source = (
        proposal.source_id == snapshot.source_id and assessment.source_id == snapshot.source_id
    )
    same_schema = (
        proposal.schema_name == snapshot.schema_name
        and assessment.schema_name == snapshot.schema_name
    )
    same_status = assessment.plan_status == proposal.status
    same_fingerprint = assessment.schema_fingerprint == snapshot.fingerprint
    if not (same_source and same_schema and same_status and same_fingerprint):
        raise ArtifactRejectedError(
            "provenance_mismatch",
            "The risk assessment does not belong to this snapshot and plan.",
        )
    fresh = assess_risk(snapshot, proposal)
    if fresh.model_dump() != assessment.model_dump():
        raise ArtifactRejectedError(
            "provenance_mismatch",
            "The risk assessment does not match the current plan and snapshot.",
        )


def _require_eligible(assessment: RiskAssessment) -> None:
    if assessment.plan_status != "proposed":
        raise ArtifactRejectedError(
            "plan_not_proposed",
            "Only a proposed plan can be generated.",
        )
    if any(finding.disposition == "policy_blocked" for finding in assessment.findings):
        raise ArtifactRejectedError(
            "policy_blocked",
            "Policy-blocked operations are not generated.",
        )
    if any(finding.data_check == "not_run" for finding in assessment.findings):
        raise ArtifactRejectedError(
            "data_check_not_run",
            "A required live row check is not_run. Static risk is not a passed check.",
        )
    if assessment.eligibility_reason == "no_operations":
        raise ArtifactRejectedError(
            "no_operations",
            "The plan has no operations to generate.",
        )
    if not assessment.artifact_eligible or assessment.eligibility_reason != "eligible":
        raise ArtifactRejectedError(
            "unsafe_to_generate",
            "The plan is not eligible for an artifact.",
        )


def _render(
    snapshot: SchemaSnapshot,
    operation: PlanOperation,
    assessment: RiskAssessment,
) -> _Rendered:
    if operation.kind == "destructive":
        raise ArtifactRejectedError(
            "unsupported_operation",
            "Destructive operations are not generated.",
        )
    if operation.kind == "add_constraint":
        raise ArtifactRejectedError(
            "unsupported_operation",
            "Unique, not-null, and check constraints are not generated. "
            "A low static score is not a passed live row check.",
        )
    problems = target_problems(snapshot, operation)
    if problems:
        raise ArtifactRejectedError(
            "unsafe_to_generate",
            "The operation does not match the snapshot: " + "; ".join(problems),
        )
    if operation.kind == "add_column":
        return _render_column(snapshot, operation)
    if operation.kind == "add_index":
        return _render_index(snapshot, operation)
    if operation.kind == "rename_column":
        return _render_rename_column(snapshot, operation, assessment)
    if operation.kind == "rename_table":
        return _render_rename_table(snapshot, operation, assessment)
    raise ArtifactRejectedError(
        "unsupported_operation",
        "This operation type is not generated.",
    )


def _render_column(snapshot: SchemaSnapshot, operation: PlanOperation) -> _Rendered:
    if operation.nullable is not True or operation.default is not None:
        raise ArtifactRejectedError(
            "unsafe_to_generate",
            "Only a nullable column without a default is generated.",
        )
    if operation.data_type not in ALLOWED_COLUMN_TYPES or contains_untrusted_sql(operation.default):
        raise ArtifactRejectedError(
            "unsafe_to_generate",
            "The column type or default cannot be generated safely.",
        )
    schema = _ident(snapshot.schema_name, "schema")
    table = _ident(operation.table, "table")
    column = _ident(operation.column, "column")
    type_name = operation.data_type or ""
    upgrade_sql = (
        f"ALTER TABLE {_qualified(schema, table)} ADD COLUMN {_quote(column)} "
        f"{_TYPE_SQL[type_name]} NULL;"
    )
    downgrade_sql = f"ALTER TABLE {_qualified(schema, table)} DROP COLUMN {_quote(column)};"
    upgrade_code = (
        f"    op.add_column(\n        {_py(table)},\n"
        f"        sa.Column({_py(column)}, {_TYPE_ALEMBIC[type_name]}, nullable=True),\n"
        f"        schema={_py(schema)},\n    )"
    )
    downgrade_code = f"    op.drop_column({_py(table)}, {_py(column)}, schema={_py(schema)})"
    return _Rendered(
        upgrade_sql=upgrade_sql,
        downgrade_sql=downgrade_sql,
        upgrade_code=upgrade_code,
        downgrade_code=downgrade_code,
        uses_timestamptz=type_name == "timestamptz",
        reversibility=OperationReversibility(
            operation_id=operation.id,
            kind=operation.kind,
            reversibility="partially_reversible",
            upgrade_effect=f"Add nullable column {schema}.{table}.{column}.",
            downgrade_effect=f"Drop column {schema}.{table}.{column}. {_COLUMN_LOSS}",
            data_loss_on_downgrade=True,
        ),
    )


def _render_index(snapshot: SchemaSnapshot, operation: PlanOperation) -> _Rendered:
    schema = _ident(snapshot.schema_name, "schema")
    table = _ident(operation.table, "table")
    columns = [_ident(column, "column") for column in operation.index_columns]
    index_name = _index_name(table, columns)
    existing_names = {
        index.name for table_snapshot in snapshot.tables for index in table_snapshot.indexes
    }
    if index_name in existing_names:
        raise ArtifactRejectedError(
            "unsafe_to_generate",
            f"Index name {index_name} already exists in the snapshot.",
        )
    quoted_columns = ", ".join(_quote(column) for column in columns)
    py_columns = ", ".join(_py(column) for column in columns)
    upgrade_sql = (
        f"CREATE INDEX {_quote(index_name)} ON {_qualified(schema, table)} ({quoted_columns});"
    )
    downgrade_sql = f"DROP INDEX {_qualified(schema, index_name)};"
    upgrade_code = (
        f"    op.create_index(\n        {_py(index_name)},\n        {_py(table)},\n"
        f"        [{py_columns}],\n        unique=False,\n        schema={_py(schema)},\n    )"
    )
    downgrade_code = (
        f"    op.drop_index({_py(index_name)}, table_name={_py(table)}, schema={_py(schema)})"
    )
    joined = ", ".join(columns)
    return _Rendered(
        upgrade_sql=upgrade_sql,
        downgrade_sql=downgrade_sql,
        upgrade_code=upgrade_code,
        downgrade_code=downgrade_code,
        uses_timestamptz=False,
        reversibility=OperationReversibility(
            operation_id=operation.id,
            kind=operation.kind,
            reversibility="reversible",
            upgrade_effect=f"Create index {index_name} on {schema}.{table} ({joined}).",
            downgrade_effect=(
                f"Drop index {index_name}. Row values in {schema}.{table} stay in place."
            ),
            data_loss_on_downgrade=False,
        ),
    )


def _render_rename_column(
    snapshot: SchemaSnapshot,
    operation: PlanOperation,
    assessment: RiskAssessment,
) -> _Rendered:
    schema = _ident(snapshot.schema_name, "schema")
    table = _ident(operation.table, "table")
    old_name = _ident(operation.column, "column")
    new_name = _ident(operation.new_name, "column")
    dependents = _dependents(assessment, operation.id)
    upgrade_sql = (
        f"ALTER TABLE {_qualified(schema, table)} RENAME COLUMN "
        f"{_quote(old_name)} TO {_quote(new_name)};"
    )
    downgrade_sql = (
        f"ALTER TABLE {_qualified(schema, table)} RENAME COLUMN "
        f"{_quote(new_name)} TO {_quote(old_name)};"
    )
    upgrade_code = (
        f"    op.alter_column(\n        {_py(table)},\n        {_py(old_name)},\n"
        f"        new_column_name={_py(new_name)},\n        schema={_py(schema)},\n    )"
    )
    downgrade_code = (
        f"    op.alter_column(\n        {_py(table)},\n        {_py(new_name)},\n"
        f"        new_column_name={_py(old_name)},\n        schema={_py(schema)},\n    )"
    )
    return _Rendered(
        upgrade_sql=upgrade_sql,
        downgrade_sql=downgrade_sql,
        upgrade_code=upgrade_code,
        downgrade_code=downgrade_code,
        uses_timestamptz=False,
        reversibility=OperationReversibility(
            operation_id=operation.id,
            kind=operation.kind,
            reversibility="reversible",
            upgrade_effect=f"Rename column {schema}.{table}.{old_name} to {new_name}.",
            downgrade_effect=_rename_downgrade(old_name, dependents),
            data_loss_on_downgrade=False,
        ),
    )


def _render_rename_table(
    snapshot: SchemaSnapshot,
    operation: PlanOperation,
    assessment: RiskAssessment,
) -> _Rendered:
    schema = _ident(snapshot.schema_name, "schema")
    old_name = _ident(operation.table, "table")
    new_name = _ident(operation.new_name, "table")
    dependents = _dependents(assessment, operation.id)
    upgrade_sql = f"ALTER TABLE {_qualified(schema, old_name)} RENAME TO {_quote(new_name)};"
    downgrade_sql = f"ALTER TABLE {_qualified(schema, new_name)} RENAME TO {_quote(old_name)};"
    upgrade_code = f"    op.rename_table({_py(old_name)}, {_py(new_name)}, schema={_py(schema)})"
    downgrade_code = f"    op.rename_table({_py(new_name)}, {_py(old_name)}, schema={_py(schema)})"
    return _Rendered(
        upgrade_sql=upgrade_sql,
        downgrade_sql=downgrade_sql,
        upgrade_code=upgrade_code,
        downgrade_code=downgrade_code,
        uses_timestamptz=False,
        reversibility=OperationReversibility(
            operation_id=operation.id,
            kind=operation.kind,
            reversibility="reversible",
            upgrade_effect=f"Rename table {schema}.{old_name} to {new_name}.",
            downgrade_effect=_rename_downgrade(old_name, dependents),
            data_loss_on_downgrade=False,
        ),
    )


def _rename_downgrade(previous_name: str, dependents: list[str]) -> str:
    if dependents:
        listed = ", ".join(dependents)
        return (
            f"Rename back to {previous_name}. Stored values stay in place. "
            f"Snapshot dependents: {listed}."
        )
    return (
        f"Rename back to {previous_name}. Stored values stay in place. "
        "The snapshot lists no dependents."
    )


def _dependents(assessment: RiskAssessment, operation_id: str) -> list[str]:
    names: list[str] = []
    for finding in assessment.findings:
        if finding.rule_id == "SP-R017" and finding.operation_id == operation_id:
            names.extend(finding.affected_objects)
    return names


def _alembic_source(
    *,
    migration_id: str,
    source_id: str,
    fingerprint: str,
    summary: str,
    upgrade: str,
    downgrade: str,
    uses_timestamptz: bool,
) -> str:
    dialect = "from sqlalchemy.dialects import postgresql\n" if uses_timestamptz else ""
    return (
        '"""SchemaPilot generated migration artifact.\n\n'
        "This module is not an applied Alembic revision. "
        "schemapilot_applied is false.\n"
        f"source_id={_py(source_id)}\n"
        f"schema_fingerprint={_py(fingerprint)}\n"
        f"summary={_py(summary)}\n"
        '"""\n'
        "from alembic import op\n"
        "import sqlalchemy as sa\n"
        f"{dialect}\n"
        f"revision = {_py(migration_id)}\n"
        "down_revision = None\n"
        "branch_labels = None\n"
        "depends_on = None\n"
        "schemapilot_applied = False\n\n\n"
        "def upgrade() -> None:\n"
        f"{upgrade}\n\n\n"
        "def downgrade() -> None:\n"
        f"{downgrade}\n"
    )


def _overall_reversibility(details: list[OperationReversibility]) -> ArtifactReversibility:
    kinds = {item.reversibility for item in details}
    if "irreversible" in kinds:
        return "irreversible"
    if "partially_reversible" in kinds:
        return "partially_reversible"
    return "reversible"


def _migration_id(snapshot: SchemaSnapshot, operations: list[PlanOperation]) -> str:
    payload = {
        "source_id": snapshot.source_id,
        "schema_name": snapshot.schema_name,
        "schema_fingerprint": snapshot.fingerprint,
        "operations": [
            {
                "id": operation.id,
                "kind": operation.kind,
                "table": operation.table,
                "column": operation.column,
                "data_type": operation.data_type,
                "nullable": operation.nullable,
                "default": operation.default,
                "new_name": operation.new_name,
                "index_columns": list(operation.index_columns),
                "constraint_kind": operation.constraint_kind,
                "check_expression": operation.check_expression,
            }
            for operation in operations
        ],
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
            "ascii"
        )
    ).hexdigest()
    return f"sp{digest[:12]}"


def _safe_output_dir(output_dir: Path | None) -> Path:
    directory = (ARTIFACTS_DIR if output_dir is None else output_dir).resolve()
    versions = _VERSIONS_DIR.resolve()
    if directory == versions or versions in directory.parents:
        raise ArtifactRejectedError(
            "unsafe_to_generate",
            "Artifacts are not written into the Alembic revision history.",
        )
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _index_name(table: str, columns: list[str]) -> str:
    candidate = "ix_" + "_".join([table, *columns])
    if _IDENTIFIER.fullmatch(candidate) is None or len(candidate) > 63:
        raise ArtifactRejectedError(
            "unsafe_to_generate",
            "The derived index name is not a safe PostgreSQL identifier.",
        )
    return candidate


def _ident(value: str | None, label: str) -> str:
    if value is None or _IDENTIFIER.fullmatch(value) is None:
        raise ArtifactRejectedError(
            "unsafe_to_generate",
            f"The {label} is not a safe identifier.",
        )
    return value


def _quote(identifier: str) -> str:
    return '"' + identifier + '"'


def _qualified(schema: str, name: str) -> str:
    return f"{_quote(schema)}.{_quote(name)}"


def _py(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)
