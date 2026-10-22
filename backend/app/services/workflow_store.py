"""Persist workflow evidence in the application metadata database.

This module uses only the application engine. It does not open the source,
sandbox, or target databases, and it does not approve a target apply.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, UnsafeDatabaseConfigurationError, resolve_app_database_url
from app.db.models import ApprovalRecord, AuditEvent, Base, MigrationWorkflow
from app.db.session import create_app_engine
from app.schemas.planning import MigrationProposal
from app.schemas.report import SafetyReport
from app.schemas.risk import RiskAssessment
from app.schemas.rollback import RollbackReport
from app.schemas.sandbox import SandboxRun
from app.schemas.workflow import (
    ApprovalCreateRequest,
    ApprovalSummary,
    AuditEventSummary,
    WorkflowDetail,
    WorkflowListResponse,
    WorkflowSummary,
)
from app.services.auth import (
    AuthenticatedPrincipal,
    AuthenticationError,
    require_authenticated_principal,
)

_RESERVED_TARGETS = frozenset(
    {
        "bookstore-demo",
        "schemapilot_bookstore",
        "schemapilot_sandbox",
        "schemapilot",
        "sandbox",
        "source",
    }
)


class WorkflowStoreError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class WorkflowStoreUnavailable(WorkflowStoreError):
    def __init__(self) -> None:
        super().__init__("app_database_unavailable", "Application database is unavailable.")


def report_checksum(report: SafetyReport) -> str:
    payload = report.model_dump(mode="json")
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def evidence_fingerprint(
    *,
    artifact_checksum: str,
    schema_fingerprint: str,
    assessment: RiskAssessment,
    sandbox: SandboxRun | None,
    rollback: RollbackReport | None,
) -> str:
    payload = {
        "artifact_checksum": artifact_checksum,
        "schema_fingerprint": schema_fingerprint,
        "risk": assessment.model_dump(mode="json"),
        "sandbox": None if sandbox is None else sandbox.model_dump(mode="json"),
        "rollback": None if rollback is None else rollback.model_dump(mode="json"),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def create_metadata_engine(settings: Settings) -> Engine:
    """Create the application metadata engine after isolation checks."""

    resolve_app_database_url(settings)
    return create_app_engine(settings)


def create_tables(engine: Engine) -> None:
    """Create metadata tables. Used by tests; production uses guarded Alembic."""

    Base.metadata.create_all(engine)


@contextmanager
def metadata_session(settings: Settings, engine: Engine | None = None) -> Iterator[Session]:
    active = engine
    owns_engine = active is None
    if active is None:
        try:
            active = create_metadata_engine(settings)
        except UnsafeDatabaseConfigurationError as exc:
            raise WorkflowStoreError("app_database_not_configured", str(exc)) from exc
        except OperationalError as exc:
            raise WorkflowStoreUnavailable from exc
    factory = sessionmaker(bind=active, autoflush=False, autocommit=False)
    session = factory()
    try:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
    finally:
        session.close()
        if owns_engine and active is not None:
            active.dispose()


def persist_workflow(
    settings: Settings,
    *,
    proposal: MigrationProposal,
    assessment: RiskAssessment,
    report: SafetyReport,
    rollback: RollbackReport | None,
    engine: Engine | None = None,
) -> WorkflowDetail:
    """Store one safety-report bundle. Duplicate artifact bindings are rejected."""

    checksum = report_checksum(report)
    fingerprint = evidence_fingerprint(
        artifact_checksum=report.artifact_checksum,
        schema_fingerprint=report.schema_fingerprint,
        assessment=assessment,
        sandbox=report.sandbox,
        rollback=rollback,
    )
    state = "report_ready" if report.eligible_for_review else "blocked"
    workflow_id = str(uuid.uuid4())
    now = _now()
    row = MigrationWorkflow(
        id=workflow_id,
        source_id=report.source_id,
        request_text=report.request,
        intent_summary=report.interpreted_intent,
        schema_fingerprint=report.schema_fingerprint,
        migration_id=report.migration_id,
        artifact_checksum=report.artifact_checksum,
        artifact_status=report.artifact_status,
        artifact_applied=False,
        state=state,
        plan_json=proposal.model_dump_json(),
        risk_json=assessment.model_dump_json(),
        sandbox_json=None if report.sandbox is None else report.sandbox.model_dump_json(),
        rollback_json=None if rollback is None else rollback.model_dump_json(),
        report_json=report.model_dump_json(),
        report_checksum=checksum,
        evidence_fingerprint=fingerprint,
        eligible_for_review=report.eligible_for_review,
        fully_reversible=report.fully_reversible,
        rollback_status=report.rollback_status,
        report_stale=False,
        created_at=now,
        updated_at=now,
    )
    try:
        with metadata_session(settings, engine) as session:
            session.add(row)
            session.add(
                _audit(
                    workflow_id,
                    "workflow_persisted",
                    {
                        "migration_id": report.migration_id,
                        "artifact_checksum": report.artifact_checksum,
                        "report_checksum": checksum,
                        "eligible_for_review": report.eligible_for_review,
                        "state": state,
                        "interpretation_path": proposal.interpretation_path,
                        "provider_status": proposal.provider_status,
                        "schema_fingerprint": report.schema_fingerprint,
                    },
                )
            )
            session.flush()
            return _detail(session, row)
    except IntegrityError as exc:
        raise WorkflowStoreError(
            "duplicate_workflow_artifact",
            "A workflow already exists for this migration id and artifact checksum.",
        ) from exc
    except OperationalError as exc:
        raise WorkflowStoreUnavailable from exc


def list_workflows(settings: Settings, engine: Engine | None = None) -> WorkflowListResponse:
    try:
        with metadata_session(settings, engine) as session:
            rows = session.scalars(
                select(MigrationWorkflow).order_by(MigrationWorkflow.created_at.desc())
            ).all()
            return WorkflowListResponse(workflows=[_summary(row) for row in rows])
    except OperationalError as exc:
        raise WorkflowStoreUnavailable from exc


def get_workflow(
    settings: Settings,
    workflow_id: str,
    *,
    current_fingerprint: str | None = None,
    engine: Engine | None = None,
) -> WorkflowDetail:
    try:
        with metadata_session(settings, engine) as session:
            row = session.get(MigrationWorkflow, workflow_id)
            if row is None:
                raise WorkflowStoreError("workflow_not_found", "The workflow was not found.")
            if current_fingerprint is not None and current_fingerprint != row.evidence_fingerprint:
                row.report_stale = True
                row.eligible_for_review = False
                if row.state == "report_ready":
                    row.state = "blocked"
                row.updated_at = _now()
                session.add(
                    _audit(
                        row.id,
                        "report_marked_stale",
                        {
                            "stored_evidence_fingerprint": row.evidence_fingerprint,
                            "current_evidence_fingerprint": current_fingerprint,
                        },
                    )
                )
                session.flush()
            return _detail(session, row)
    except OperationalError as exc:
        raise WorkflowStoreUnavailable from exc


def record_approval(
    settings: Settings,
    workflow_id: str,
    body: ApprovalCreateRequest,
    *,
    expected_artifact_checksum: str | None = None,
    expected_report_checksum: str | None = None,
    current_fingerprint: str | None = None,
    principal: AuthenticatedPrincipal | None = None,
    engine: Engine | None = None,
) -> ApprovalSummary:
    """Record an approval binding only for an authenticated principal.

    This is not target execution. Request-body usernames are ignored; the
    principal must come from server-side authentication.
    """

    if body.confirm is not True:
        raise WorkflowStoreError("approval_not_confirmed", "Approval requires confirm=true.")
    try:
        authenticated = require_authenticated_principal(settings, principal)
    except AuthenticationError as exc:
        raise WorkflowStoreError(exc.code, exc.message) from exc
    target = body.target_identity
    if target.lower() in _RESERVED_TARGETS:
        raise WorkflowStoreError(
            "invalid_target_identity",
            "The target identity must not name the source, sandbox, or application database.",
        )
    pending_error: WorkflowStoreError | None = None
    summary: ApprovalSummary | None = None
    try:
        with metadata_session(settings, engine) as session:
            row = session.get(MigrationWorkflow, workflow_id)
            if row is None:
                pending_error = WorkflowStoreError(
                    "workflow_not_found",
                    "The workflow was not found.",
                )
            elif (
                current_fingerprint is not None
                and current_fingerprint != row.evidence_fingerprint
            ):
                row.report_stale = True
                row.eligible_for_review = False
                row.state = "blocked"
                row.updated_at = _now()
                session.add(
                    _audit(row.id, "approval_rejected_stale", {"target_identity": target})
                )
                pending_error = WorkflowStoreError(
                    "stale_safety_report",
                    "The safety report is stale relative to the current evidence.",
                )
            elif row.report_stale:
                session.add(
                    _audit(row.id, "approval_rejected_stale", {"target_identity": target})
                )
                pending_error = WorkflowStoreError(
                    "stale_safety_report",
                    "The safety report is marked stale and cannot be approved.",
                )
            elif expected_artifact_checksum and expected_artifact_checksum != row.artifact_checksum:
                session.add(
                    _audit(
                        row.id,
                        "approval_rejected_checksum",
                        {
                            "expected_artifact_checksum": expected_artifact_checksum,
                            "stored_artifact_checksum": row.artifact_checksum,
                        },
                    )
                )
                pending_error = WorkflowStoreError(
                    "artifact_checksum_mismatch",
                    "The approval is not bound to this workflow's artifact checksum.",
                )
            elif expected_report_checksum and expected_report_checksum != row.report_checksum:
                session.add(
                    _audit(
                        row.id,
                        "approval_rejected_report_checksum",
                        {
                            "expected_report_checksum": expected_report_checksum,
                            "stored_report_checksum": row.report_checksum,
                        },
                    )
                )
                pending_error = WorkflowStoreError(
                    "report_checksum_mismatch",
                    "The approval is not bound to this workflow's report checksum.",
                )
            elif not row.eligible_for_review:
                session.add(
                    _audit(row.id, "approval_rejected_ineligible", {"target_identity": target})
                )
                pending_error = WorkflowStoreError(
                    "not_eligible_for_review",
                    "The workflow is not eligible for review.",
                )
            else:
                report = SafetyReport.model_validate_json(row.report_json)
                if report.blocking_reasons or report.missing_evidence:
                    session.add(
                        _audit(row.id, "approval_rejected_blockers", {"target_identity": target})
                    )
                    pending_error = WorkflowStoreError(
                        "evidence_incomplete",
                        "Policy blockers or missing evidence prevent approval.",
                    )
                elif report.rollback_status not in {"exact_restoration", "partial_restoration"}:
                    session.add(
                        _audit(
                            row.id,
                            "approval_rejected_rollback",
                            {"rollback_status": report.rollback_status},
                        )
                    )
                    pending_error = WorkflowStoreError(
                        "rollback_not_verified",
                        "Approval requires exact_restoration or partial_restoration.",
                    )
                else:
                    approval = ApprovalRecord(
                        id=str(uuid.uuid4()),
                        workflow_id=row.id,
                        migration_id=row.migration_id,
                        artifact_checksum=row.artifact_checksum,
                        report_checksum=row.report_checksum,
                        target_identity=target,
                        decision="recorded",
                        authentication_available=True,
                        approver_identity=authenticated.identity,
                        limitation=(
                            "Approval recorded for an authenticated principal. "
                            "This is not target execution."
                        ),
                        created_at=_now(),
                    )
                    try:
                        session.add(approval)
                        row.state = "approval_recorded"
                        row.updated_at = _now()
                        session.add(
                            _audit(
                                row.id,
                                "approval_recorded",
                                {
                                    "approval_id": approval.id,
                                    "target_identity": target,
                                    "artifact_checksum": row.artifact_checksum,
                                    "report_checksum": row.report_checksum,
                                    "authentication_available": True,
                                    "approver_identity": authenticated.identity,
                                },
                            )
                        )
                        session.flush()
                        summary = _approval_summary(approval)
                    except IntegrityError as exc:
                        pending_error = WorkflowStoreError(
                            "duplicate_approval",
                            "An approval already exists for this artifact, report, and target.",
                        )
                        del exc
    except OperationalError as exc:
        raise WorkflowStoreUnavailable from exc
    if pending_error is not None:
        raise pending_error
    if summary is None:
        raise WorkflowStoreError("approval_failed", "The approval could not be recorded.")
    return summary


def _detail(session: Session, row: MigrationWorkflow) -> WorkflowDetail:
    approvals = session.scalars(
        select(ApprovalRecord)
        .where(ApprovalRecord.workflow_id == row.id)
        .order_by(ApprovalRecord.created_at.asc())
    ).all()
    events = session.scalars(
        select(AuditEvent)
        .where(AuditEvent.workflow_id == row.id)
        .order_by(AuditEvent.created_at.asc())
    ).all()
    report = SafetyReport.model_validate_json(row.report_json)
    return WorkflowDetail(
        id=row.id,
        source_id=row.source_id,
        migration_id=row.migration_id,
        artifact_checksum=row.artifact_checksum,
        artifact_status=row.artifact_status,
        artifact_applied=False,
        schema_fingerprint=row.schema_fingerprint,
        state=row.state,  # type: ignore[arg-type]
        report_checksum=row.report_checksum,
        evidence_fingerprint=row.evidence_fingerprint,
        report_stale=row.report_stale,
        eligible_for_review=row.eligible_for_review and not row.report_stale,
        fully_reversible=row.fully_reversible,
        rollback_status=row.rollback_status,  # type: ignore[arg-type]
        report=report,
        approvals=[_approval_summary(item) for item in approvals],
        audit_events=[_audit_summary(item) for item in events],
        created_at=_iso(row.created_at),
        updated_at=_iso(row.updated_at),
    )


def _summary(row: MigrationWorkflow) -> WorkflowSummary:
    return WorkflowSummary(
        id=row.id,
        source_id=row.source_id,
        migration_id=row.migration_id,
        artifact_checksum=row.artifact_checksum,
        schema_fingerprint=row.schema_fingerprint,
        state=row.state,  # type: ignore[arg-type]
        eligible_for_review=row.eligible_for_review and not row.report_stale,
        report_stale=row.report_stale,
        rollback_status=row.rollback_status,  # type: ignore[arg-type]
        created_at=_iso(row.created_at),
        updated_at=_iso(row.updated_at),
    )


def _approval_summary(row: ApprovalRecord) -> ApprovalSummary:
    return ApprovalSummary(
        id=row.id,
        migration_id=row.migration_id,
        artifact_checksum=row.artifact_checksum,
        report_checksum=row.report_checksum,
        target_identity=row.target_identity,
        decision=row.decision,  # type: ignore[arg-type]
        authentication_available=row.authentication_available,
        approver_identity=row.approver_identity,
        limitation=row.limitation,
        created_at=_iso(row.created_at),
    )


def _audit_summary(row: AuditEvent) -> AuditEventSummary:
    return AuditEventSummary(
        id=row.id,
        event_type=row.event_type,
        detail=json.loads(row.detail_json),
        created_at=_iso(row.created_at),
    )


def _audit(workflow_id: str | None, event_type: str, detail: dict[str, object]) -> AuditEvent:
    return AuditEvent(
        id=str(uuid.uuid4()),
        workflow_id=workflow_id,
        event_type=event_type,
        detail_json=json.dumps(detail, sort_keys=True, separators=(",", ":"), ensure_ascii=True),
        created_at=_now(),
    )


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC).isoformat()
    return value.isoformat()
