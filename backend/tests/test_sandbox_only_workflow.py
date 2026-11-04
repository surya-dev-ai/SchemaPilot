"""Regression coverage for the browser sandbox-only recovery flow."""

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.core.config import Settings
from app.schemas.domain import SchemaSnapshot
from app.schemas.rollback import BaselineEvidence, SnapshotRecoveryReport
from app.schemas.sandbox import SandboxRunRequest
from app.services import sandbox_checkpoint_store as sessions
from app.services.sandbox_checkpoint_store import SandboxCheckpointSession


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
        allow_sandbox_execution=False,
        target_execution_enabled=False,
        allow_app_migrations=False,
    )


def _snapshot() -> SchemaSnapshot:
    return SchemaSnapshot.model_validate(
        {
            "source_id": "sandbox",
            "database_name": "schemapilot_sandbox",
            "schema_name": "bookstore",
            "tables": [],
            "dependencies": [],
            "fingerprint": "baseline-fingerprint",
        }
    )


def test_sandbox_plan_uses_sandbox_inspection_only(monkeypatch) -> None:
    from app.api import plans

    inspected = []
    monkeypatch.setattr(plans, "inspect_source", lambda *_: pytest.fail("demo source queried"))
    monkeypatch.setattr(
        plans, "inspect_sandbox", lambda settings: inspected.append(settings) or _snapshot(),
        raising=False,
    )
    expected = object()
    monkeypatch.setattr(plans, "create_proposal", lambda *_args, **_kwargs: expected)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=_settings())))

    result = plans.create_plan(
        "sandbox",
        plans.PlanCreateRequest(request="Add a nullable text column called note to users."),
        request,
    )

    assert result is expected
    assert inspected == [request.app.state.settings]


def test_sandbox_plan_never_opens_demo_database(monkeypatch) -> None:
    from app.api import plans

    def forbidden_demo_connection(*_args, **_kwargs):
        raise AssertionError("sandbox planning attempted a demo connection")

    monkeypatch.setattr(plans, "inspect_source", forbidden_demo_connection)
    monkeypatch.setattr(plans, "inspect_sandbox", lambda *_: _snapshot(), raising=False)
    monkeypatch.setattr(plans, "create_proposal", lambda *_args, **_kwargs: "proposal")
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=_settings())))
    result = plans.create_plan(
        "sandbox",
        plans.PlanCreateRequest(request="Add a nullable text column called note to users."),
        request,
    )
    assert result == "proposal"


def test_sandbox_validation_never_resets_or_reseeds_existing_schema() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "app" / "services" / "sandbox_manager.py"
    ).read_text(encoding="utf-8")
    run_body = source.split("def run_sandbox(", 1)[1].split(
        "def prepare_sandbox_baseline(", 1
    )[0]
    assert "_prepare_baseline(connection)" not in run_body
    assert "_execute_reset(connection)" not in run_body
    assert "seed.sql" not in run_body


def test_sandbox_inspection_uses_only_read_only_sandbox_engine(monkeypatch) -> None:
    from app.services import schema_inspector

    calls = []

    class Result:
        def one(self):
            return "schemapilot_sandbox", "schemapilot_sandbox", "on"

    class Connection:
        def exec_driver_sql(self, statement):
            calls.append(statement)

        def execute(self, *_args, **_kwargs):
            return Result()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class Engine:
        def connect(self):
            return Connection()

        def dispose(self):
            calls.append("disposed")

    monkeypatch.setattr(schema_inspector, "require_sandbox_execution", lambda _settings: "sandbox")
    monkeypatch.setattr(schema_inspector, "create_sandbox_engine", lambda _settings: Engine())
    monkeypatch.setattr(
        schema_inspector,
        "create_bookstore_source_engine",
        lambda *_: pytest.fail("demo database engine was created"),
    )
    monkeypatch.setattr(
        schema_inspector,
        "load_catalog",
        lambda _connection: schema_inspector.Catalog((), (), (), ()),
    )

    result = schema_inspector.inspect_sandbox(_settings())

    assert calls == ["SET TRANSACTION READ ONLY", "disposed"]
    assert result.source_id == "sandbox"
    assert result.database_name == "schemapilot_sandbox"


