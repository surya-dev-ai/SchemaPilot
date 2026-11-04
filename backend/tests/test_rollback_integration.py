"""Live rollback tests. Skipped when schemapilot_sandbox is not configured.

The unavailable-sandbox test does not use that fixture. It attempts a connection
and must report not_verified. It is not a successful downgrade.
"""

import os
import subprocess
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.api import safety as safety_api
from app.api import sandbox as sandbox_api
from app.core.config import (
    Settings,
    UnsafeDatabaseConfigurationError,
    require_sandbox_execution,
)
from app.db.session import create_sandbox_engine
from app.schemas.sandbox import SandboxRunRequest
from app.services import (
    rollback_evidence_store,
    rollback_tester,
    sandbox_checkpoint_store,
    sandbox_manager,
    sandbox_snapshots,
)
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
from app.services.sandbox_snapshots import create_verified_checkpoint, restore_verified_checkpoint
from app.services.schema_inspector import inspect_sandbox
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine.url import make_url
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

    baseline = prepare_sandbox_baseline(settings)
    checkpoint = create_verified_checkpoint(settings, baseline.fingerprint)
    assert checkpoint.backup_status == "verified"
    assert checkpoint.checkpoint_id is not None

    restored = restore_verified_checkpoint(settings, checkpoint)
    assert restored.restore_status == "restore_verified"
    assert restored.schema_match is True
    assert restored.data_match is True
    assert restored.checkpoint_retained is True

    engine = create_sandbox_engine(settings)
    try:
        with engine.connect() as connection:
            _assert_identity(connection)
            review_count = connection.execute(
                text("SELECT count(*) FROM bookstore.reviews")
            ).scalar_one()
            assert review_count > 0
            statuses = list(
                connection.execute(
                    text("SELECT DISTINCT status FROM bookstore.orders ORDER BY status")
                ).scalars()
            )
            assert statuses == ["cancelled", "paid", "pending"]
            assert connection.execute(
                text("SELECT to_regclass('bookstore.orders_status_idx') IS NOT NULL")
            ).scalar_one() is True
            assert connection.execute(
                text(
                    "SELECT 1 FROM pg_catalog.pg_constraint "
                    "WHERE conname = 'orders_status_known'"
                )
            ).scalar_one() == 1
    finally:
        engine.dispose()
    return settings


def test_index_downgrade_can_match_the_baseline(
    sandbox_settings: Settings,
    tmp_path: Path,
) -> None:
    snapshot = prepare_sandbox_baseline(sandbox_settings)
    proposal = propose_migration(snapshot, "Add an index on the placed_at column of orders")
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
    assert report.snapshot_recovery is not None
    assert report.snapshot_recovery.backup_status == "verified"
    assert report.snapshot_recovery.restore_status == "restore_verified"
    assert report.snapshot_recovery.schema_match is True
    assert report.snapshot_recovery.data_match is True
    assert report.snapshot_recovery.checkpoint_retained is True
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


def test_destructive_drop_downgrade_reports_lost_values_and_schema_difference(
    sandbox_settings: Settings,
    tmp_path: Path,
) -> None:
    snapshot = prepare_sandbox_baseline(sandbox_settings)
    proposal = propose_migration(snapshot, "Drop the status column from orders")
    artifact = generate_migration(snapshot, proposal, assess_risk(snapshot, proposal), tmp_path)
    report = run_rollback_test(sandbox_settings, artifact.migration_id, directory=tmp_path)

    assert report.status == "partial_restoration"
    assert report.downgrade_executed is True
    assert report.schema_matches_baseline is False
    assert any("former values" in item for item in report.data_loss_limitations)
    assert any(
        check.name == "former_column_values" and check.status == "failed"
        for check in report.data_checks
    )
    assert report.snapshot_recovery is not None
    assert report.snapshot_recovery.restore_status == "restore_verified"
    assert report.snapshot_recovery.schema_match is True
    assert report.snapshot_recovery.data_match is True


