"""Artifact tests. These tests build a snapshot in memory and do not open PostgreSQL."""

import ast
from pathlib import Path

import pytest
from app.core.config import Settings
from app.db import session as session_module
from app.demo.bookstore import USER_TABLE_COMMENT
from app.main import create_app
from app.schemas.domain import (
    ColumnSnapshot,
    ConstraintSnapshot,
    DependencySnapshot,
    IndexSnapshot,
    SchemaSnapshot,
    TableSnapshot,
)
from app.schemas.planning import MigrationProposal, PlanOperation
from app.schemas.risk import RiskAssessment
from app.services.migration_generator import (
    ARTIFACTS_DIR,
    ArtifactRejectedError,
    generate_migration,
    verify_artifact,
)
from app.services.planner import propose_migration
from app.services.risk_engine import assess_risk
from fastapi.testclient import TestClient

MALICIOUS = USER_TABLE_COMMENT
VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"


def _column(
    table: str,
    name: str,
    *,
    nullable: bool = False,
    position: int = 1,
) -> ColumnSnapshot:
    return ColumnSnapshot(
        id=f"bookstore.{table}.{name}",
        name=name,
        ordinal_position=position,
        data_type="text",
        udt_name="text",
        nullable=nullable,
        identity="none",
        generated="never",
        comment=MALICIOUS,
    )


def _table(
    name: str,
    columns: list[ColumnSnapshot],
    constraints: list[ConstraintSnapshot] | None = None,
    indexes: list[IndexSnapshot] | None = None,
) -> TableSnapshot:
    return TableSnapshot(
        id=f"bookstore.{name}",
        schema_name="bookstore",
        name=name,
        comment=MALICIOUS,
        columns=columns,
        constraints=constraints or [],
        indexes=indexes or [],
    )


def _snapshot() -> SchemaSnapshot:
    return SchemaSnapshot(
        source_id="bookstore-demo",
        database_name="schemapilot_bookstore",
        schema_name="bookstore",
        fingerprint="fingerprint-1",
        tables=[
            _table(
                "users",
                [
                    _column("users", "id", position=1),
                    _column("users", "email", position=2),
                    _column("users", "display_name", nullable=True, position=3),
                ],
                constraints=[
                    ConstraintSnapshot(
                        id="bookstore.users.users_pkey",
                        name="users_pkey",
                        kind="primary_key",
                        columns=["id"],
                    )
                ],
            ),
            _table(
                "orders",
                [
                    _column("orders", "id", position=1),
                    _column("orders", "user_id", position=2),
                    _column("orders", "status", position=3),
                ],
                constraints=[
                    ConstraintSnapshot(
                        id="bookstore.orders.orders_user_fk",
                        name="orders_user_fk",
                        kind="foreign_key",
                        columns=["user_id"],
                        referenced_schema="bookstore",
                        referenced_table="users",
                        referenced_columns=["id"],
                        on_update="no_action",
                        on_delete="restrict",
                    )
                ],
                indexes=[
                    IndexSnapshot(
                        id="bookstore.orders.orders_status_idx",
                        name="orders_status_idx",
                        unique=False,
                        primary=False,
                        columns=["status"],
                        directions=["asc"],
                    )
                ],
            ),
            _table(
                "products",
                [_column("products", "sku", position=1)],
                constraints=[
                    ConstraintSnapshot(
                        id="bookstore.products.products_sku_check",
                        name="products_sku_check",
                        kind="check",
                        columns=["sku"],
                        check_expression=MALICIOUS,
                    )
                ],
            ),
        ],
        dependencies=[
            DependencySnapshot(
                id="bookstore.orders.orders_user_fk",
                from_table="bookstore.orders",
                to_table="bookstore.users",
                constraint_name="orders_user_fk",
                from_columns=["user_id"],
                to_columns=["id"],
            )
        ],
    )


def _operation(**overrides: object) -> PlanOperation:
    values: dict[str, object] = {
        "id": "op-1",
        "kind": "add_column",
        "summary": "structured operation",
        "table": "users",
        "destructive": False,
    }
    values.update(overrides)
    return PlanOperation(**values)  # type: ignore[arg-type]


