"""Live sandbox upgrades. Skipped when schemapilot_sandbox is not enabled or reachable.

A passing result in this file is the only sandbox success that came from PostgreSQL.
"""

import hashlib
from pathlib import Path

import pytest
from app.core.config import (
    Settings,
    UnsafeDatabaseConfigurationError,
    require_sandbox_execution,
)
from app.db.session import create_sandbox_engine
from app.schemas.artifacts import MigrationArtifact, OperationReversibility
from app.services.migration_generator import canonical_artifact_json, generate_migration
from app.services.planner import propose_migration
from app.services.risk_engine import assess_risk
from app.services.sandbox_manager import (
    SandboxRejected,
    cleanup_sandbox,
    load_verified_artifact,
    prepare_sandbox_baseline,
    probe_statement_timeout,
    run_sandbox,
)
from app.services.validator import validate_upgrade
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

pytestmark = pytest.mark.integration
VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"


@pytest.fixture
def sandbox_settings() -> Settings:
    settings = Settings(_env_file=".env")
    try:
        require_sandbox_execution(settings)
    except UnsafeDatabaseConfigurationError as exc:
        pytest.skip(
            "Sandbox integration test not run. "
            f"{exc} Start sandbox-db and set SCHEMAPILOT_ALLOW_SANDBOX_EXECUTION=true."
        )
    engine = create_sandbox_engine(settings)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except OperationalError:
        pytest.skip(
            "Sandbox integration test not run. "
            "The disposable sandbox PostgreSQL service is not reachable."
        )
    finally:
        engine.dispose()
    return settings


def test_sandbox_upgrade_adds_a_nullable_column(sandbox_settings: Settings, tmp_path: Path) -> None:
    before = _version_names()
    snapshot = prepare_sandbox_baseline(sandbox_settings)
    proposal = propose_migration(
        snapshot,
        "Add a nullable text column called nickname to users",
    )
    artifact = generate_migration(
        snapshot,
        proposal,
        assess_risk(snapshot, proposal),
        tmp_path,
    )
    result = run_sandbox(sandbox_settings, artifact.migration_id, directory=tmp_path)
    print("SANDBOX ERROR:", result.error)
    print("SANDBOX CHECKS:", [check.model_dump() for check in result.checks])
    assert result.result == "passed"
    assert result.upgrade_applied is True
    assert result.restored is False
    assert result.cleaned_up is False
    assert result.sandbox_database == "schemapilot_sandbox"
    assert result.sandbox_user == "schemapilot_sandbox"
    assert result.schema_fingerprint == snapshot.fingerprint
    assert result.artifact_checksum == artifact.checksum
    assert result.postgres_version
    assert result.started_at and result.finished_at
    assert "orders" in result.observed_tables
    column = _check(result.checks, "column:users.nickname")
    assert column.status == "passed"
    assert _check(result.checks, "risk_row_checks").status == "not_run"
    assert _check(result.checks, "duplicate_email").status == "passed"
    assert "://" not in result.model_dump_json()
    assert _version_names() == before


def test_failed_migration_records_the_verified_baseline(
    sandbox_settings: Settings,
    tmp_path: Path,
) -> None:
    snapshot = prepare_sandbox_baseline(sandbox_settings)
    artifact = _rename_conflict(snapshot.fingerprint, tmp_path)
    result = run_sandbox(sandbox_settings, artifact.migration_id, directory=tmp_path)
    restored = _check(result.checks, "baseline_restored")
    assert result.result == "failed"
    assert result.upgrade_applied is False
    assert result.restored is (restored.status == "passed")
    assert result.restored is True
    assert "users" in result.observed_tables
    assert "orders" in result.observed_tables
    assert result.error
    assert "://" not in result.error


def test_unexpected_fingerprint_does_not_execute_sql(
    sandbox_settings: Settings,
    tmp_path: Path,
) -> None:
    artifact = _rename_conflict("fingerprint-1", tmp_path)
    result = run_sandbox(sandbox_settings, artifact.migration_id, directory=tmp_path)
    assert result.result == "rejected"
    assert result.upgrade_applied is False
    assert result.restored is False
    assert _check(result.checks, "upgrade").status == "not_run"
    assert "users" in result.observed_tables