def test_snapshot_restores_dropped_table_modified_rows_and_dependent_objects(
    sandbox_settings: Settings,
) -> None:
    baseline = prepare_sandbox_baseline(sandbox_settings)
    checkpoint = create_verified_checkpoint(sandbox_settings, baseline.fingerprint)
    assert checkpoint.backup_status == "verified"
    assert checkpoint.checkpoint_id is not None

    engine = create_sandbox_engine(sandbox_settings)
    try:
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE bookstore.orders SET status = 'paid' WHERE id = 1")
            )
            connection.execute(text("DROP TABLE bookstore.reviews"))
            connection.execute(text("ALTER TABLE bookstore.orders DROP COLUMN status"))
    finally:
        engine.dispose()


    restored = restore_verified_checkpoint(sandbox_settings, checkpoint)
    assert restored.restore_status == "restore_verified"
    assert restored.schema_match is True
    assert restored.data_match is True
    assert restored.checkpoint_retained is True

    engine = create_sandbox_engine(sandbox_settings)
    try:
        with engine.connect() as connection:
            _assert_identity(connection)
            assert connection.execute(
                text("SELECT count(*) FROM bookstore.reviews")
            ).scalar_one() > 0
            statuses = list(
                connection.execute(
                    text("SELECT DISTINCT status FROM bookstore.orders ORDER BY status")
                ).scalars()
            )
            assert statuses == ["cancelled", "paid", "pending"]
            assert connection.execute(
                text("SELECT to_regclass('bookstore.orders_status_idx') IS NOT NULL")
            ).scalar_one() is True
            assert connection.execute(
                text(
                    "SELECT 1 FROM pg_catalog.pg_constraint "
                    "WHERE conname = 'orders_status_known'"
                )
            ).scalar_one() == 1
    finally:
        engine.dispose()


def test_data_fingerprint_includes_sequence_is_called_state(
    sandbox_settings: Settings,
) -> None:
    engine = create_sandbox_engine(sandbox_settings)
    try:
        with engine.begin() as connection:
            last_value, is_called = connection.execute(
                text("SELECT last_value, is_called FROM bookstore.users_id_seq")
            ).one()
            assert last_value is not None
            connection.execute(
                text("SELECT setval('bookstore.users_id_seq', :value, :is_called)"),
                {"value": last_value, "is_called": is_called},
            )
            persisted_value_before = connection.execute(
                text(
                    "SELECT last_value FROM pg_catalog.pg_sequences "
                    "WHERE schemaname = 'bookstore' AND sequencename = 'users_id_seq'"
                )
            ).scalar_one()
            before = sandbox_snapshots._data_fingerprint(connection)
            connection.execute(
                text("SELECT setval('bookstore.users_id_seq', :value, :is_called)"),
                {"value": last_value, "is_called": not is_called},
            )
            persisted_value_after = connection.execute(
                text(
                    "SELECT last_value FROM pg_catalog.pg_sequences "
                    "WHERE schemaname = 'bookstore' AND sequencename = 'users_id_seq'"
                )
            ).scalar_one()
            after = sandbox_snapshots._data_fingerprint(connection)
            connection.execute(
                text("SELECT setval('bookstore.users_id_seq', :value, :is_called)"),
                {"value": last_value, "is_called": is_called},
            )

        # PostgreSQL's pg_sequences view reports NULL when is_called is false,
        # so the existing sequence fingerprint observes this nextval difference.
        assert persisted_value_before != persisted_value_after
        assert before != after, "Sequence is_called state changes the next generated value."
    finally:
        engine.dispose()


def test_rollback_test_restores_the_sandbox_state_that_existed_before_it_started(
    sandbox_settings: Settings,
    tmp_path: Path,
) -> None:
    baseline = prepare_sandbox_baseline(sandbox_settings)
    proposal = propose_migration(baseline, "Add a nullable text column called trial_note to users")
    artifact = generate_migration(
        baseline,
        proposal,
        assess_risk(baseline, proposal),
        tmp_path,
    )
    engine = create_sandbox_engine(sandbox_settings)
    try:
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE bookstore.users SET display_name = 'preserve-this-value' WHERE id = 1")
            )
    finally:
        engine.dispose()

    report = run_rollback_test(sandbox_settings, artifact.migration_id, directory=tmp_path)
    assert report.preexisting_sandbox_recovery is not None
    assert report.preexisting_sandbox_recovery.backup_status == "verified"
    assert report.preexisting_sandbox_recovery.restore_status == "restore_verified"
    assert report.preexisting_sandbox_recovery.schema_match is True
    assert report.preexisting_sandbox_recovery.data_match is True

    engine = create_sandbox_engine(sandbox_settings)
    try:
        with engine.connect() as connection:
            _assert_identity(connection)
            assert connection.execute(
                text("SELECT display_name FROM bookstore.users WHERE id = 1")
            ).scalar_one() == "preserve-this-value"
    finally:
        engine.dispose()


