"""Rollback and report unit tests. These tests do not prove a live PostgreSQL downgrade."""

import hashlib
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.core.config import Settings
from app.db import session as session_module
from app.main import create_app
from app.schemas.artifacts import MigrationArtifact, OperationReversibility
from app.schemas.domain import ColumnSnapshot, SchemaSnapshot, TableSnapshot
from app.schemas.planning import Assumption, MigrationProposal, PlanOperation
from app.schemas.report import SafetyReport, SafetyReportRequest
from app.schemas.rollback import BaselineEvidence, RollbackReport, SnapshotRecoveryReport
from app.schemas.sandbox import SandboxRun
from app.services.migration_generator import generate_migration
from app.services.planner import propose_migration
from app.services.report_service import build_safety_report
from app.services.risk_engine import assess_risk
from app.services.rollback_tester import (
    DowngradeRejected,
    classify_restoration,
    parse_downgrade_sql,
    run_rollback_test,
)
from fastapi.testclient import TestClient

SANDBOX_URL = (
    "postgresql+psycopg://schemapilot_sandbox:change_me_local_sandbox"
    "@127.0.0.1:5433/schemapilot_sandbox"
)


@pytest.fixture(autouse=True)
def _avoid_real_sandbox_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit tests must not connect to PostgreSQL just to acquire the lifecycle lock."""

    @contextmanager
    def no_database_lock(_settings):
        yield

    monkeypatch.setattr("app.services.rollback_tester.sandbox_lifecycle_lock", no_database_lock)
    monkeypatch.setattr("app.services.sandbox_snapshots.sandbox_lifecycle_lock", no_database_lock)


def _column(table: str, name: str, *, nullable: bool = False, position: int = 1) -> ColumnSnapshot:
    return ColumnSnapshot(
        id=f"bookstore.{table}.{name}",
        name=name,
        ordinal_position=position,
        data_type="text",
        udt_name="text",
        nullable=nullable,
        identity="none",
        generated="never",
    )


def _table(name: str, columns: list[ColumnSnapshot]) -> TableSnapshot:
    return TableSnapshot(
        id=f"bookstore.{name}",
        schema_name="bookstore",
        name=name,
        columns=columns,
        constraints=[],
        indexes=[],
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
                    _column("users", "id"),
                    _column("users", "email", position=2),
                    _column("users", "display_name", nullable=True, position=3),
                ],
            ),
            _table(
                "orders",
                [
                    _column("orders", "id"),
                    _column("orders", "user_id", position=2),
                    _column("orders", "status", position=3),
                ],
            ),
        ],
        dependencies=[],
    )


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_name": "SchemaPilot",
        "api_v1_prefix": "/api/v1",
        "cors_origins": "http://localhost:5173",
        "sandbox_database_url": SANDBOX_URL,
        "allow_sandbox_execution": True,
        "target_execution_enabled": False,
        "allow_app_migrations": False,
        "allow_demo_reset": False,
        "demo_environment": "",
    }
    values.update(overrides)
    return Settings.model_construct(**values)  # type: ignore[arg-type]


def _generated(request: str, directory: Path) -> tuple[SchemaSnapshot, MigrationArtifact]:
    snapshot = _snapshot()
    proposal = propose_migration(snapshot, request)
    artifact = generate_migration(snapshot, proposal, assess_risk(snapshot, proposal), directory)
    return snapshot, artifact


def _evidence() -> BaselineEvidence:
    return BaselineEvidence(
        schema_fingerprint="fingerprint-1",
        tables=["orders", "users"],
        row_counts={"users": 3, "products": 4, "orders": 2, "order_items": 3},
        emails=["mira@example.test"],
    )


def _checkpoint() -> SnapshotRecoveryReport:
    return SnapshotRecoveryReport(
        checkpoint_id="a" * 32,
        backup_status="verified",
        restore_status="not_attempted",
        baseline_schema_fingerprint="fingerprint-1",
        restored_schema_fingerprint="fingerprint-1",
        baseline_data_fingerprint="data-fingerprint",
        restored_data_fingerprint="data-fingerprint",
        schema_match=True,
        data_match=True,
        checkpoint_retained=True,
    )


def _upgrade(result: str = "passed", applied: bool = True) -> SandboxRun:
    return SandboxRun(
        migration_id="sp0123456789ab",
        source_id="bookstore-demo",
        schema_fingerprint="fingerprint-1",
        artifact_checksum="sha256:abc",
        sandbox_database="schemapilot_sandbox",
        sandbox_user="schemapilot_sandbox",
        postgres_version="16.0",
        started_at="2026-10-15T00:00:00+00:00",
        finished_at="2026-10-15T00:00:01+00:00",
        result=result,  # type: ignore[arg-type]
        upgrade_applied=applied,
        restored=False,
        cleaned_up=False,
        checks=[],
        observed_tables=["orders", "users"],
        error=None if result == "passed" else "upgrade failed",
    )


def test_classify_requires_complete_evidence() -> None:
    assert (
        classify_restoration(
            upgrade_passed=False,
            evidence_complete=True,
            downgrade_executed=False,
            downgrade_failed=False,
            schema_matches=None,
            data_restored=None,
            data_loss=False,
        )
        == "not_verified"
    )
    assert (
        classify_restoration(
            upgrade_passed=True,
            evidence_complete=False,
            downgrade_executed=True,
            downgrade_failed=False,
            schema_matches=True,
            data_restored=True,
            data_loss=False,
        )
        == "not_verified"
    )
    assert (
        classify_restoration(
            upgrade_passed=True,
            evidence_complete=True,
            downgrade_executed=True,
            downgrade_failed=True,
            schema_matches=True,
            data_restored=True,
            data_loss=False,
        )
        == "failed"
    )
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
    assert (
        classify_restoration(
            upgrade_passed=True,
            evidence_complete=True,
            downgrade_executed=True,
            downgrade_failed=False,
            schema_matches=True,
            data_restored=True,
            data_loss=True,
        )
        == "partial_restoration"
    )
    assert (
        classify_restoration(
            upgrade_passed=True,
            evidence_complete=True,
            downgrade_executed=True,
            downgrade_failed=False,
            schema_matches=False,
            data_restored=True,
            data_loss=True,
        )
        == "partial_restoration"
    )
    assert (
        classify_restoration(
            upgrade_passed=True,
            evidence_complete=True,
            downgrade_executed=True,
            downgrade_failed=False,
            schema_matches=True,
            data_restored=True,
            data_loss=False,
        )
        == "exact_restoration"
    )


def test_failed_upgrade_does_not_run_a_downgrade(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _snapshot_artifact = _generated("Add a nullable text column called nickname to users", tmp_path)
    artifact = _snapshot_artifact[1]
    calls = {"downgrade": 0}

    def fail_downgrade(*_args: object, **_kwargs: object) -> None:
        calls["downgrade"] += 1
        raise AssertionError("downgrade ran after a failed upgrade")

    monkeypatch.setattr(
        "app.services.rollback_tester.prepare_sandbox_baseline",
        lambda _settings, **_kwargs: _snapshot(),
    )
    monkeypatch.setattr(
        "app.services.rollback_tester.read_baseline_evidence",
        lambda _settings, _snapshot_value: _evidence(),
    )
    monkeypatch.setattr(
        "app.services.rollback_tester.create_verified_checkpoint",
        lambda *_args, **_kwargs: _checkpoint(),
    )
    monkeypatch.setattr(
        "app.services.rollback_tester.restore_verified_checkpoint",
        lambda _settings, checkpoint, **_kwargs: checkpoint.model_copy(
            update={"restore_status": "restore_verified", "schema_match": True, "data_match": True}
        ),
    )
    monkeypatch.setattr(
        "app.services.rollback_tester.run_sandbox",
        lambda *_args, **_kwargs: _upgrade("failed", applied=False),
    )
    monkeypatch.setattr("app.services.rollback_tester._downgrade", fail_downgrade)
    report = run_rollback_test(_settings(), artifact.migration_id, directory=tmp_path)
    assert report.status == "not_verified"
    assert report.downgrade_executed is False
    assert calls["downgrade"] == 0


def test_missing_baseline_is_not_verified(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    artifact = _generated("Add a nullable text column called nickname to users", tmp_path)[1]
    monkeypatch.setattr(
        "app.services.rollback_tester.prepare_sandbox_baseline",
        lambda _settings, **_kwargs: _snapshot(),
    )
    monkeypatch.setattr(
        "app.services.rollback_tester.read_baseline_evidence",
        lambda _settings, _snapshot_value: None,
    )
    monkeypatch.setattr(
        "app.services.rollback_tester.create_verified_checkpoint",
        lambda *_args, **_kwargs: _checkpoint(),
    )
    monkeypatch.setattr(
        "app.services.rollback_tester.restore_verified_checkpoint",
        lambda _settings, checkpoint, **_kwargs: checkpoint.model_copy(
            update={"restore_status": "restore_verified", "schema_match": True, "data_match": True}
        ),
    )
    monkeypatch.setattr(
        "app.services.rollback_tester.run_sandbox",
        lambda *_args, **_kwargs: _upgrade(),
    )
    report = run_rollback_test(_settings(), artifact.migration_id, directory=tmp_path)
    assert report.status == "not_verified"
    assert report.downgrade_executed is False
    assert report.baseline is None


def test_unverified_checkpoint_stops_before_the_migration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = _generated("Add a nullable text column called nickname to users", tmp_path)[1]
    checkpoints = iter(
        [
            _checkpoint(),
            SnapshotRecoveryReport(
                checkpoint_id="c" * 32,
                backup_status="failed",
                restore_status="not_attempted",
                error="test restore mismatch",
            ),
        ]
    )
    monkeypatch.setattr(
        "app.services.rollback_tester.prepare_sandbox_baseline",
        lambda _settings, **_kwargs: _snapshot(),
    )
    monkeypatch.setattr(
        "app.services.rollback_tester.read_baseline_evidence",
        lambda _settings, _snapshot_value: _evidence(),
    )
    monkeypatch.setattr(
        "app.services.rollback_tester.create_verified_checkpoint",
        lambda *_args, **_kwargs: next(checkpoints),
    )

    def fail_if_called(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("migration ran without a verified checkpoint")

    monkeypatch.setattr("app.services.rollback_tester.run_sandbox", fail_if_called)
    report = run_rollback_test(_settings(), artifact.migration_id, directory=tmp_path)
    assert report.status == "not_verified"
    assert report.upgrade is None
    assert report.snapshot_recovery is not None
    assert report.snapshot_recovery.backup_status == "failed"


def test_invalid_checkpoint_cannot_be_reported_as_restored() -> None:
    from app.services.sandbox_snapshots import restore_verified_checkpoint

    checkpoint = SnapshotRecoveryReport(
        checkpoint_id="not-a-checkpoint",
        backup_status="verified",
        restore_status="not_attempted",
    )
    report = restore_verified_checkpoint(_settings(), checkpoint)
    assert report.restore_status == "backup_unavailable"


def test_safety_report_reads_saved_rollback_evidence_without_running_rollback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import safety as safety_api

    request_text = "Add a nullable text column called nickname to users"
    snapshot, artifact = _generated(request_text, tmp_path)
    proposal = propose_migration(snapshot, request_text)
    monkeypatch.setattr(safety_api, "inspect_source", lambda *_args: snapshot)
    monkeypatch.setattr(
        safety_api,
        "create_proposal",
        lambda *_args, **_kwargs: proposal,
    )
    monkeypatch.setattr(safety_api, "load_verified_artifact", lambda *_args: artifact)
    monkeypatch.setattr(safety_api, "generate_migration", lambda *_args: artifact)
    monkeypatch.setattr(safety_api, "artifact_matches_plan", lambda *_args: True)
    monkeypatch.setattr(
        safety_api,
        "load_checkpoint_session",
        lambda *_args, **_kwargs: SimpleNamespace(
            validation_run=None,
            baseline_evidence=None,
            checkpoint=SnapshotRecoveryReport(backup_status="verified"),
            downgrade_report=None,
        ),
    )
    requested_sessions: list[str | None] = []

    def no_saved_evidence(*_args, **kwargs):
        requested_sessions.append(kwargs.get("session_id"))
        return None

    monkeypatch.setattr(safety_api, "load_rollback_evidence", no_saved_evidence)

    def fail_if_restore_runs(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Reading a safety report must not restore or mutate the sandbox")

    monkeypatch.setattr(safety_api, "restore_verified_checkpoint", fail_if_restore_runs)
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(settings=_settings(), llm_provider=None)
        )
    )
    report = safety_api.create_safety_report(
        "bookstore-demo",
        artifact.migration_id,
        SafetyReportRequest(
            request=request_text,
            confirm=True,
            snapshot_session_id="9" * 32,
        ),
        request,
    )
    assert report.rollback_status == "not_verified"
    assert report.eligible_for_review is False
    assert requested_sessions == ["9" * 32]


def test_rollback_route_requires_a_prior_validation_snapshot() -> None:
    from app.api import safety as safety_api
    from app.schemas.sandbox import SandboxRunRequest
    from fastapi import HTTPException

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=_settings())))
    with pytest.raises(HTTPException) as exc:
        safety_api.run_rollback(
            "bookstore-demo",
            "sp0123456789ab",
            SandboxRunRequest(confirm=True),
            request,
        )
    assert exc.value.status_code == 409
    assert exc.value.detail["error"] == "pre_migration_snapshot_session_required"


def test_rollback_evidence_store_detects_modified_payload(tmp_path: Path) -> None:
    from app.services.rollback_evidence_store import (
        RollbackEvidenceError,
        load_rollback_evidence,
        save_rollback_evidence,
    )

    report = RollbackReport(
        migration_id="sp0123456789ab",
        artifact_checksum="sha256:artifact",
        source_id="bookstore-demo",
        schema_fingerprint="fingerprint-1",
        sandbox_database="schemapilot_sandbox",
        sandbox_user="schemapilot_sandbox",
        postgres_version="16.0",
        started_at="2026-10-30T00:00:00+00:00",
        finished_at="2026-10-30T00:00:01+00:00",
        status="not_verified",
        downgrade_executed=False,
        data_checks=[],
        data_loss_limitations=[],
        snapshot_session_id="f" * 32,
    )
    save_rollback_evidence(report, directory=tmp_path)
    assert load_rollback_evidence(
        report.migration_id,
        report.artifact_checksum,
        session_id=report.snapshot_session_id,
        directory=tmp_path,
    ) == report

    evidence_path = tmp_path / f"{report.migration_id}-{report.snapshot_session_id}.json"
    evidence_path.write_text(
        evidence_path.read_text(encoding="utf-8").replace("not_verified", "failed"),
        encoding="utf-8",
    )
    with pytest.raises(RollbackEvidenceError, match="checksum"):
        load_rollback_evidence(
            report.migration_id,
            report.artifact_checksum,
            session_id=report.snapshot_session_id,
            directory=tmp_path,
        )


def test_pre_validation_checkpoint_session_is_artifact_bound_and_one_way(
    tmp_path: Path,
) -> None:
    from app.services.sandbox_checkpoint_store import (
        SandboxCheckpointSession,
        SandboxCheckpointSessionError,
        load_checkpoint_session,
        save_checkpoint_session,
        transition_checkpoint_session,
    )

    session = SandboxCheckpointSession(
        session_id="1" * 32,
        migration_id="sp0123456789ab",
        artifact_checksum="sha256:artifact",
        state="ready",
        checkpoint=_checkpoint(),
    )
    save_checkpoint_session(session, directory=tmp_path)
    loaded = load_checkpoint_session(
        session.session_id,
        session.migration_id,
        session.artifact_checksum,
        directory=tmp_path,
    )
    assert loaded.checkpoint.checkpoint_id == session.checkpoint.checkpoint_id
    running = transition_checkpoint_session(
        loaded,
        expected_state="ready",
        new_state="running",
        directory=tmp_path,
    )
    assert running.state == "running"
    with pytest.raises(SandboxCheckpointSessionError, match="expected state"):
        transition_checkpoint_session(
            running,
            expected_state="ready",
            new_state="running",
            directory=tmp_path,
        )
    with pytest.raises(SandboxCheckpointSessionError, match="previous sandbox validation"):
        save_checkpoint_session(
            session.model_copy(update={"session_id": "2" * 32}),
            directory=tmp_path,
        )
    assert (tmp_path / f"{session.session_id}.json").is_file()
    assert load_checkpoint_session(
        session.session_id,
        session.migration_id,
        session.artifact_checksum,
        directory=tmp_path,
    ).state == "running"
    with pytest.raises(SandboxCheckpointSessionError, match="verification"):
        load_checkpoint_session(
            session.session_id,
            session.migration_id,
            "sha256:wrong-artifact",
            directory=tmp_path,
        )


def test_checkpoint_session_rejects_invalid_state_transition(tmp_path: Path) -> None:
    from app.services.sandbox_checkpoint_store import (
        SandboxCheckpointSession,
        SandboxCheckpointSessionError,
        save_checkpoint_session,
        transition_checkpoint_session,
    )

    session = SandboxCheckpointSession(
        session_id="3" * 32,
        migration_id="sp0123456789ab",
        artifact_checksum="sha256:artifact",
        state="ready",
        checkpoint=_checkpoint(),
    )
    save_checkpoint_session(session, directory=tmp_path)

    with pytest.raises(SandboxCheckpointSessionError, match="restoration evidence"):
        transition_checkpoint_session(
            session,
            expected_state="ready",
            new_state="completed",
            directory=tmp_path,
        )


def test_checkpoint_session_transition_cannot_replace_checkpoint_identity(
    tmp_path: Path,
) -> None:
    from app.services.sandbox_checkpoint_store import (
        SandboxCheckpointSession,
        SandboxCheckpointSessionError,
        save_checkpoint_session,
        transition_checkpoint_session,
    )

    session = SandboxCheckpointSession(
        session_id="4" * 32,
        migration_id="sp0123456789ab",
        artifact_checksum="sha256:artifact",
        state="ready",
        checkpoint=_checkpoint(),
    )
    save_checkpoint_session(session, directory=tmp_path)
    replacement = session.checkpoint.model_copy(
        update={
            "checkpoint_id": "e" * 32,
            "baseline_schema_fingerprint": "different-schema",
            "baseline_data_fingerprint": "different-data",
        }
    )

    with pytest.raises(SandboxCheckpointSessionError, match="checkpoint identity"):
        transition_checkpoint_session(
            session,
            expected_state="ready",
            new_state="running",
            checkpoint=replacement,
            directory=tmp_path,
        )


def test_checkpoint_session_rejects_incomplete_verified_checkpoint_metadata(
    tmp_path: Path,
) -> None:
    from app.services.sandbox_checkpoint_store import (
        SandboxCheckpointSession,
        SandboxCheckpointSessionError,
        save_checkpoint_session,
    )

    incomplete_checkpoint = _checkpoint().model_copy(
        update={
            "baseline_data_fingerprint": None,
            "checkpoint_retained": False,
        }
    )
    session = SandboxCheckpointSession(
        session_id="5" * 32,
        migration_id="sp0123456789ab",
        artifact_checksum="sha256:artifact",
        state="ready",
        checkpoint=incomplete_checkpoint,
    )

    with pytest.raises(SandboxCheckpointSessionError, match="verified checkpoint evidence"):
        save_checkpoint_session(session, directory=tmp_path)

    assert not (tmp_path / f"{session.session_id}.json").exists()


def test_checkpoint_session_rejects_mismatched_checkpoint_verification_metadata(
    tmp_path: Path,
) -> None:
    from app.services.sandbox_checkpoint_store import (
        SandboxCheckpointSession,
        SandboxCheckpointSessionError,
        save_checkpoint_session,
    )

    mismatched_checkpoint = _checkpoint().model_copy(
        update={
            "restored_schema_fingerprint": "different-schema",
            "schema_match": False,
            "data_match": True,
        }
    )
    session = SandboxCheckpointSession(
        session_id="6" * 32,
        migration_id="sp0123456789ab",
        artifact_checksum="sha256:artifact",
        state="ready",
        checkpoint=mismatched_checkpoint,
    )

    with pytest.raises(SandboxCheckpointSessionError, match="verified checkpoint evidence"):
        save_checkpoint_session(session, directory=tmp_path)

    assert not (tmp_path / f"{session.session_id}.json").exists()


def test_compose_publishes_sandbox_database_on_loopback_only() -> None:
    compose_file = Path(__file__).resolve().parents[2] / "docker" / "compose.yaml"
    compose = compose_file.read_text(encoding="utf-8")
    sandbox_service = compose.split("  sandbox-db:", maxsplit=1)[1].split(
        "\n  volumes:", maxsplit=1
    )[0]
    assert '"127.0.0.1:5433:5432"' in sandbox_service
    assert '"5433:5432"' not in sandbox_service


def test_tampered_artifact_and_checksum_mismatch_are_not_verified(tmp_path: Path) -> None:
    artifact = _generated("Add a nullable text column called nickname to users", tmp_path)[1]
    json_path = tmp_path / f"{artifact.migration_id}.json"
    original = json_path.read_text(encoding="utf-8")
    json_path.write_text(original.replace("TEXT NULL", "TEXT NOT NULL"), encoding="utf-8")
    mismatched = run_rollback_test(_settings(), artifact.migration_id, directory=tmp_path)
    assert mismatched.status == "not_verified"
    assert mismatched.downgrade_executed is False
    assert "checksum" in (mismatched.error or "")
    json_path.write_text(original, encoding="utf-8")
    module_path = tmp_path / f"{artifact.migration_id}.py"
    edited = module_path.read_text(encoding="utf-8") + "\n# edited\n"
    module_path.write_text(edited, encoding="utf-8")
    tampered = run_rollback_test(_settings(), artifact.migration_id, directory=tmp_path)
    assert tampered.status == "not_verified"
    assert "Alembic" in (tampered.error or "")


def test_downgrade_allowlist_rejects_drop_table(tmp_path: Path) -> None:
    artifact = _generated("Add a nullable text column called nickname to users", tmp_path)[1]
    statements = parse_downgrade_sql(artifact.downgrade_sql)
    assert statements[0].kind == "drop_column"
    effect = artifact.operation_reversibility[0].downgrade_effect
    assert "does not recover its former values" in effect
    with pytest.raises(Exception, match="will not run"):
        parse_downgrade_sql('DROP TABLE "bookstore"."orders";')


def test_destructive_column_downgrade_recreates_only_nullable_shape(tmp_path: Path) -> None:
    _snapshot, artifact = _generated("Drop the status column from orders", tmp_path)
    statements = parse_downgrade_sql(artifact.downgrade_sql)
    assert statements[0].kind == "add_column"
    assert statements[0].table == "orders"
    assert statements[0].name == "status"
    assert artifact.sandbox_only is True
    assert artifact.operation_reversibility[0].data_loss_on_downgrade is True
    assert "nullability are not restored" in artifact.operation_reversibility[0].downgrade_effect


def test_report_keeps_review_separate_from_approval() -> None:
    proposal = MigrationProposal(
        source_id="bookstore-demo",
        schema_name="bookstore",
        schema_fingerprint="fingerprint-1",
        request="Add a nullable text column called nickname to users",
        status="proposed",
        summary="Add nullable text column nickname to users.",
        assumptions=[Assumption(id="assumption-1", text="The column is nullable.")],
        clarification_questions=[],
        operations=[
            PlanOperation(
                id="op-1",
                kind="add_column",
                summary="Add nullable text column nickname to users.",
                table="users",
                column="nickname",
                data_type="text",
                nullable=True,
            )
        ],
        validation_errors=[],
        destructive=False,
        requires_risk_assessment=False,
    )
    snapshot = _snapshot()
    assessment = assess_risk(snapshot, proposal)
    artifact = MigrationArtifact(
        migration_id="sp0123456789ab",
        source_id="bookstore-demo",
        schema_name="bookstore",
        schema_fingerprint="fingerprint-1",
        summary=proposal.summary,
        status="generated",
        applied=False,
        operation_ids=["op-1"],
        sql_preview='ALTER TABLE "bookstore"."users" ADD COLUMN "nickname" TEXT NULL;',
        downgrade_sql='ALTER TABLE "bookstore"."users" DROP COLUMN "nickname";',
        alembic_source="def upgrade():\n    pass\n\ndef downgrade():\n    pass\n",
        reversibility="partially_reversible",
        operation_reversibility=[
            OperationReversibility(
                operation_id="op-1",
                kind="add_column",
                reversibility="partially_reversible",
                upgrade_effect="Add column.",
                downgrade_effect="Recreating a dropped column does not restore its former values.",
                data_loss_on_downgrade=True,
            )
        ],
        checksum="sha256:abc",
        location="",
    )
    rollback = RollbackReport(
        migration_id=artifact.migration_id,
        artifact_checksum=artifact.checksum,
        source_id=artifact.source_id,
        schema_fingerprint=artifact.schema_fingerprint,
        sandbox_database="schemapilot_sandbox",
        sandbox_user="schemapilot_sandbox",
        postgres_version="16.0",
        started_at="2026-10-15T00:00:00+00:00",
        finished_at="2026-10-15T00:00:02+00:00",
        status="partial_restoration",
        upgrade=_upgrade(),
        baseline=_evidence(),
        downgrade_executed=True,
        schema_matches_baseline=True,
        data_checks=[],
        snapshot_recovery=SnapshotRecoveryReport(
            checkpoint_id="a" * 32,
            backup_status="verified",
            restore_status="restore_verified",
            baseline_schema_fingerprint="fingerprint-1",
            restored_schema_fingerprint="fingerprint-1",
            baseline_data_fingerprint="data-fingerprint",
            restored_data_fingerprint="data-fingerprint",
            schema_match=True,
            data_match=True,
            checkpoint_retained=True,
        ),
        preexisting_sandbox_recovery=SnapshotRecoveryReport(
            checkpoint_id="d" * 32,
            backup_status="verified",
            restore_status="restore_verified",
            baseline_schema_fingerprint="fingerprint-1",
            restored_schema_fingerprint="fingerprint-1",
            baseline_data_fingerprint="preexisting-data-fingerprint",
            restored_data_fingerprint="preexisting-data-fingerprint",
            schema_match=True,
            data_match=True,
            checkpoint_retained=True,
        ),
        data_loss_limitations=[
            "Recreating a dropped column does not restore its former values."
        ],
        error=None,
    )
    rollback.upgrade.migration_id = artifact.migration_id  # type: ignore[union-attr]
    report = build_safety_report(
        proposal,
        assessment,
        artifact,
        rollback,
        artifact_matches=True,
    )
    assert isinstance(report, SafetyReport)
    assert report.approved is False
    assert report.applied is False
    assert report.fully_reversible is False
    assert report.eligible_for_review is True
    assert report.rollback_status == "partial_restoration"
    assert report.request == proposal.request
    assert report.risk_findings
    incomplete = build_safety_report(
        proposal,
        assessment,
        artifact,
        None,
        artifact_matches=True,
    )
    assert incomplete.eligible_for_review is False
    assert incomplete.rollback_status == "not_verified"
    assert "sandbox upgrade" in incomplete.missing_evidence


def test_persisted_validation_evidence_is_visible_but_snapshot_alone_is_ineligible(
    tmp_path: Path,
) -> None:
    request_text = "Add a nullable text column called nickname to users"
    snapshot, artifact = _generated(request_text, tmp_path)
    proposal = propose_migration(snapshot, request_text)
    assessment = assess_risk(snapshot, proposal)
    session_id = "9" * 32
    validation = _upgrade().model_copy(
        update={
            "migration_id": artifact.migration_id,
            "source_id": artifact.source_id,
            "schema_fingerprint": artifact.schema_fingerprint,
            "artifact_checksum": artifact.checksum,
            "snapshot_session_id": session_id,
            "pre_migration_snapshot_verified": True,
        }
    )
    baseline = BaselineEvidence(
        schema_fingerprint=artifact.schema_fingerprint,
        tables=["users"],
        row_counts={"users": 3},
        emails=["not-returned@example.test"],
    )
    checkpoint = SnapshotRecoveryReport(
        checkpoint_id="a" * 32,
        backup_status="verified",
        restore_status="restore_verified",
        baseline_schema_fingerprint=artifact.schema_fingerprint,
        restored_schema_fingerprint=artifact.schema_fingerprint,
        baseline_data_fingerprint="data-before",
        restored_data_fingerprint="data-before",
        schema_match=True,
        data_match=True,
        checkpoint_retained=True,
    )

    report = build_safety_report(
        proposal,
        assessment,
        artifact,
        None,
        artifact_matches=True,
        sandbox_run=validation,
        baseline_evidence=baseline,
        snapshot_recovery=checkpoint,
        snapshot_session_id=session_id,
    )

    assert report.sandbox is not None
    assert report.sandbox.result == "passed"
    assert report.baseline_evidence is not None
    assert report.baseline_evidence.schema_fingerprint == artifact.schema_fingerprint
    assert "emails" not in report.baseline_evidence.model_dump()
    assert report.snapshot_recovery is checkpoint
    assert "migration downgrade" in report.missing_evidence
    assert report.eligible_for_review is False


def test_failed_validation_evidence_is_never_reported_as_success(tmp_path: Path) -> None:
    request_text = "Add a nullable text column called nickname to users"
    snapshot, artifact = _generated(request_text, tmp_path)
    proposal = propose_migration(snapshot, request_text)
    assessment = assess_risk(snapshot, proposal)
    failed_run = _upgrade().model_copy(
        update={
            "migration_id": artifact.migration_id,
            "source_id": artifact.source_id,
            "schema_fingerprint": artifact.schema_fingerprint,
            "artifact_checksum": artifact.checksum,
            "result": "failed",
        }
    )
    baseline = BaselineEvidence(
        schema_fingerprint=artifact.schema_fingerprint,
        tables=["users"],
        row_counts={"users": 3},
        emails=[],
    )

    report = build_safety_report(
        proposal,
        assessment,
        artifact,
        None,
        artifact_matches=True,
        sandbox_run=failed_run,
        baseline_evidence=baseline,
    )

    assert report.sandbox is not None
    assert report.sandbox.result == "failed"
    assert report.eligible_for_review is False
    assert any("validation evidence" in item for item in report.blocking_reasons)


def test_snapshot_restore_status_does_not_stand_in_for_downgrade(tmp_path: Path) -> None:
    request_text = "Add a nullable text column called nickname to users"
    snapshot, artifact = _generated(request_text, tmp_path)
    proposal = propose_migration(snapshot, request_text)
    assessment = assess_risk(snapshot, proposal)
    validation = _upgrade().model_copy(
        update={
            "migration_id": artifact.migration_id,
            "schema_fingerprint": artifact.schema_fingerprint,
            "artifact_checksum": artifact.checksum,
        }
    )
    snapshot_only = RollbackReport(
        migration_id=artifact.migration_id,
        artifact_checksum=artifact.checksum,
        source_id=artifact.source_id,
        schema_fingerprint=artifact.schema_fingerprint,
        sandbox_database="schemapilot_sandbox",
        sandbox_user="schemapilot_sandbox",
        postgres_version="16.0",
        started_at="2026-11-03T00:00:00+00:00",
        finished_at="2026-11-03T00:00:01+00:00",
        status="exact_restoration",
        upgrade=validation,
        baseline=BaselineEvidence(
            schema_fingerprint=artifact.schema_fingerprint,
            tables=["users"],
            row_counts={"users": 1},
            emails=[],
        ),
        downgrade_executed=False,
        schema_matches_baseline=True,
        data_checks=[],
        data_loss_limitations=[],
        snapshot_recovery=SnapshotRecoveryReport(
            checkpoint_id="a" * 32,
            backup_status="verified",
            restore_status="restore_verified",
            baseline_schema_fingerprint=artifact.schema_fingerprint,
            restored_schema_fingerprint=artifact.schema_fingerprint,
            baseline_data_fingerprint="data-before",
            restored_data_fingerprint="data-before",
            schema_match=True,
            data_match=True,
            checkpoint_retained=True,
        ),
    )

    report = build_safety_report(
        proposal,
        assessment,
        artifact,
        snapshot_only,
        artifact_matches=True,
    )

    assert report.snapshot_recovery is not None
    assert report.snapshot_recovery.restore_status == "restore_verified"
    assert report.rollback_status == "not_verified"
    assert report.downgrade_executed is False
    assert "migration downgrade" in report.missing_evidence
    assert report.eligible_for_review is False


def test_sandbox_only_destructive_report_is_reviewable_but_never_approved(
    tmp_path: Path,
) -> None:
    snapshot, artifact = _generated("Drop the status column from orders", tmp_path)
    proposal = propose_migration(snapshot, "Drop the status column from orders")
    assessment = assess_risk(snapshot, proposal)
    rollback = RollbackReport(
        migration_id=artifact.migration_id,
        artifact_checksum=artifact.checksum,
        source_id=artifact.source_id,
        schema_fingerprint=artifact.schema_fingerprint,
        sandbox_database="schemapilot_sandbox",
        sandbox_user="schemapilot_sandbox",
        postgres_version="16.0",
        started_at="2026-10-30T00:00:00+00:00",
        finished_at="2026-10-30T00:00:02+00:00",
        status="partial_restoration",
        upgrade=_upgrade(),
        baseline=_evidence(),
        downgrade_executed=True,
        schema_matches_baseline=False,
        data_checks=[],
        snapshot_recovery=SnapshotRecoveryReport(
            checkpoint_id="b" * 32,
            backup_status="verified",
            restore_status="restore_verified",
            baseline_schema_fingerprint=artifact.schema_fingerprint,
            restored_schema_fingerprint=artifact.schema_fingerprint,
            baseline_data_fingerprint="data-fingerprint",
            restored_data_fingerprint="data-fingerprint",
            schema_match=True,
            data_match=True,
            checkpoint_retained=True,
        ),
        preexisting_sandbox_recovery=SnapshotRecoveryReport(
            checkpoint_id="e" * 32,
            backup_status="verified",
            restore_status="restore_verified",
            baseline_schema_fingerprint=artifact.schema_fingerprint,
            restored_schema_fingerprint=artifact.schema_fingerprint,
            baseline_data_fingerprint="preexisting-data-fingerprint",
            restored_data_fingerprint="preexisting-data-fingerprint",
            schema_match=True,
            data_match=True,
            checkpoint_retained=True,
        ),
        data_loss_limitations=["Recreating a dropped column does not restore its former values."],
        error=None,
    )
    rollback.upgrade.migration_id = artifact.migration_id  # type: ignore[union-attr]
    rollback.upgrade.schema_fingerprint = artifact.schema_fingerprint  # type: ignore[union-attr]
    rollback.upgrade.artifact_checksum = artifact.checksum  # type: ignore[union-attr]

    report = build_safety_report(
        proposal,
        assessment,
        artifact,
        rollback,
        artifact_matches=True,
    )

    assert assessment.policy_blocked is True
    assert artifact.sandbox_only is True
    assert report.eligible_for_review is True
    assert report.approved is False
    assert report.applied is False
    assert report.rollback_status == "partial_restoration"
    assert not report.blocking_reasons
    assert any(finding.disposition == "policy_blocked" for finding in report.risk_findings)

    restore_failure = rollback.model_copy(
        update={
            "snapshot_recovery": rollback.snapshot_recovery.model_copy(
                update={"restore_status": "verification_incomplete", "data_match": False}
            )
        }
    )
    blocked_report = build_safety_report(
        proposal,
        assessment,
        artifact,
        restore_failure,
        artifact_matches=True,
    )
    assert blocked_report.eligible_for_review is False
    assert any("restoration was not verified" in item for item in blocked_report.blocking_reasons)


def test_rollback_route_does_not_open_a_database(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_if_called(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("route opened a database")

    monkeypatch.setattr(session_module, "create_engine", fail_if_called)
    monkeypatch.setattr(session_module, "create_demo_engine", fail_if_called)
    monkeypatch.setattr(session_module, "create_bookstore_source_engine", fail_if_called)
    monkeypatch.setattr(session_module, "create_sandbox_engine", fail_if_called)
    client = TestClient(create_app(_settings(allow_sandbox_execution=False)))
    unconfirmed = client.post(
        "/api/v1/sources/bookstore-demo/artifacts/sp0123456789ab/rollback",
        json={"confirm": False},
    )
    extra = client.post(
        "/api/v1/sources/bookstore-demo/artifacts/sp0123456789ab/report",
        json={"request": "Add a column", "confirm": True, "database_url": "postgresql://secret@db/prod"},
    )
    assert unconfirmed.status_code == 409
    assert extra.status_code == 422
    assert "secret" not in extra.text


def test_rollback_modules_do_not_use_source_engines() -> None:
    root = Path(__file__).resolve().parents[1] / "app" / "services"
    for name in ("rollback_tester.py", "report_service.py"):
        source = (root / name).read_text(encoding="utf-8")
        assert "create_demo_engine" not in source
        assert "create_bookstore_source_engine" not in source
        assert ".comment" not in source
    assert hashlib.sha256(b"stable").hexdigest()


def test_unquoted_downgrade_sql_is_rejected() -> None:
    with pytest.raises(DowngradeRejected):
        parse_downgrade_sql("ALTER TABLE bookstore.users DROP COLUMN nickname;")