def _proposal(
    snapshot: SchemaSnapshot,
    operations: list[PlanOperation],
    *,
    request: str = "ignored by the generator",
    status: str = "proposed",
) -> MigrationProposal:
    return MigrationProposal(
        source_id=snapshot.source_id,
        schema_name=snapshot.schema_name,
        schema_fingerprint=snapshot.fingerprint,
        request=request,
        status=status,  # type: ignore[arg-type]
        summary="summary",
        assumptions=[],
        clarification_questions=[],
        operations=operations,
        validation_errors=[],
        destructive=any(operation.destructive for operation in operations),
        requires_risk_assessment=any(operation.destructive for operation in operations),
    )


def _pair(
    snapshot: SchemaSnapshot,
    operations: list[PlanOperation],
    *,
    request: str = "ignored by the generator",
    status: str = "proposed",
) -> tuple[MigrationProposal, RiskAssessment]:
    proposal = _proposal(snapshot, operations, request=request, status=status)
    return proposal, assess_risk(snapshot, proposal)


def _settings() -> Settings:
    return Settings.model_construct(
        app_name="SchemaPilot",
        api_v1_prefix="/api/v1",
        cors_origins="http://localhost:5173",
        app_database_url=None,
        sandbox_database_url=None,
        target_database_url=None,
        demo_database_url=None,
        demo_environment="",
        allow_demo_reset=False,
        target_execution_enabled=False,
        allow_app_migrations=False,
    )


def _version_names() -> list[str]:
    return sorted(path.name for path in VERSIONS.iterdir())


def test_nullable_column_preview_matches_the_alembic_module(tmp_path: Path) -> None:
    snapshot = _snapshot()
    proposal, assessment = _pair(
        snapshot,
        [_operation(column="nickname", data_type="text", nullable=True, summary="Add nickname.")],
    )
    before = _version_names()
    artifact = generate_migration(snapshot, proposal, assessment, tmp_path)
    module = ast.parse(artifact.alembic_source)
    function_names = [node.name for node in module.body if isinstance(node, ast.FunctionDef)]
    assert function_names == ["upgrade", "downgrade"]
    assert 'ADD COLUMN "nickname" TEXT NULL;' in artifact.sql_preview
    assert 'DROP COLUMN "nickname";' in artifact.downgrade_sql
    assert "op.add_column(" in artifact.alembic_source
    assert "op.drop_column(" in artifact.alembic_source
    assert "sa.Text()" in artifact.alembic_source
    assert "nickname" in artifact.alembic_source
    assert artifact.applied is False
    assert artifact.status == "generated"
    assert artifact.reversibility == "partially_reversible"
    assert artifact.operation_reversibility[0].data_loss_on_downgrade is True
    effect = artifact.operation_reversibility[0].downgrade_effect
    assert "does not recover its former values" in effect
    assert artifact.source_id == "bookstore-demo"
    assert artifact.schema_fingerprint == "fingerprint-1"
    assert artifact.summary == "Add nickname."
    assert verify_artifact(artifact) is True
    assert (tmp_path / f"{artifact.migration_id}.py").read_text(encoding="utf-8") == (
        artifact.alembic_source
    )
    assert _version_names() == before
    assert "alembic/versions" not in artifact.location.replace("\\", "/")
    assert MALICIOUS not in artifact.model_dump_json()
    assert "DROP TABLE" not in artifact.alembic_source
    assert "op.execute" not in artifact.alembic_source


@pytest.mark.parametrize(
    ("data_type", "sql_type", "alembic_type"),
    [
        ("integer", "INTEGER", "sa.Integer()"),
        ("bigint", "BIGINT", "sa.BigInteger()"),
        ("boolean", "BOOLEAN", "sa.Boolean()"),
        ("timestamptz", "TIMESTAMP WITH TIME ZONE", "postgresql.TIMESTAMP(timezone=True)"),
    ],
)
def test_supported_nullable_types(
    tmp_path: Path,
    data_type: str,
    sql_type: str,
    alembic_type: str,
) -> None:
    snapshot = _snapshot()
    proposal, assessment = _pair(
        snapshot,
        [_operation(column="extra_value", data_type=data_type, nullable=True)],
    )
    artifact = generate_migration(snapshot, proposal, assessment, tmp_path)
    assert sql_type in artifact.sql_preview
    assert alembic_type in artifact.alembic_source
    assert "NOT NULL" not in artifact.sql_preview
    ast.parse(artifact.alembic_source)