def test_api_validation_then_rollback_restores_pre_validation_data(
    sandbox_settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = prepare_sandbox_baseline(sandbox_settings)
    proposal = propose_migration(baseline, "Add a nullable text column called trial_note to users")
    artifact = generate_migration(
        baseline,
        proposal,
        assess_risk(baseline, proposal),
        tmp_path,
    )
    engine = create_sandbox_engine(sandbox_settings)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE bookstore.users SET display_name = "
                    "'captured-before-validation' WHERE id = 1"
                )
            )
    finally:
        engine.dispose()

    monkeypatch.setattr(sandbox_api, "ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(safety_api, "ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(sandbox_manager, "ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(rollback_tester, "ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(sandbox_checkpoint_store, "CHECKPOINT_SESSION_DIR", tmp_path / "sessions")
    monkeypatch.setattr(rollback_evidence_store, "ROLLBACK_EVIDENCE_DIR", tmp_path / "rollback")
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=sandbox_settings, llm_provider=None))
    )

    validation = sandbox_api.run_artifact_in_sandbox(
        "sandbox",
        artifact.migration_id,
        SandboxRunRequest(confirm=True),
        request,
    )
    assert validation.result == "passed"
    assert validation.pre_migration_snapshot_verified is True
    assert validation.snapshot_session_id is not None

    rollback = safety_api.run_rollback(
        "sandbox",
        artifact.migration_id,
        SandboxRunRequest(confirm=True, snapshot_session_id=validation.snapshot_session_id),
        request,
    )
    assert rollback.snapshot_session_id == validation.snapshot_session_id
    assert rollback.preexisting_sandbox_recovery is not None
    assert rollback.preexisting_sandbox_recovery.restore_status == "restore_verified"
    assert rollback.preexisting_sandbox_recovery.data_match is True

    engine = create_sandbox_engine(sandbox_settings)
    try:
        with engine.connect() as connection:
            _assert_identity(connection)
            assert connection.execute(
                text("SELECT display_name FROM bookstore.users WHERE id = 1")
            ).scalar_one() == "captured-before-validation"
    finally:
        engine.dispose()