def test_explicit_sandbox_baseline_uses_sandbox_identity(monkeypatch) -> None:
    from app.services import sandbox_manager, schema_inspector

    class Connection:
        def commit(self):
            pass

        def begin(self):
            return nullcontext()

        def execute(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(
        sandbox_manager,
        "_session",
        lambda *_args, **_kwargs: nullcontext(Connection()),
    )
    monkeypatch.setattr(sandbox_manager, "_assert_identity", lambda _connection: None)
    monkeypatch.setattr(sandbox_manager, "_set_timeout", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sandbox_manager, "_prepare_baseline", lambda _connection: None)
    monkeypatch.setattr(
        sandbox_manager,
        "load_catalog",
        lambda _connection: schema_inspector.Catalog((), (), (), ()),
    )

    snapshot = sandbox_manager.prepare_sandbox_baseline(_settings(), _lifecycle_lock_held=True)

    assert snapshot.source_id == "sandbox"
    assert snapshot.database_name == "schemapilot_sandbox"


def test_rollback_schema_verification_uses_sandbox_identity(monkeypatch) -> None:
    from app.services import rollback_tester

    identity = {}
    monkeypatch.setattr(rollback_tester, "_connect", lambda _settings: nullcontext(object()))
    monkeypatch.setattr(rollback_tester, "load_catalog", lambda _connection: object())

    def assemble(_catalog, *, source_id="bookstore-demo", database_name="schemapilot_bookstore"):
        identity.update(source_id=source_id, database_name=database_name)
        return SimpleNamespace(fingerprint="expected-fingerprint")

    monkeypatch.setattr(rollback_tester, "assemble_snapshot", assemble)

    assert rollback_tester.live_schema_matches(_settings(), "expected-fingerprint") is True
    assert identity == {"source_id": "sandbox", "database_name": "schemapilot_sandbox"}


def test_checkpoint_failure_prevents_sandbox_migration(monkeypatch) -> None:
    from app.api import sandbox as sandbox_api
    from fastapi import HTTPException

    artifact = SimpleNamespace(
        source_id="sandbox", checksum="sha256:x", schema_fingerprint="baseline-fingerprint"
    )
    monkeypatch.setattr(sandbox_api, "load_verified_artifact", lambda *_: artifact)
    monkeypatch.setattr(sandbox_api, "sandbox_lifecycle_lock", lambda *_: nullcontext())
    monkeypatch.setattr(sandbox_api, "inspect_sandbox", lambda *_: _snapshot())
    monkeypatch.setattr(
        sandbox_api,
        "read_baseline_evidence",
        lambda *_: BaselineEvidence(
            schema_fingerprint="baseline-fingerprint",
            tables=[],
            row_counts={},
            emails=[],
        ),
    )
    monkeypatch.setattr(
        sandbox_api,
        "create_verified_checkpoint",
        lambda *_args, **_kwargs: SnapshotRecoveryReport(backup_status="failed"),
    )
    monkeypatch.setattr(
        sandbox_api,
        "run_sandbox",
        lambda *_args, **_kwargs: pytest.fail("migration ran without a verified checkpoint"),
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=_settings())))

    with pytest.raises(HTTPException) as error:
        sandbox_api.run_artifact_in_sandbox(
            "sandbox",
            "sp0123456789ab",
            SandboxRunRequest(confirm=True),
            request,
        )

    assert error.value.status_code == 409
    assert error.value.detail["error"] == "pre_migration_snapshot_unverified"


