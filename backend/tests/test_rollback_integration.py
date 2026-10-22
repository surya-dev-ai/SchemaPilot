"""Live rollback tests. Skipped when schemapilot_sandbox is not configured.

The unavailable-sandbox test does not use that fixture. It attempts a connection
and must report not_verified. It is not a successful downgrade.
"""

from pathlib import Path

import pytest
from app.core.config import (
    Settings,
    UnsafeDatabaseConfigurationError,
    require_sandbox_execution,
)
from app.db.session import create_sandbox_engine
from app.services.migration_generator import generate_migration
from app.services.planner import propose_migration
from app.services.risk_engine import assess_risk
from app.services.rollback_tester import (
    classify_restoration,
    downgrade_verified_upgrade,
    live_schema_matches,
    read_baseline_evidence,
    run_rollback_test,
)
from app.services.sandbox_manager import _assert_identity, prepare_sandbox_baseline, run_sandbox
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

pytestmark = pytest.mark.integration


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


def test_index_downgrade_can_match_the_baseline(
    sandbox_settings: Settings,
    tmp_path: Path,
) -> None:
    snapshot = prepare_sandbox_baseline(sandbox_settings)
    proposal = propose_migration(snapshot, "Add an index on the user_id column of orders")
    artifact = generate_migration(
        snapshot,
        proposal,
        assess_risk(snapshot, proposal),
        tmp_path,
    )
    report = run_rollback_test(sandbox_settings, artifact.migration_id, directory=tmp_path)
    assert report.status == "exact_restoration"
    assert report.downgrade_executed is True
    assert report.schema_matches_baseline is True
    assert report.upgrade is not None
    assert report.upgrade.result == "passed"
    assert report.data_loss_limitations == []
    assert report.sandbox_database == "schemapilot_sandbox"
    assert report.sandbox_user == "schemapilot_sandbox"
    assert "://" not in report.model_dump_json()


def test_column_downgrade_does_not_restore_former_values(
    sandbox_settings: Settings,
    tmp_path: Path,
) -> None:
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
    report = run_rollback_test(sandbox_settings, artifact.migration_id, directory=tmp_path)
    assert report.status == "partial_restoration"
    assert report.schema_matches_baseline is True
    assert any("does not restore" in item for item in report.data_loss_limitations)
    values = next(check for check in report.data_checks if check.name == "former_column_values")
    assert values.status == "failed"


def test_failed_downgrade_is_not_exact_restoration(
    sandbox_settings: Settings,
    tmp_path: Path,
) -> None:
    snapshot = prepare_sandbox_baseline(sandbox_settings)
    evidence = read_baseline_evidence(sandbox_settings, snapshot)
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
    upgrade = run_sandbox(sandbox_settings, artifact.migration_id, directory=tmp_path)
    assert upgrade.result == "passed"
    engine = create_sandbox_engine(sandbox_settings)
    try:
        with engine.connect() as connection:
            _assert_identity(connection)
            with connection.begin():
                connection.execute(text('ALTER TABLE "bookstore"."users" DROP COLUMN "nickname"'))
    finally:
        engine.dispose()
    report = downgrade_verified_upgrade(
        sandbox_settings,
        artifact.migration_id,
        tmp_path,
        upgrade,
        evidence,
    )
    assert report.status == "failed"
    assert report.downgrade_executed is True
    assert report.status != "exact_restoration"
    assert report.error
    assert "://" not in report.error


def test_live_schema_mismatch_is_failed(sandbox_settings: Settings, tmp_path: Path) -> None:
    snapshot = prepare_sandbox_baseline(sandbox_settings)
    proposal = propose_migration(snapshot, "Add an index on the user_id column of orders")
    artifact = generate_migration(
        snapshot,
        proposal,
        assess_risk(snapshot, proposal),
        tmp_path,
    )
    report = run_rollback_test(sandbox_settings, artifact.migration_id, directory=tmp_path)
    assert report.baseline is not None
    assert report.schema_matches_baseline is True
    engine = create_sandbox_engine(sandbox_settings)
    try:
        with engine.connect() as connection:
            _assert_identity(connection)
            with connection.begin():
                connection.execute(
                    text('ALTER TABLE "bookstore"."users" ADD COLUMN "extra_marker" TEXT NULL')
                )
    finally:
        engine.dispose()
    assert live_schema_matches(sandbox_settings, report.baseline.schema_fingerprint) is False
    assert (
        classify_restoration(
            upgrade_passed=True,
            evidence_complete=True,
            downgrade_executed=True,
            downgrade_failed=False,
            schema_matches=False,
            data_restored=True,
            data_loss=False,
        )
        == "failed"
    )


def test_unavailable_sandbox_is_not_verified(tmp_path: Path) -> None:
    artifact = _offline_artifact(tmp_path)
    settings = Settings.model_construct(
        sandbox_database_url=(
            "postgresql+psycopg://schemapilot_sandbox:change_me_local_sandbox"
            "@127.0.0.1:1/schemapilot_sandbox"
        ),
        allow_sandbox_execution=True,
        demo_database_url=None,
        app_database_url=None,
        target_database_url=None,
    )
    report = run_rollback_test(settings, artifact.migration_id, directory=tmp_path)
    assert report.status == "not_verified"
    assert report.downgrade_executed is False
    assert report.status != "exact_restoration"
    assert "unavailable" in (report.error or "")


def _offline_artifact(directory: Path):
    from app.schemas.domain import ColumnSnapshot, SchemaSnapshot, TableSnapshot

    column = ColumnSnapshot(
        id="bookstore.users.email",
        name="email",
        ordinal_position=1,
        data_type="text",
        udt_name="text",
        nullable=False,
        identity="none",
        generated="never",
    )
    snapshot = SchemaSnapshot(
        source_id="bookstore-demo",
        database_name="schemapilot_bookstore",
        schema_name="bookstore",
        fingerprint="fingerprint-offline",
        tables=[
            TableSnapshot(
                id="bookstore.users",
                schema_name="bookstore",
                name="users",
                columns=[column],
                constraints=[],
                indexes=[],
            )
        ],
        dependencies=[],
    )
    proposal = propose_migration(snapshot, "Add a nullable text column called nickname to users")
    return generate_migration(snapshot, proposal, assess_risk(snapshot, proposal), directory)