def test_validation_downgrade_snapshot_and_report_are_separate_and_bound(
    sandbox_settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import workflows as workflows_api
    from app.db.session import create_app_engine
    from app.schemas.report import SafetyReportRequest
    from app.services.sandbox_checkpoint_store import load_checkpoint_session
    from app.services.workflow_store import create_tables, get_workflow, persist_workflow

    baseline = prepare_sandbox_baseline(sandbox_settings)
    engine = create_sandbox_engine(sandbox_settings)
    try:
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE bookstore.users SET display_name = 'phase5-evidence' WHERE id = 1")
            )
    finally:
        engine.dispose()

    column_name = f"phase5_note_{uuid.uuid4().hex[:6]}"
    request_text = f"Add a nullable text column called {column_name} to users"
    proposal = propose_migration(baseline, request_text)
    artifact = generate_migration(
        baseline,
        proposal,
        assess_risk(baseline, proposal),
        tmp_path,
    )
    sessions_dir = tmp_path / "sessions"
    rollback_dir = tmp_path / "rollback"
    monkeypatch.setattr(sandbox_api, "ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(safety_api, "ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(sandbox_manager, "ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(rollback_tester, "ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(sandbox_checkpoint_store, "CHECKPOINT_SESSION_DIR", sessions_dir)
    monkeypatch.setattr(rollback_evidence_store, "ROLLBACK_EVIDENCE_DIR", rollback_dir)
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=sandbox_settings, llm_provider=None))
    )

    validation = sandbox_api.run_artifact_in_sandbox(
        "sandbox", artifact.migration_id, SandboxRunRequest(confirm=True), request
    )
    assert validation.result == "passed"
    assert validation.snapshot_session_id is not None
    recorded = load_checkpoint_session(
        validation.snapshot_session_id,
        artifact.migration_id,
        artifact.checksum,
        directory=sessions_dir,
    )
    assert recorded.validation_run is not None
    assert recorded.validation_run.result == "passed"
    assert recorded.baseline_evidence is not None
    assert recorded.baseline_evidence.schema_fingerprint == artifact.schema_fingerprint

    downgrade = safety_api.run_sandbox_downgrade(
        "sandbox",
        artifact.migration_id,
        SandboxRunRequest(confirm=True, snapshot_session_id=validation.snapshot_session_id),
        request,
    )
    assert downgrade.downgrade_executed is True
    assert downgrade.status == "partial_restoration"
    assert downgrade.snapshot_recovery is None
    assert any(
        "not restored" in limitation or "does not restore" in limitation
        for limitation in downgrade.data_loss_limitations
    )
    after_downgrade = load_checkpoint_session(
        validation.snapshot_session_id,
        artifact.migration_id,
        artifact.checksum,
        directory=sessions_dir,
    )
    assert after_downgrade.downgrade_report is not None
    assert after_downgrade.checkpoint.restore_status == "not_attempted"

    restored = safety_api.run_rollback(
        "sandbox",
        artifact.migration_id,
        SandboxRunRequest(confirm=True, snapshot_session_id=validation.snapshot_session_id),
        request,
    )
    assert restored.downgrade_executed is True
    assert restored.snapshot_recovery is not None
    assert restored.snapshot_recovery.restore_status == "restore_verified"
    assert restored.snapshot_recovery.schema_match is True
    assert restored.snapshot_recovery.data_match is True

    report = safety_api.create_safety_report(
        "sandbox",
        artifact.migration_id,
        SafetyReportRequest(
            request=request_text,
            confirm=True,
            snapshot_session_id=validation.snapshot_session_id,
        ),
        request,
    )
    assert report.sandbox is not None
    assert report.sandbox.snapshot_session_id == validation.snapshot_session_id
    assert report.sandbox.artifact_checksum == artifact.checksum
    assert report.baseline_evidence is not None
    assert report.downgrade_executed is True
    assert report.snapshot_recovery is not None
    assert report.snapshot_recovery.restore_status == "restore_verified"
    assert report.eligible_for_review is True
    assert report.approved is False
    assert report.applied is False

    engine = create_sandbox_engine(sandbox_settings)
    try:
        with engine.connect() as connection:
            _assert_identity(connection)
            assert connection.execute(
                text("SELECT display_name FROM bookstore.users WHERE id = 1")
            ).scalar_one() == "phase5-evidence"
            assert connection.execute(
                text("SELECT to_regclass(:table_name) IS NOT NULL"),
                {"table_name": f"bookstore.{column_name}"},
            ).scalar_one() is False
    finally:
        engine.dispose()

    monkeypatch.setattr(workflows_api, "ARTIFACTS_DIR", tmp_path)
    proposal, assessment, report, rollback = workflows_api._build_report(
        sandbox_settings,
        "sandbox",
        artifact.migration_id,
        request_text,
        snapshot_session_id=validation.snapshot_session_id,
    )
    app_engine = create_app_engine(sandbox_settings)
    try:
        create_tables(app_engine)
        detail = persist_workflow(
            sandbox_settings,
            proposal=proposal,
            assessment=assessment,
            report=report,
            rollback=rollback,
            engine=app_engine,
        )
        history = get_workflow(sandbox_settings, detail.id, engine=app_engine)
        assert history.report.sandbox is not None
        assert history.report.sandbox.snapshot_session_id == validation.snapshot_session_id
        assert history.report.baseline_evidence is not None
        assert history.report.downgrade_executed is True
        assert history.report.snapshot_recovery is not None
        assert history.report.snapshot_recovery.restore_status == "restore_verified"
        assert history.eligible_for_review is True
    finally:
        app_engine.dispose()