def test_successful_sandbox_validation_is_persisted_with_artifact_and_session(
    monkeypatch, tmp_path: Path
) -> None:
    from app.api import sandbox as sandbox_api
    from app.schemas.sandbox import SandboxRun

    monkeypatch.setattr(sessions, "CHECKPOINT_SESSION_DIR", tmp_path)
    artifact = SimpleNamespace(
        source_id="sandbox", checksum="sha256:test", schema_fingerprint="baseline-fingerprint"
    )
    checkpoint = SnapshotRecoveryReport(
        checkpoint_id="2" * 32,
        backup_status="verified",
        baseline_schema_fingerprint="baseline-fingerprint",
        restored_schema_fingerprint="baseline-fingerprint",
        baseline_data_fingerprint="data-before",
        restored_data_fingerprint="data-before",
        schema_match=True,
        data_match=True,
        checkpoint_retained=True,
    )
    run = SandboxRun(
        migration_id="sp0123456789ab",
        source_id="sandbox",
        schema_fingerprint="baseline-fingerprint",
        artifact_checksum="sha256:test",
        sandbox_database="schemapilot_sandbox",
        sandbox_user="schemapilot_sandbox",
        postgres_version="16",
        started_at="2026-11-03T00:00:00Z",
        finished_at="2026-11-03T00:00:01Z",
        result="passed",
        upgrade_applied=True,
        restored=False,
        cleaned_up=False,
        checks=[],
        observed_tables=["users"],
    )
    monkeypatch.setattr(sandbox_api, "load_verified_artifact", lambda *_: artifact)
    monkeypatch.setattr(sandbox_api, "sandbox_lifecycle_lock", lambda *_: nullcontext())
    monkeypatch.setattr(sandbox_api, "assert_no_active_checkpoint_session", lambda: None)
    monkeypatch.setattr(sandbox_api, "inspect_sandbox", lambda *_: _snapshot())
    monkeypatch.setattr(
        sandbox_api,
        "read_baseline_evidence",
        lambda *_: BaselineEvidence(
            schema_fingerprint="baseline-fingerprint",
            tables=["users"],
            row_counts={"users": 1},
            emails=[],
        ),
    )
    monkeypatch.setattr(sandbox_api, "create_verified_checkpoint", lambda *_a, **_k: checkpoint)
    monkeypatch.setattr(sandbox_api, "run_sandbox", lambda *_a, **_k: run)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=_settings())))

    response = sandbox_api.run_artifact_in_sandbox(
        "sandbox", "sp0123456789ab", SandboxRunRequest(confirm=True), request
    )
    persisted = sessions.load_checkpoint_session(
        response.snapshot_session_id,
        response.migration_id,
        response.artifact_checksum,
        directory=tmp_path,
    )

    assert response.result == "passed"
    assert persisted.session_id == response.snapshot_session_id
    assert persisted.migration_id == response.migration_id
    assert persisted.artifact_checksum == response.artifact_checksum
    assert persisted.validation_run is not None
    assert persisted.validation_run.result == "passed"
    assert persisted.validation_run.snapshot_session_id == persisted.session_id


def test_refreshed_checkpoint_status_returns_persisted_validation_evidence(
    tmp_path: Path, monkeypatch
) -> None:
    from app.api import sandbox as sandbox_api
    from app.schemas.sandbox import SandboxRun

    monkeypatch.setattr(sessions, "CHECKPOINT_SESSION_DIR", tmp_path)
    run = SandboxRun(
        migration_id="sp0123456789ab",
        source_id="sandbox",
        schema_fingerprint="schema-before",
        artifact_checksum="sha256:test",
        sandbox_database="schemapilot_sandbox",
        sandbox_user="schemapilot_sandbox",
        postgres_version="16",
        started_at="2026-11-03T00:00:00Z",
        finished_at="2026-11-03T00:00:01Z",
        result="passed",
        upgrade_applied=True,
        restored=False,
        cleaned_up=False,
        checks=[],
        observed_tables=["users"],
        snapshot_session_id="1" * 32,
        pre_migration_snapshot_verified=True,
    )
    session = SandboxCheckpointSession(
        session_id="1" * 32,
        migration_id=run.migration_id,
        artifact_checksum=run.artifact_checksum,
        state="ready",
        checkpoint=SnapshotRecoveryReport(
            checkpoint_id="2" * 32,
            backup_status="verified",
            baseline_schema_fingerprint="schema-before",
            restored_schema_fingerprint="schema-before",
            baseline_data_fingerprint="data-before",
            restored_data_fingerprint="data-before",
            schema_match=True,
            data_match=True,
            checkpoint_retained=True,
        ),
        validation_run=run,
        baseline_evidence=BaselineEvidence(
            schema_fingerprint="schema-before",
            tables=["users"],
            row_counts={"users": 1},
            emails=[],
        ),
    )
    sessions.save_checkpoint_session(session, directory=tmp_path)
    monkeypatch.setattr(sandbox_api, "ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(
        sandbox_api,
        "load_verified_artifact",
        lambda *_: SimpleNamespace(checksum=run.artifact_checksum, source_id="sandbox"),
    )

    status = sandbox_api.get_sandbox_checkpoint_session("sandbox")

    assert status.validation_run is not None
    assert status.validation_run.migration_id == run.migration_id
    assert status.validation_run.snapshot_session_id == status.snapshot_session_id