def test_soft_delete_column_is_a_nullable_timestamp(tmp_path: Path) -> None:
    snapshot = _snapshot()
    proposal, assessment = _pair(
        snapshot,
        [_operation(column="deleted_at", data_type="timestamptz", nullable=True)],
    )
    artifact = generate_migration(snapshot, proposal, assessment, tmp_path)
    assert 'ADD COLUMN "deleted_at" TIMESTAMP WITH TIME ZONE NULL;' in artifact.sql_preview
    assert "op.add_column(" in artifact.alembic_source
    assert artifact.operation_reversibility[0].data_loss_on_downgrade is True


def test_index_preview_matches_the_alembic_module(tmp_path: Path) -> None:
    snapshot = _snapshot()
    proposal, assessment = _pair(
        snapshot,
        [
            _operation(
                kind="add_index",
                table="orders",
                index_columns=["user_id"],
                summary="Index orders.user_id.",
            )
        ],
    )
    artifact = generate_migration(snapshot, proposal, assessment, tmp_path)
    assert (
        'CREATE INDEX "ix_orders_user_id" ON "bookstore"."orders" ("user_id");'
        == artifact.sql_preview
    )
    assert 'DROP INDEX "bookstore"."ix_orders_user_id";' == artifact.downgrade_sql
    assert "op.create_index(" in artifact.alembic_source
    assert "op.drop_index(" in artifact.alembic_source
    assert artifact.reversibility == "reversible"
    assert artifact.operation_reversibility[0].data_loss_on_downgrade is False
    ast.parse(artifact.alembic_source)


def test_rename_column_and_table_keep_downgrade_names(tmp_path: Path) -> None:
    snapshot = _snapshot()
    column_proposal, column_assessment = _pair(
        snapshot,
        [
            _operation(
                kind="rename_column",
                table="orders",
                column="status",
                new_name="order_status",
            )
        ],
    )
    table_proposal, table_assessment = _pair(
        snapshot,
        [_operation(kind="rename_table", table="users", new_name="customers")],
    )
    column_artifact = generate_migration(snapshot, column_proposal, column_assessment, tmp_path)
    table_artifact = generate_migration(snapshot, table_proposal, table_assessment, tmp_path)
    assert 'RENAME COLUMN "status" TO "order_status";' in column_artifact.sql_preview
    assert 'RENAME COLUMN "order_status" TO "status";' in column_artifact.downgrade_sql
    assert "op.alter_column(" in column_artifact.alembic_source
    assert "bookstore.orders.orders_status_idx" in (
        column_artifact.operation_reversibility[0].downgrade_effect
    )
    assert 'RENAME TO "customers";' in table_artifact.sql_preview
    assert 'RENAME TO "users";' in table_artifact.downgrade_sql
    assert "op.rename_table(" in table_artifact.alembic_source
    table_effect = table_artifact.operation_reversibility[0].downgrade_effect
    assert "bookstore.orders.orders_user_fk" in table_effect
    assert column_artifact.reversibility == "reversible"
    assert table_artifact.reversibility == "reversible"
    ast.parse(column_artifact.alembic_source)
    ast.parse(table_artifact.alembic_source)


def test_two_operations_share_one_checksum(tmp_path: Path) -> None:
    snapshot = _snapshot()
    proposal, assessment = _pair(
        snapshot,
        [
            _operation(
                id="op-1",
                column="nickname",
                data_type="text",
                nullable=True,
                summary="Add nickname.",
            ),
            _operation(
                id="op-2",
                kind="add_index",
                table="users",
                index_columns=["display_name"],
                summary="Index display_name.",
            ),
        ],
    )
    artifact = generate_migration(snapshot, proposal, assessment, tmp_path)
    assert "nickname" in artifact.sql_preview
    assert "ix_users_display_name" in artifact.sql_preview
    assert "op.add_column(" in artifact.alembic_source
    assert "op.create_index(" in artifact.alembic_source
    assert artifact.operation_ids == ["op-1", "op-2"]
    assert artifact.reversibility == "partially_reversible"
    ast.parse(artifact.alembic_source)