def test_failed_replacement_clone_leaves_current_sandbox_untouched(
    sandbox_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = prepare_sandbox_baseline(sandbox_settings)
    checkpoint = create_verified_checkpoint(sandbox_settings, baseline.fingerprint)
    engine = create_sandbox_engine(sandbox_settings)
    try:
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE bookstore.users SET display_name = 'current-state' WHERE id = 1")
            )
    finally:
        engine.dispose()

    inspect_database = sandbox_snapshots._inspect_database

    def mismatch_replacement(url, database_name: str):
        if database_name.startswith("schemapilot_replacement_"):
            return "deliberate-mismatch", "deliberate-mismatch"
        return inspect_database(url, database_name)

    monkeypatch.setattr(sandbox_snapshots, "_inspect_database", mismatch_replacement)
    restored = restore_verified_checkpoint(sandbox_settings, checkpoint)
    assert restored.restore_status == "verification_incomplete"
    assert restored.restore_status != "restore_verified"

    engine = create_sandbox_engine(sandbox_settings)
    try:
        with engine.connect() as connection:
            _assert_identity(connection)
            assert connection.execute(
                text("SELECT display_name FROM bookstore.users WHERE id = 1")
            ).scalar_one() == "current-state"
    finally:
        engine.dispose()


def test_failure_between_database_rename_steps_restores_old_sandbox_and_reports_incomplete(
    sandbox_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = prepare_sandbox_baseline(sandbox_settings)
    checkpoint = create_verified_checkpoint(sandbox_settings, baseline.fingerprint)
    assert checkpoint.backup_status == "verified"
    assert checkpoint.checkpoint_id is not None

    engine = create_sandbox_engine(sandbox_settings)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE bookstore.users SET display_name = "
                    "'keep-current-state' WHERE id = 1"
                )
            )
    finally:
        engine.dispose()

    original_create_engine = sandbox_snapshots.create_engine

    def create_engine_with_rename_fault(*args, **kwargs):
        engine = original_create_engine(*args, **kwargs)

        def fail_new_database_rename(
            _connection,
            _cursor,
            statement: str,
            _parameters,
            _context,
            _executemany,
        ) -> None:
            if (
                statement.startswith('ALTER DATABASE "schemapilot_replacement_')
                and 'RENAME TO "schemapilot_sandbox"' in statement
            ):
                raise RuntimeError("Injected failure between sandbox database renames.")

        event.listen(engine, "before_cursor_execute", fail_new_database_rename)
        return engine

    monkeypatch.setattr(sandbox_snapshots, "create_engine", create_engine_with_rename_fault)
    sandbox_url = make_url(sandbox_settings.sandbox_database_url or "")
    try:
        result = restore_verified_checkpoint(sandbox_settings, checkpoint)
        assert result.restore_status == "verification_incomplete"
        assert result.restore_status != "restore_verified"
        assert result.checkpoint_retained is True

        engine = create_sandbox_engine(sandbox_settings)
        try:
            with engine.connect() as connection:
                _assert_identity(connection)
                assert connection.execute(
                    text("SELECT display_name FROM bookstore.users WHERE id = 1")
                ).scalar_one() == "keep-current-state"
        finally:
            engine.dispose()

        assert not sandbox_snapshots._database_exists_by_url(
            sandbox_url,
            f"schemapilot_previous_{checkpoint.checkpoint_id}",
        )
        assert not sandbox_snapshots._database_exists_by_url(
            sandbox_url,
            f"schemapilot_replacement_{checkpoint.checkpoint_id}",
        )
    finally:
        for prefix in (
            "schemapilot_replacement_",
            "schemapilot_previous_",
            "schemapilot_failed_",
        ):
            name = prefix + checkpoint.checkpoint_id
            if sandbox_snapshots._database_exists_by_url(sandbox_url, name):
                sandbox_snapshots._drop_database(
                    sandbox_url,
                    name,
                    allowed_prefixes=(prefix,),
                )