def test_sandbox_session_rejects_validation_from_a_different_artifact() -> None:
    from app.schemas.sandbox import SandboxRun
    from pydantic import ValidationError

    invalid_run = SandboxRun(
        migration_id="sp999999999999",
        source_id="sandbox",
        schema_fingerprint="schema-before",
        artifact_checksum="sha256:other",
        sandbox_database="schemapilot_sandbox",
        sandbox_user="schemapilot_sandbox",
        postgres_version="16",
        started_at="2026-11-03T00:00:00Z",
        finished_at="2026-11-03T00:00:01Z",
        result="passed",
        upgrade_applied=True,
        restored=False,
        cleaned_up=False,
        checks=[],
        observed_tables=["users"],
        snapshot_session_id="1" * 32,
        pre_migration_snapshot_verified=True,
    )
    with pytest.raises(ValidationError, match="validation_run"):
        SandboxCheckpointSession(
            session_id="1" * 32,
            migration_id="sp0123456789ab",
            artifact_checksum="sha256:test",
            state="ready",
            checkpoint=SnapshotRecoveryReport(
                checkpoint_id="2" * 32,
                backup_status="verified",
                baseline_schema_fingerprint="schema-before",
                restored_schema_fingerprint="schema-before",
                baseline_data_fingerprint="data-before",
                restored_data_fingerprint="data-before",
                schema_match=True,
                data_match=True,
                checkpoint_retained=True,
            ),
            validation_run=invalid_run,
        )


def test_downgrade_has_a_distinct_api_action_from_snapshot_restore() -> None:
    from app.api.safety import router

    paths = {route.path for route in router.routes}
    assert "/sources/{source_id}/artifacts/{migration_id}/downgrade" in paths
    assert "/sources/{source_id}/artifacts/{migration_id}/rollback" in paths


def test_snapshot_restore_evidence_does_not_claim_migration_downgrade(monkeypatch) -> None:
    from app.api import safety

    session = SandboxCheckpointSession(
        session_id="1" * 32,
        migration_id="sp0123456789ab",
        artifact_checksum="sha256:test",
        state="ready",
        checkpoint=SnapshotRecoveryReport(
            checkpoint_id="2" * 32,
            backup_status="verified",
            baseline_schema_fingerprint="schema-before",
            restored_schema_fingerprint="schema-before",
            baseline_data_fingerprint="data-before",
            restored_data_fingerprint="data-before",
            schema_match=True,
            data_match=True,
            checkpoint_retained=True,
        ),
    )
    artifact = SimpleNamespace(
        migration_id="sp0123456789ab", checksum="sha256:test", source_id="sandbox"
    )
    monkeypatch.setattr(safety, "load_verified_artifact", lambda *_: artifact)
    monkeypatch.setattr(safety, "sandbox_lifecycle_lock", lambda *_: nullcontext())
    monkeypatch.setattr(safety, "load_checkpoint_session", lambda *_a, **_k: session)
    monkeypatch.setattr(
        safety,
        "restore_verified_checkpoint",
        lambda *_a, **_k: session.checkpoint.model_copy(
            update={"restore_status": "restore_verified", "schema_match": True, "data_match": True}
        ),
    )
    monkeypatch.setattr(safety, "save_rollback_evidence", lambda *_: None)
    monkeypatch.setattr(safety, "transition_checkpoint_session", lambda _s, **_k: session)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=_settings())))

    report = safety.run_rollback(
        "sandbox",
        artifact.migration_id,
        SandboxRunRequest(confirm=True, snapshot_session_id=session.session_id),
        request,
    )

    assert report.snapshot_recovery.restore_status == "restore_verified"
    assert report.downgrade_executed is False


