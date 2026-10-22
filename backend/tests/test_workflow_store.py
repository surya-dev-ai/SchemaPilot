"""Workflow persistence unit tests. These use SQLite and do not open PostgreSQL."""

from pathlib import Path

import pytest
from app.core.config import Settings
from app.db import session as session_module
from app.main import create_app
from app.schemas.artifacts import MigrationArtifact, OperationReversibility
from app.schemas.planning import Assumption, MigrationProposal, PlanOperation
from app.schemas.report import SafetyReport
from app.schemas.rollback import BaselineEvidence, RollbackReport
from app.schemas.sandbox import SandboxRun
from app.schemas.workflow import ApprovalCreateRequest
from app.services.report_service import build_safety_report
from app.services.risk_engine import assess_risk
from app.services.workflow_store import (
    WorkflowStoreError,
    WorkflowStoreUnavailable,
    create_tables,
    evidence_fingerprint,
    get_workflow,
    list_workflows,
    persist_workflow,
    record_approval,
    report_checksum,
)
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError


def _settings(*, authentication_available: bool = False) -> Settings:
    return Settings.model_construct(
        app_name="SchemaPilot",
        api_v1_prefix="/api/v1",
        cors_origins="http://localhost:5173",
        app_database_url="postgresql+psycopg://schemapilot:local@127.0.0.1:5432/schemapilot",
        sandbox_database_url=(
            "postgresql+psycopg://schemapilot_sandbox:local@127.0.0.1:5433/schemapilot_sandbox"
        ),
        demo_database_url=(
            "postgresql+psycopg://schemapilot_demo:local@127.0.0.1:5434/schemapilot_bookstore"
        ),
        target_database_url=None,
        target_execution_enabled=False,
        allow_app_migrations=False,
        authentication_available=authentication_available,
    )


def _principal():
    from app.services.auth import AuthenticatedPrincipal

    return AuthenticatedPrincipal(identity="reviewer@example.test", scheme="test")


def _engine(tmp_path: Path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'meta.db'}")
    create_tables(engine)
    return engine