def test_checksum_is_stable_and_content_changes_invalidate_it(tmp_path: Path) -> None:
    snapshot = _snapshot()
    proposal, assessment = _pair(
        snapshot,
        [_operation(column="nickname", data_type="text", nullable=True)],
    )
    first = generate_migration(snapshot, proposal, assessment, tmp_path)
    second = generate_migration(snapshot, proposal, assessment, tmp_path)
    moved = first.model_copy(update={"location": "elsewhere/not-applied.py"})
    changed_sql = first.model_copy(update={"sql_preview": first.sql_preview + "\n-- edited"})
    changed_module = first.model_copy(
        update={"alembic_source": first.alembic_source.replace("nickname", "alias")}
    )
    assert first.checksum == second.checksum
    assert first.migration_id == second.migration_id
    assert first.alembic_source == second.alembic_source
    assert verify_artifact(moved) is True
    assert verify_artifact(changed_sql) is False
    assert verify_artifact(changed_module) is False


def test_policy_blocked_and_not_run_checks_are_rejected(tmp_path: Path) -> None:
    snapshot = _snapshot()
    blocked, blocked_risk = _pair(
        snapshot,
        [_operation(kind="destructive", table="orders", destructive=True)],
    )
    pending, pending_risk = _pair(
        snapshot,
        [
            _operation(
                column="loyalty_points",
                data_type="integer",
                nullable=True,
                default="0",
            )
        ],
    )
    unique, unique_risk = _pair(
        snapshot,
        [
            _operation(
                kind="add_constraint",
                column="display_name",
                constraint_kind="unique",
            )
        ],
    )
    check, check_risk = _pair(
        snapshot,
        [
            _operation(
                kind="add_constraint",
                table="orders",
                constraint_kind="check",
                check_expression="status in ('paid')",
            )
        ],
    )
    with pytest.raises(ArtifactRejectedError) as blocked_error:
        generate_migration(snapshot, blocked, blocked_risk, tmp_path)
    with pytest.raises(ArtifactRejectedError) as pending_error:
        generate_migration(snapshot, pending, pending_risk, tmp_path)
    with pytest.raises(ArtifactRejectedError) as unique_error:
        generate_migration(snapshot, unique, unique_risk, tmp_path)
    with pytest.raises(ArtifactRejectedError) as check_error:
        generate_migration(snapshot, check, check_risk, tmp_path)
    assert blocked_error.value.code == "policy_blocked"
    assert pending_error.value.code == "data_check_not_run"
    assert "not a passed check" in pending_error.value.message
    assert unique_error.value.code == "data_check_not_run"
    assert check_error.value.code == "data_check_not_run"
    assert list(tmp_path.iterdir()) == []


def test_low_static_score_does_not_generate_a_constraint(tmp_path: Path) -> None:
    snapshot = _snapshot()
    proposal, assessment = _pair(
        snapshot,
        [_operation(kind="add_constraint", column="email", constraint_kind="not_null")],
    )
    assert assessment.artifact_eligible is True
    assert assessment.findings[0].severity == "low"
    assert assessment.findings[0].data_check == "not_required"
    with pytest.raises(ArtifactRejectedError) as exc:
        generate_migration(snapshot, proposal, assessment, tmp_path)
    assert exc.value.code == "unsupported_operation"
    assert "not a passed live row check" in exc.value.message