def test_downgrade_action_records_its_result_on_the_matching_session(
    monkeypatch, tmp_path: Path
) -> None:
    from app.api import safety
    from app.schemas.rollback import RollbackReport
    from app.schemas.sandbox import SandboxRun

    monkeypatch.setattr(sessions, "CHECKPOINT_SESSION_DIR", tmp_path)
    checkpoint = SnapshotRecoveryReport(
        checkpoint_id="2" * 32,
        backup_status="verified",
        baseline_schema_fingerprint="schema-before",
        restored_schema_fingerprint="schema-before",
        baseline_data_fingerprint="data-before",
        restored_data_fingerprint="data-before",
        schema_match=True,
        data_match=True,
        checkpoint_retained=True,
    )
    run = SandboxRun(
        migration_id="sp0123456789ab",
        source_id="sandbox",
        schema_fingerprint="schema-before",
        artifact_checksum="sha256:test",
        sandbox_database="schemapilot_sandbox",
        sandbox_user="schemapilot_sandbox",
        postgres_version="16",
        started_at="2026-11-03T00:00:00Z",
        finished_at="2026-11-03T00:00:01Z",
        result="passed",
        upgrade_applied=True,
        restored=False,
        cleaned_up=False,
        checks=[],
        observed_tables=["users"],
        snapshot_session_id="1" * 32,
        pre_migration_snapshot_verified=True,
    )
    baseline = BaselineEvidence(
        schema_fingerprint="schema-before", tables=["users"], row_counts={"users": 1}, emails=[]
    )
    session = SandboxCheckpointSession(
        session_id="1" * 32,
        migration_id=run.migration_id,
        artifact_checksum=run.artifact_checksum,
        state="ready",
        checkpoint=checkpoint,
        validation_run=run,
        baseline_evidence=baseline,
    )
    sessions.save_checkpoint_session(session, directory=tmp_path)
    artifact = SimpleNamespace(source_id="sandbox", checksum="sha256:test")
    monkeypatch.setattr(safety, "ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(safety, "load_verified_artifact", lambda *_: artifact)
    monkeypatch.setattr(safety, "sandbox_lifecycle_lock", lambda *_: nullcontext())
    monkeypatch.setattr(
        safety,
        "downgrade_verified_upgrade",
        lambda *_args, **_kwargs: RollbackReport(
            migration_id=run.migration_id,
            artifact_checksum=run.artifact_checksum,
            source_id="sandbox",
            schema_fingerprint=run.schema_fingerprint,
            sandbox_database="schemapilot_sandbox",
            sandbox_user="schemapilot_sandbox",
            postgres_version="16",
            started_at="2026-11-03T00:00:00Z",
            finished_at="2026-11-03T00:00:02Z",
            status="partial_restoration",
            upgrade=run,
            baseline=baseline,
            downgrade_executed=True,
            schema_matches_baseline=True,
            data_checks=[],
            data_loss_limitations=["New-column values are not restored by downgrade."],
        ),
    )
    monkeypatch.setattr(safety, "save_rollback_evidence", lambda *_: None)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=_settings())))

    report = safety.run_sandbox_downgrade(
        "sandbox",
        run.migration_id,
        SandboxRunRequest(confirm=True, snapshot_session_id=session.session_id),
        request,
    )
    saved = sessions.load_checkpoint_session(
        session.session_id, run.migration_id, run.artifact_checksum, directory=tmp_path
    )

    assert report.downgrade_executed is True
    assert report.snapshot_recovery is None
    assert saved.downgrade_report is not None
    assert saved.downgrade_report.status == "partial_restoration"
    assert saved.checkpoint.restore_status == "not_attempted"