def _proposal() -> MigrationProposal:
    return MigrationProposal(
        source_id="bookstore-demo",
        schema_name="bookstore",
        schema_fingerprint="fingerprint-1",
        request="Add a nullable text column called nickname to users",
        status="proposed",
        summary="Add nullable text column nickname to users.",
        assumptions=[Assumption(id="assumption-1", text="Column is nullable.")],
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


def _artifact() -> MigrationArtifact:
    return MigrationArtifact(
        migration_id="sp0123456789ab",
        source_id="bookstore-demo",
        schema_name="bookstore",
        schema_fingerprint="fingerprint-1",
        summary="Add nullable text column nickname to users.",
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
        checksum="sha256:artifact",
        location="artifacts/generated/sp0123456789ab.py",
    )


def _upgrade() -> SandboxRun:
    return SandboxRun(
        migration_id="sp0123456789ab",
        source_id="bookstore-demo",
        schema_fingerprint="fingerprint-1",
        artifact_checksum="sha256:artifact",
        sandbox_database="schemapilot_sandbox",
        sandbox_user="schemapilot_sandbox",
        postgres_version="16.0",
        started_at="2026-10-15T00:00:00+00:00",
        finished_at="2026-10-15T00:00:01+00:00",
        result="passed",
        upgrade_applied=True,
        restored=False,
        cleaned_up=False,
        checks=[],
        observed_tables=["users"],
        error=None,
    )


def _rollback(status: str = "partial_restoration") -> RollbackReport:
    return RollbackReport(
        migration_id="sp0123456789ab",
        artifact_checksum="sha256:artifact",
        source_id="bookstore-demo",
        schema_fingerprint="fingerprint-1",
        sandbox_database="schemapilot_sandbox",
        sandbox_user="schemapilot_sandbox",
        postgres_version="16.0",
        started_at="2026-10-15T00:00:00+00:00",
        finished_at="2026-10-15T00:00:02+00:00",
        status=status,  # type: ignore[arg-type]
        upgrade=_upgrade(),
        baseline=BaselineEvidence(
            schema_fingerprint="fingerprint-1",
            tables=["users"],
            row_counts={"users": 3},
            emails=["mira@example.test"],
        ),
        downgrade_executed=True,
        schema_matches_baseline=True,
        data_checks=[],
        data_loss_limitations=[
            "Recreating a dropped column does not restore its former values."
        ],
        error=None,
    )


def _eligible_bundle():
    from app.schemas.domain import ColumnSnapshot, SchemaSnapshot, TableSnapshot

    snapshot = SchemaSnapshot(
        source_id="bookstore-demo",
        database_name="schemapilot_bookstore",
        schema_name="bookstore",
        fingerprint="fingerprint-1",
        tables=[
            TableSnapshot(
                id="bookstore.users",
                schema_name="bookstore",
                name="users",
                columns=[
                    ColumnSnapshot(
                        id="bookstore.users.id",
                        name="id",
                        ordinal_position=1,
                        data_type="text",
                        udt_name="text",
                        nullable=False,
                        identity="none",
                        generated="never",
                    )
                ],
                constraints=[],
                indexes=[],
            )
        ],
        dependencies=[],
    )
    proposal = _proposal()
    assessment = assess_risk(snapshot, proposal)
    report = build_safety_report(
        proposal,
        assessment,
        _artifact(),
        _rollback(),
        artifact_matches=True,
    )
    return proposal, assessment, report, _rollback()


def test_persist_and_list_workflows(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    proposal, assessment, report, rollback = _eligible_bundle()
    detail = persist_workflow(
        _settings(),
        proposal=proposal,
        assessment=assessment,
        report=report,
        rollback=rollback,
        engine=engine,
    )
    assert detail.migration_id == "sp0123456789ab"
    assert detail.artifact_applied is False
    assert detail.report.approved is False
    assert detail.report.applied is False
    assert detail.eligible_for_review is True
    assert detail.report_checksum == report_checksum(report)
    listed = list_workflows(_settings(), engine=engine)
    assert len(listed.workflows) == 1
    assert listed.workflows[0].id == detail.id


def test_duplicate_artifact_binding_is_rejected(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    proposal, assessment, report, rollback = _eligible_bundle()
    persist_workflow(
        _settings(),
        proposal=proposal,
        assessment=assessment,
        report=report,
        rollback=rollback,
        engine=engine,
    )
    with pytest.raises(WorkflowStoreError) as exc:
        persist_workflow(
            _settings(),
            proposal=proposal,
            assessment=assessment,
            report=report,
            rollback=rollback,
            engine=engine,
        )
    assert exc.value.code == "duplicate_workflow_artifact"


def test_stale_evidence_blocks_approval(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    proposal, assessment, report, rollback = _eligible_bundle()
    detail = persist_workflow(
        _settings(),
        proposal=proposal,
        assessment=assessment,
        report=report,
        rollback=rollback,
        engine=engine,
    )
    stale = get_workflow(
        _settings(),
        detail.id,
        current_fingerprint="sha256:changed",
        engine=engine,
    )
    assert stale.report_stale is True
    assert stale.eligible_for_review is False
    with pytest.raises(WorkflowStoreError) as exc:
        record_approval(
            _settings(authentication_available=True),
            detail.id,
            ApprovalCreateRequest(target_identity="staging-target", confirm=True),
            principal=_principal(),
            engine=engine,
        )
    assert exc.value.code == "stale_safety_report"


def test_approval_requires_authentication_and_rejects_body_identity(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    proposal, assessment, report, rollback = _eligible_bundle()
    detail = persist_workflow(
        _settings(),
        proposal=proposal,
        assessment=assessment,
        report=report,
        rollback=rollback,
        engine=engine,
    )
    with pytest.raises(WorkflowStoreError) as unauth:
        record_approval(
            _settings(),
            detail.id,
            ApprovalCreateRequest(target_identity="staging-target", confirm=True),
            expected_artifact_checksum=detail.artifact_checksum,
            engine=engine,
        )
    assert unauth.value.code == "authentication_unavailable"
    loaded = get_workflow(_settings(), detail.id, engine=engine)
    assert loaded.state != "approval_recorded"
    assert loaded.approvals == []
    assert loaded.report.applied is False


def test_approval_requires_matching_artifact_report_and_valid_target(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    proposal, assessment, report, rollback = _eligible_bundle()
    detail = persist_workflow(
        _settings(),
        proposal=proposal,
        assessment=assessment,
        report=report,
        rollback=rollback,
        engine=engine,
    )
    auth_settings = _settings(authentication_available=True)
    principal = _principal()
    with pytest.raises(WorkflowStoreError) as wrong_checksum:
        record_approval(
            auth_settings,
            detail.id,
            ApprovalCreateRequest(target_identity="staging-target", confirm=True),
            expected_artifact_checksum="sha256:other",
            principal=principal,
            engine=engine,
        )
    assert wrong_checksum.value.code == "artifact_checksum_mismatch"
    with pytest.raises(WorkflowStoreError) as wrong_report:
        record_approval(
            auth_settings,
            detail.id,
            ApprovalCreateRequest(target_identity="staging-target", confirm=True),
            expected_artifact_checksum=detail.artifact_checksum,
            expected_report_checksum="sha256:other-report",
            principal=principal,
            engine=engine,
        )
    assert wrong_report.value.code == "report_checksum_mismatch"
    with pytest.raises(WorkflowStoreError) as reserved:
        record_approval(
            auth_settings,
            detail.id,
            ApprovalCreateRequest(target_identity="schemapilot_sandbox", confirm=True),
            principal=principal,
            engine=engine,
        )
    assert reserved.value.code == "invalid_target_identity"
    approval = record_approval(
        auth_settings,
        detail.id,
        ApprovalCreateRequest(target_identity="staging-target", confirm=True),
        expected_artifact_checksum=detail.artifact_checksum,
        expected_report_checksum=detail.report_checksum,
        principal=principal,
        engine=engine,
    )
    assert approval.decision == "recorded"
    assert approval.authentication_available is True
    assert approval.approver_identity == "reviewer@example.test"
    loaded = get_workflow(_settings(), detail.id, engine=engine)
    assert loaded.state == "approval_recorded"
    assert loaded.report.applied is False


def test_incomplete_evidence_cannot_be_approved(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    proposal, assessment, report, rollback = _eligible_bundle()
    incomplete = build_safety_report(
        proposal,
        assessment,
        _artifact(),
        None,
        artifact_matches=True,
    )
    assert incomplete.eligible_for_review is False
    detail = persist_workflow(
        _settings(),
        proposal=proposal,
        assessment=assessment,
        report=incomplete,
        rollback=None,
        engine=engine,
    )
    with pytest.raises(WorkflowStoreError) as exc:
        record_approval(
            _settings(authentication_available=True),
            detail.id,
            ApprovalCreateRequest(target_identity="staging-target", confirm=True),
            principal=_principal(),
            engine=engine,
        )
    assert exc.value.code == "not_eligible_for_review"


def test_not_verified_rollback_is_not_upgraded(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    proposal, assessment, _, _ = _eligible_bundle()
    report = build_safety_report(
        proposal,
        assessment,
        _artifact(),
        _rollback("not_verified"),
        artifact_matches=True,
    )
    assert report.rollback_status == "not_verified"
    assert report.eligible_for_review is False
    detail = persist_workflow(
        _settings(),
        proposal=proposal,
        assessment=assessment,
        report=report,
        rollback=_rollback("not_verified"),
        engine=engine,
    )
    assert detail.state == "blocked"
    assert detail.rollback_status == "not_verified"


def test_app_database_unavailability_is_reported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Engine:
        def connect(self):
            raise OperationalError("SELECT 1", {}, Exception("postgresql://secret@db/prod"))

        def dispose(self) -> None:
            return None

    monkeypatch.setattr(session_module, "create_engine", lambda *_a, **_k: _Engine())
    proposal, assessment, report, rollback = _eligible_bundle()
    with pytest.raises(WorkflowStoreUnavailable):
        persist_workflow(
            _settings(),
            proposal=proposal,
            assessment=assessment,
            report=report,
            rollback=rollback,
        )


def test_workflow_store_does_not_use_source_or_sandbox_engines() -> None:
    source = Path("app/services/workflow_store.py").read_text(encoding="utf-8")
    assert "create_demo_engine" not in source
    assert "create_bookstore_source_engine" not in source
    assert "create_sandbox_engine" not in source
    assert "alembic/versions" not in source


def test_workflow_routes_require_app_database(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_if_called(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("workflow route opened a database")

    monkeypatch.setattr(session_module, "create_engine", fail_if_called)
    unset = Settings.model_construct(
        app_name="SchemaPilot",
        api_v1_prefix="/api/v1",
        cors_origins="http://localhost:5173",
        app_database_url=None,
        sandbox_database_url=None,
        demo_database_url=None,
        target_database_url=None,
        target_execution_enabled=False,
        allow_app_migrations=False,
    )
    client = TestClient(create_app(unset))
    listed = client.get("/api/v1/workflows")
    assert listed.status_code == 409
    assert listed.json()["detail"]["error"] == "app_database_not_configured"
    assert "postgresql" not in listed.text
    assert "secret" not in listed.text


def test_evidence_fingerprint_changes_with_rollback_status() -> None:
    proposal, assessment, report, rollback = _eligible_bundle()
    first = evidence_fingerprint(
        artifact_checksum=report.artifact_checksum,
        schema_fingerprint=report.schema_fingerprint,
        assessment=assessment,
        sandbox=report.sandbox,
        rollback=rollback,
    )
    second = evidence_fingerprint(
        artifact_checksum=report.artifact_checksum,
        schema_fingerprint=report.schema_fingerprint,
        assessment=assessment,
        sandbox=report.sandbox,
        rollback=_rollback("failed"),
    )
    assert first != second
    assert isinstance(report, SafetyReport)