def test_unsupported_plan_and_tampered_assessment_are_rejected(tmp_path: Path) -> None:
    snapshot = _snapshot()
    rejected = propose_migration(snapshot, "Change the type of users.email to integer")
    rejected_risk = assess_risk(snapshot, rejected)
    clarifying, clarifying_risk = _pair(snapshot, [], status="needs_clarification")
    drop, drop_risk = _pair(
        snapshot,
        [_operation(kind="destructive", table="orders", destructive=True)],
    )
    forged = drop_risk.model_copy(
        update={
            "artifact_eligible": True,
            "policy_blocked": False,
            "eligibility_reason": "eligible",
            "findings": [],
        }
    )
    with pytest.raises(ArtifactRejectedError) as rejected_error:
        generate_migration(snapshot, rejected, rejected_risk, tmp_path)
    with pytest.raises(ArtifactRejectedError) as clarifying_error:
        generate_migration(snapshot, clarifying, clarifying_risk, tmp_path)
    with pytest.raises(ArtifactRejectedError) as forged_error:
        generate_migration(snapshot, drop, forged, tmp_path)
    assert rejected_error.value.code == "plan_not_proposed"
    assert clarifying_error.value.code == "plan_not_proposed"
    assert forged_error.value.code == "provenance_mismatch"


def test_request_text_is_not_copied_into_the_artifact(tmp_path: Path) -> None:
    snapshot = _snapshot()
    proposal, assessment = _pair(
        snapshot,
        [_operation(column="nickname", data_type="text", nullable=True)],
        request=MALICIOUS,
    )
    artifact = generate_migration(snapshot, proposal, assessment, tmp_path)
    serialized = artifact.model_dump_json()
    assert "DROP TABLE" not in serialized
    assert MALICIOUS not in artifact.sql_preview
    assert MALICIOUS not in artifact.alembic_source


def test_generator_does_not_connect_or_write_revision_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_called(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("generator connected to a database")

    monkeypatch.setattr(session_module, "create_engine", fail_if_called)
    monkeypatch.setattr(session_module, "create_demo_engine", fail_if_called)
    monkeypatch.setattr(session_module, "create_bookstore_source_engine", fail_if_called)
    source = Path("app/services/migration_generator.py").read_text(encoding="utf-8")
    assert ".comment" not in source
    assert "create_engine" not in source
    snapshot = _snapshot()
    proposal = propose_migration(snapshot, "Add a nullable text column called nickname to users")
    before = _version_names()
    artifact = generate_migration(snapshot, proposal, assess_risk(snapshot, proposal), tmp_path)
    assert artifact.applied is False
    assert _version_names() == before
    with pytest.raises(ArtifactRejectedError) as exc:
        generate_migration(snapshot, proposal, assess_risk(snapshot, proposal), VERSIONS)
    assert exc.value.code == "unsafe_to_generate"


def test_default_directory_is_outside_alembic_versions() -> None:
    versions = VERSIONS.resolve()
    artifacts = ARTIFACTS_DIR.resolve()
    assert artifacts != versions
    assert versions not in artifacts.parents
    assert artifacts.name == "generated"


def test_artifact_route_writes_a_preview_and_hides_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_called(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("artifact route opened a database engine")

    monkeypatch.setattr(session_module, "create_engine", fail_if_called)
    monkeypatch.setattr(session_module, "create_demo_engine", fail_if_called)
    monkeypatch.setattr(session_module, "create_bookstore_source_engine", fail_if_called)
    monkeypatch.setattr("app.services.migration_generator.ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(
        "app.api.artifacts.inspect_source",
        lambda _settings, _source_id: _snapshot(),
    )
    before = _version_names()
    client = TestClient(create_app(_settings()))
    created = client.post(
        "/api/v1/sources/bookstore-demo/artifacts",
        json={"request": "Add a nullable text column called nickname to users"},
    )
    blocked = client.post(
        "/api/v1/sources/bookstore-demo/artifacts",
        json={"request": "Drop table orders"},
    )
    extra = client.post(
        "/api/v1/sources/bookstore-demo/artifacts",
        json={"request": "Add a column", "database_url": "postgresql://secret@db/prod"},
    )
    assert created.status_code == 200
    body = created.json()
    assert body["applied"] is False
    assert body["status"] == "generated"
    assert "nickname" in body["sql_preview"]
    assert body["checksum"].startswith("sha256:")
    assert "DROP TABLE" not in created.text
    assert "postgresql" not in created.text
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["error"] == "policy_blocked"
    assert extra.status_code == 422
    assert "secret" not in extra.text
    assert _version_names() == before
    assert any(path.suffix == ".py" for path in tmp_path.iterdir())