def test_failed_snapshot_restore_never_reports_exact_success(monkeypatch, tmp_path: Path) -> None:
    from app.api import safety

    session = SandboxCheckpointSession(
        session_id="1" * 32,
        migration_id="sp0123456789ab",
        artifact_checksum="sha256:test",
        state="ready",
        checkpoint=SnapshotRecoveryReport(
            checkpoint_id="2" * 32,
            backup_status="verified",
            baseline_schema_fingerprint="schema-before",
            restored_schema_fingerprint="schema-before",
            baseline_data_fingerprint="data-before",
            restored_data_fingerprint="data-before",
            schema_match=True,
            data_match=True,
            checkpoint_retained=True,
        ),
    )
    artifact = SimpleNamespace(
        migration_id="sp0123456789ab",
        checksum="sha256:test",
        source_id="sandbox",
    )
    transitions = []
    monkeypatch.setattr(safety, "load_verified_artifact", lambda *_: artifact)
    monkeypatch.setattr(safety, "sandbox_lifecycle_lock", lambda *_: nullcontext())
    monkeypatch.setattr(safety, "load_checkpoint_session", lambda *_args, **_kwargs: session)
    monkeypatch.setattr(
        safety,
        "transition_checkpoint_session",
        lambda _session, **kwargs: transitions.append(kwargs) or _session,
    )
    monkeypatch.setattr(
        safety,
        "restore_verified_checkpoint",
        lambda *_args, **_kwargs: session.checkpoint.model_copy(
            update={"restore_status": "restore_failed", "schema_match": False, "data_match": False}
        ),
    )
    monkeypatch.setattr(
        safety,
        "save_rollback_evidence",
        lambda _report: None,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=_settings())))

    report = safety.run_rollback(
        "sandbox",
        "sp0123456789ab",
        SandboxRunRequest(confirm=True, snapshot_session_id="1" * 32),
        request,
    )

    assert report.status != "exact_restoration"
    assert report.snapshot_recovery.restore_status == "restore_failed"
    assert any(item["new_state"] == "recovery_required" for item in transitions)


def test_sandbox_checkpoint_is_discovered_after_a_new_client_refresh(
    tmp_path: Path, monkeypatch
) -> None:
    from app.api import sandbox as sandbox_api

    monkeypatch.setattr(sessions, "CHECKPOINT_SESSION_DIR", tmp_path)
    monkeypatch.setattr(sandbox_api, "ARTIFACTS_DIR", tmp_path)
    session = SandboxCheckpointSession(
        session_id="1" * 32,
        migration_id="sp0123456789ab",
        artifact_checksum="sha256:test",
        state="ready",
        checkpoint=SnapshotRecoveryReport(
            checkpoint_id="2" * 32,
            backup_status="verified",
            baseline_schema_fingerprint="schema-before",
            restored_schema_fingerprint="schema-before",
            baseline_data_fingerprint="data-before",
            restored_data_fingerprint="data-before",
            schema_match=True,
            data_match=True,
            checkpoint_retained=True,
        ),
    )
    sessions.save_checkpoint_session(session, directory=tmp_path)
    monkeypatch.setattr(
        sandbox_api,
        "load_verified_artifact",
        lambda *_: SimpleNamespace(checksum="sha256:test", source_id="sandbox"),
    )

    # Calling the route in a fresh request context models a page reload: the
    # state is read from the durable session store, not browser memory.
    response = sandbox_api.get_sandbox_checkpoint_session("sandbox")

    assert response.active is True
    assert response.snapshot_session_id == "1" * 32