def test_process_crash_after_first_rename_is_discovered_and_resumed_after_restart(
    sandbox_settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A restarted API resumes an interrupted sandbox replacement safely."""
    engine = create_sandbox_engine(sandbox_settings)
    try:
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE bookstore.users SET display_name = 'crash-preserve' WHERE id = 1")
            )
    finally:
        engine.dispose()

    snapshot = inspect_sandbox(sandbox_settings)
    proposal = propose_migration(snapshot, "Add a nullable text column called crash_note to users")
    artifacts_dir = tmp_path / "artifacts"
    artifact = generate_migration(
        snapshot,
        proposal,
        assess_risk(snapshot, proposal),
        artifacts_dir,
    )
    sessions_dir = tmp_path / "sessions"
    rollback_dir = tmp_path / "rollback"
    monkeypatch.setattr(sandbox_api, "ARTIFACTS_DIR", artifacts_dir)
    monkeypatch.setattr(safety_api, "ARTIFACTS_DIR", artifacts_dir)
    monkeypatch.setattr(sandbox_manager, "ARTIFACTS_DIR", artifacts_dir)
    monkeypatch.setattr(rollback_tester, "ARTIFACTS_DIR", artifacts_dir)
    monkeypatch.setattr(sandbox_checkpoint_store, "CHECKPOINT_SESSION_DIR", sessions_dir)
    monkeypatch.setattr(rollback_evidence_store, "ROLLBACK_EVIDENCE_DIR", rollback_dir)
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=sandbox_settings, llm_provider=None))
    )
    validation = sandbox_api.run_artifact_in_sandbox(
        "sandbox",
        artifact.migration_id,
        SandboxRunRequest(confirm=True),
        request,
    )
    assert validation.result == "passed"
    assert validation.snapshot_session_id is not None
    session_id = validation.snapshot_session_id
    session = sandbox_checkpoint_store.find_active_checkpoint_session(
        artifact.migration_id,
        artifact.checksum,
        directory=sessions_dir,
    )
    assert session is not None
    assert session.checkpoint.backup_status == "verified"

    sandbox_url = sandbox_settings.sandbox_database_url
    assert sandbox_url is not None
    child_env = os.environ.copy()
    child_env.update(
        {
            "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
            "BACKEND_PATH": str(Path(__file__).resolve().parents[1]),
            "SCHEMAPILOT_SANDBOX_DATABASE_URL": sandbox_url,
            "SCHEMAPILOT_ALLOW_SANDBOX_EXECUTION": "true",
            "SCHEMAPILOT_TARGET_EXECUTION_ENABLED": "false",
            "SCHEMAPILOT_ALLOW_APP_MIGRATIONS": "false",
            "SCHEMAPILOT_LLM_ENABLED": "false",
            "ARTIFACTS_DIR": str(artifacts_dir),
            "SESSIONS_DIR": str(sessions_dir),
            "ROLLBACK_DIR": str(rollback_dir),
            "MIGRATION_ID": artifact.migration_id,
            "SESSION_ID": session_id,
        }
    )
    crash_script = """
import os
import sys
sys.path.insert(0, os.environ['BACKEND_PATH'])
from sqlalchemy import event
from app.core.config import Settings
from app.services import sandbox_snapshots
from app.main import app
from app.api import sandbox, safety
from app.services import sandbox_checkpoint_store, rollback_evidence_store
from fastapi.testclient import TestClient
from pathlib import Path
settings = Settings(_env_file=None)
app.state.settings = settings
sandbox.ARTIFACTS_DIR = Path(os.environ['ARTIFACTS_DIR'])
safety.ARTIFACTS_DIR = sandbox.ARTIFACTS_DIR
sandbox_checkpoint_store.CHECKPOINT_SESSION_DIR = Path(os.environ['SESSIONS_DIR'])
rollback_evidence_store.ROLLBACK_EVIDENCE_DIR = Path(os.environ['ROLLBACK_DIR'])
original_create_engine = sandbox_snapshots.create_engine
def crash_after_first_rename(*args, **kwargs):
    engine = original_create_engine(*args, **kwargs)
    def terminate_after_rename(
        _conn, _cursor, statement, _params, _context, _executemany
    ):
        if statement.startswith(
            'ALTER DATABASE "schemapilot_sandbox" RENAME TO "schemapilot_previous_'
        ):
            os._exit(86)
    event.listen(engine, 'after_cursor_execute', terminate_after_rename)
    return engine
sandbox_snapshots.create_engine = crash_after_first_rename
with TestClient(app) as client:
    client.post(
        f"/api/v1/sources/sandbox/artifacts/{os.environ['MIGRATION_ID']}/rollback",
        json={'confirm': True, 'snapshot_session_id': os.environ['SESSION_ID']},
    )
os._exit(87)
"""
    crashed = subprocess.run(
        [sys.executable, "-c", crash_script],
        env=child_env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert crashed.returncode == 86, "Crash worker exited before the first rename completed."

    # A fresh process represents backend restart; the API calls represent browser
    # refresh, recovery discovery, and the explicit resume action.
    restart_script = """
import os
import sys
sys.path.insert(0, os.environ['BACKEND_PATH'])
from pathlib import Path
from fastapi.testclient import TestClient
from app.core.config import Settings
from app.main import app
from app.api import sandbox, safety
from app.services import sandbox_checkpoint_store, rollback_evidence_store
app.state.settings = Settings(_env_file=None)
sandbox.ARTIFACTS_DIR = Path(os.environ['ARTIFACTS_DIR'])
safety.ARTIFACTS_DIR = sandbox.ARTIFACTS_DIR
sandbox_checkpoint_store.CHECKPOINT_SESSION_DIR = Path(os.environ['SESSIONS_DIR'])
rollback_evidence_store.ROLLBACK_EVIDENCE_DIR = Path(os.environ['ROLLBACK_DIR'])
with TestClient(app) as client:
    status = client.get('/api/v1/sources/sandbox/sandbox-session')
    assert status.status_code == 200, status.text
    assert status.json()['active'] is True, status.text
    assert status.json()['migration_id'] == os.environ['MIGRATION_ID'], status.text
    assert status.json()['snapshot_session_id'] == os.environ['SESSION_ID'], status.text
    assert status.json()['checkpoint_verified'] is True, status.text
    response = client.post(
        f"/api/v1/sources/sandbox/artifacts/{os.environ['MIGRATION_ID']}/rollback",
        json={'confirm': True, 'snapshot_session_id': os.environ['SESSION_ID']},
    )
    assert response.status_code == 200, response.text
    assert (
        response.json()["snapshot_recovery"]["restore_status"] == "restore_verified"
    ), response.text
    repeated = client.post(
        f"/api/v1/sources/sandbox/artifacts/{os.environ['MIGRATION_ID']}/rollback",
        json={'confirm': True, 'snapshot_session_id': os.environ['SESSION_ID']},
    )
    assert repeated.status_code == 409, repeated.text
"""
    restarted = subprocess.run(
        [sys.executable, "-c", restart_script],
        env=child_env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert restarted.returncode == 0, "Fresh API recovery process failed (diagnostics withheld)."

    monkeypatch.setattr(
        sandbox_snapshots,
        "_create_verified_replacement",
        lambda *_args, **_kwargs: pytest.fail("Verified canonical restore should be idempotent."),
    )
    repeated_restore = restore_verified_checkpoint(sandbox_settings, session.checkpoint)
    assert repeated_restore.restore_status == "restore_verified"
    assert repeated_restore.schema_match is True
    assert repeated_restore.data_match is True

    engine = create_sandbox_engine(sandbox_settings)
    try:
        with engine.connect() as connection:
            _assert_identity(connection)
            assert connection.execute(
                text("SELECT display_name FROM bookstore.users WHERE id = 1")
            ).scalar_one() == "crash-preserve"
            assert connection.execute(
                text("SELECT to_regclass('bookstore.crash_note') IS NULL")
            ).scalar_one() is True
    finally:
        engine.dispose()


def test_recovery_rebuilds_a_missing_staged_clone_from_the_retained_checkpoint(
    sandbox_settings: Settings,
) -> None:
    baseline = prepare_sandbox_baseline(sandbox_settings)
    checkpoint = create_verified_checkpoint(sandbox_settings, baseline.fingerprint)
    assert checkpoint.backup_status == "verified"
    assert checkpoint.checkpoint_id is not None

    engine = create_sandbox_engine(sandbox_settings)
    try:
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE bookstore.users SET display_name = 'preserve-previous' WHERE id = 1")
            )
    finally:
        engine.dispose()

    sandbox_url = make_url(sandbox_settings.sandbox_database_url or "")
    previous_name = f"schemapilot_previous_{checkpoint.checkpoint_id}"
    try:
        with sandbox_snapshots._maintenance_engine(sandbox_url) as maintenance:
            with maintenance.connect() as connection:
                sandbox_snapshots._assert_maintenance_identity(connection)
                connection.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_catalog.pg_stat_activity "
                        "WHERE datname = :database AND pid <> pg_backend_pid()"
                    ),
                    {"database": "schemapilot_sandbox"},
                )
                connection.execute(
                    text(
                        f'ALTER DATABASE "schemapilot_sandbox" RENAME TO "{previous_name}"'
                    )
                )

        restored = restore_verified_checkpoint(sandbox_settings, checkpoint)
        assert restored.restore_status == "restore_verified"
        assert restored.schema_match is True
        assert restored.data_match is True
        assert restored.checkpoint_retained is True
        assert not sandbox_snapshots._database_exists_by_url(sandbox_url, previous_name)
    finally:
        # Keep the isolated disposable database usable if this regression is red.
        if not sandbox_snapshots._database_exists_by_url(sandbox_url, "schemapilot_sandbox"):
            with sandbox_snapshots._maintenance_engine(sandbox_url) as maintenance:
                with maintenance.connect() as connection:
                    if sandbox_snapshots._database_exists(connection, previous_name):
                        connection.execute(
                            text(
                                f'ALTER DATABASE "{previous_name}" '
                                'RENAME TO "schemapilot_sandbox"'
                            )
                        )


def test_missing_checkpoint_returns_unavailable_without_touching_sandbox(
    sandbox_settings: Settings,
) -> None:
    from app.services.schema_inspector import inspect_sandbox

    baseline = prepare_sandbox_baseline(sandbox_settings)
    checkpoint = create_verified_checkpoint(sandbox_settings, baseline.fingerprint)
    before = inspect_sandbox(sandbox_settings)
    missing_checkpoint = checkpoint.model_copy(update={"checkpoint_id": uuid.uuid4().hex})

    result = restore_verified_checkpoint(sandbox_settings, missing_checkpoint)

    assert result.restore_status == "backup_unavailable"
    assert result.checkpoint_retained is False
    after = inspect_sandbox(sandbox_settings)
    assert after.fingerprint == before.fingerprint


@pytest.mark.parametrize(
    "damage_sql",
    [
        "UPDATE bookstore.orders SET status = 'paid' WHERE id = 1",
        "DROP TABLE bookstore.reviews",
    ],
    ids=["data-mismatch", "schema-mismatch"],
)
def test_corrupt_checkpoint_is_not_reported_as_restored(
    sandbox_settings: Settings,
    damage_sql: str,
) -> None:
    baseline = prepare_sandbox_baseline(sandbox_settings)
    checkpoint = create_verified_checkpoint(sandbox_settings, baseline.fingerprint)
    assert checkpoint.backup_status == "verified"
    assert checkpoint.checkpoint_id is not None

    sandbox_url = make_url(sandbox_settings.sandbox_database_url or "")
    checkpoint_url = sandbox_url.set(
        database=f"schemapilot_checkpoint_{checkpoint.checkpoint_id}"
    )
    checkpoint_engine = create_engine(checkpoint_url, connect_args={"connect_timeout": 5})
    try:
        with checkpoint_engine.begin() as connection:
            connection.execute(text(damage_sql))
    finally:
        checkpoint_engine.dispose()

    result = restore_verified_checkpoint(sandbox_settings, checkpoint)
    assert result.restore_status == "verification_incomplete"
    assert result.checkpoint_retained is True
    assert result.restore_status != "restore_verified"

    sandbox_engine = create_sandbox_engine(sandbox_settings)
    try:
        with sandbox_engine.connect() as connection:
            _assert_identity(connection)
            assert connection.execute(
                text("SELECT status FROM bookstore.orders WHERE id = 1")
            ).scalar_one() == "pending"
    finally:
        sandbox_engine.dispose()

def test_missing_downgrade_precondition_prevents_execution(
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
            connection.commit()
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
    assert report.status == "not_verified"
    assert report.downgrade_executed is False
    assert report.status != "exact_restoration"
    assert report.error
    assert "://" not in report.error


def test_live_schema_mismatch_is_failed(sandbox_settings: Settings, tmp_path: Path) -> None:
    snapshot = prepare_sandbox_baseline(sandbox_settings)
    proposal = propose_migration(snapshot, "Add an index on the placed_at column of orders")
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
            connection.commit()
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