def test_sandbox_reports_constraint_violation(sandbox_settings: Settings) -> None:
    prepare_sandbox_baseline(sandbox_settings)
    engine = create_sandbox_engine(sandbox_settings)
    try:
        with engine.connect() as connection:
            checks = validate_upgrade(connection, [])
    finally:
        engine.dispose()
    duplicate = _check(checks, "duplicate_email")
    assert duplicate.status == "passed"
    assert "violation" in duplicate.detail
    assert _check(checks, "risk_row_checks").status == "not_run"
    assert _check(checks, "target_database").status == "not_run"


def test_checksum_mismatch_is_rejected_before_upgrade(
    sandbox_settings: Settings,
    tmp_path: Path,
) -> None:
    snapshot = prepare_sandbox_baseline(sandbox_settings)
    proposal = propose_migration(snapshot, "Add a nullable text column called nickname to users")
    artifact = generate_migration(
        snapshot,
        proposal,
        assess_risk(snapshot, proposal),
        tmp_path,
    )
    path = tmp_path / f"{artifact.migration_id}.json"
    edited = path.read_text(encoding="utf-8").replace("TEXT NULL", "TEXT NOT NULL")
    path.write_text(edited, encoding="utf-8")
    with pytest.raises(SandboxRejected) as exc:
        load_verified_artifact(tmp_path, artifact.migration_id)
    assert exc.value.code == "checksum_mismatch"


def test_statement_timeout_is_enforced(sandbox_settings: Settings) -> None:
    result = probe_statement_timeout(sandbox_settings, timeout_ms=50)
    assert result.result == "failed"
    assert result.upgrade_applied is False
    assert result.restored is False
    assert result.cleaned_up is False
    assert result.error == "Sandbox statement exceeded the timeout."
    assert _check(result.checks, "statement_timeout").status == "passed"


def test_cleanup_removes_the_bookstore_schema(sandbox_settings: Settings) -> None:
    prepare_sandbox_baseline(sandbox_settings)
    result = cleanup_sandbox(sandbox_settings)
    assert result.cleaned_up is True
    assert result.restored is False
    assert result.observed_tables == []
    assert result.sandbox_database == "schemapilot_sandbox"


def _check(checks, name: str):
    return next(check for check in checks if check.name == name)


def _version_names() -> list[str]:
    return sorted(path.name for path in VERSIONS.iterdir())


def _rename_conflict(fingerprint: str, directory: Path) -> MigrationArtifact:
    upgrade = '    op.rename_table("users", "orders", schema="bookstore")\n'
    source = (
        '"""generated conflict artifact\n"""\n'
        "from alembic import op\n"
        "import sqlalchemy as sa\n\n"
        'revision = "sp0123456789ab"\n'
        "down_revision = None\n"
        "branch_labels = None\n"
        "depends_on = None\n"
        "schemapilot_applied = False\n\n\n"
        "def upgrade() -> None:\n"
        f"{upgrade}\n\n"
        "def downgrade() -> None:\n"
        '    op.rename_table("orders", "users", schema="bookstore")\n'
    )
    artifact = MigrationArtifact(
        migration_id="sp0123456789ab",
        source_id="bookstore-demo",
        schema_name="bookstore",
        schema_fingerprint=fingerprint,
        summary="Rename users to orders.",
        status="generated",
        applied=False,
        operation_ids=["op-1"],
        sql_preview='ALTER TABLE "bookstore"."users" RENAME TO "orders";',
        downgrade_sql='ALTER TABLE "bookstore"."orders" RENAME TO "users";',
        alembic_source=source,
        reversibility="reversible",
        operation_reversibility=[
            OperationReversibility(
                operation_id="op-1",
                kind="rename_table",
                reversibility="reversible",
                upgrade_effect="Rename users to orders.",
                downgrade_effect="Rename back to users.",
                data_loss_on_downgrade=False,
            )
        ],
        checksum="",
        location="",
    )
    digest = hashlib.sha256(canonical_artifact_json(artifact).encode("ascii")).hexdigest()
    signed = artifact.model_copy(update={"checksum": f"sha256:{digest}"})
    (directory / f"{signed.migration_id}.json").write_text(
        signed.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (directory / f"{signed.migration_id}.py").write_text(
        signed.alembic_source,
        encoding="utf-8",
        newline="\n",
    )
    return signed
