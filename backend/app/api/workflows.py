"""Persisted workflow history and approval foundation routes."""

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.config import Settings, UnsafeDatabaseConfigurationError
from app.schemas.workflow import (
    ApprovalCreateRequest,
    ApprovalSummary,
    WorkflowDetail,
    WorkflowListResponse,
    WorkflowPersistRequest,
)
from app.services.auth import principal_from_request, require_approver, require_engineer
from app.services.llm.assisted_planner import create_proposal
from app.services.migration_generator import ARTIFACTS_DIR, generate_migration
from app.services.report_service import artifact_matches_plan, build_safety_report
from app.services.risk_engine import assess_risk
from app.services.rollback_evidence_store import RollbackEvidenceError, load_rollback_evidence
from app.services.sandbox_checkpoint_store import (
    SandboxCheckpointSessionError,
    load_checkpoint_session,
)
from app.services.sandbox_manager import SandboxRejected, load_verified_artifact
from app.services.schema_inspector import inspect_sandbox, inspect_source
from app.services.source_manager import (
    BOOKSTORE_SOURCE_ID,
    SANDBOX_SOURCE_ID,
    SourceNotConfiguredError,
    SourceNotFoundError,
    SourceNotReadOnlyError,
    SourceUnavailableError,
    UnexpectedSourceDatabaseError,
)
from app.services.workflow_store import (
    WorkflowStoreError,
    WorkflowStoreUnavailable,
    get_workflow,
    list_workflows,
    persist_workflow,
    record_approval,
)

router = APIRouter(tags=["workflows"])


@router.post(
    "/sources/{source_id}/artifacts/{migration_id}/workflows",
    response_model=WorkflowDetail,
)
def persist_artifact_workflow(
    source_id: str,
    migration_id: str,
    body: WorkflowPersistRequest,
    request: Request,
) -> WorkflowDetail:
    require_engineer(request)
    _require_source(source_id)
    if body.confirm is not True:
        raise HTTPException(status_code=409, detail={"error": "workflow_not_confirmed"}) from None
    settings: Settings = request.app.state.settings
    provider = getattr(request.app.state, "llm_provider", None)
    proposal, assessment, report, rollback = _build_report(
        settings,
        source_id,
        migration_id,
        body.request,
        use_llm=body.use_llm,
        snapshot_session_id=body.snapshot_session_id,
        provider=provider,
    )
    try:
        return persist_workflow(
            settings,
            proposal=proposal,
            assessment=assessment,
            report=report,
            rollback=rollback,
            principal=principal_from_request(request),
            visibility=body.visibility,
        )
    except WorkflowStoreUnavailable:
        raise HTTPException(status_code=503, detail={"error": "app_database_unavailable"}) from None
    except WorkflowStoreError as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": exc.code, "message": exc.message},
        ) from None
    except UnsafeDatabaseConfigurationError as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": "app_database_not_configured", "message": str(exc)},
        ) from None
    except RollbackEvidenceError as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": "rollback_evidence_invalid", "message": str(exc)},
        ) from None


@router.get("/workflows", response_model=WorkflowListResponse)
def read_workflows(request: Request) -> WorkflowListResponse:
    settings: Settings = request.app.state.settings
    try:
        return list_workflows(settings, principal=principal_from_request(request))
    except WorkflowStoreUnavailable:
        raise HTTPException(status_code=503, detail={"error": "app_database_unavailable"}) from None
    except WorkflowStoreError as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": exc.code, "message": exc.message},
        ) from None
    except UnsafeDatabaseConfigurationError as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": "app_database_not_configured", "message": str(exc)},
        ) from None


@router.get("/workflows/{workflow_id}", response_model=WorkflowDetail)
def read_workflow(workflow_id: str, request: Request) -> WorkflowDetail:
    settings: Settings = request.app.state.settings
    try:
        return get_workflow(settings, workflow_id, principal=principal_from_request(request))
    except WorkflowStoreUnavailable:
        raise HTTPException(status_code=503, detail={"error": "app_database_unavailable"}) from None
    except WorkflowStoreError as exc:
        status = 404 if exc.code == "workflow_not_found" else 409
        raise HTTPException(
            status_code=status,
            detail={"error": exc.code, "message": exc.message},
        ) from None
    except UnsafeDatabaseConfigurationError as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": "app_database_not_configured", "message": str(exc)},
        ) from None


@router.post(
    "/workflows/{workflow_id}/approvals",
    response_model=ApprovalSummary,
    dependencies=[Depends(require_approver)],
)
def create_approval(
    workflow_id: str,
    body: ApprovalCreateRequest,
    request: Request,
) -> ApprovalSummary:
    settings: Settings = request.app.state.settings
    try:
        return record_approval(
            settings,
            workflow_id,
            body,
            principal=principal_from_request(request),
        )
    except WorkflowStoreUnavailable:
        raise HTTPException(status_code=503, detail={"error": "app_database_unavailable"}) from None
    except WorkflowStoreError as exc:
        status = 404 if exc.code == "workflow_not_found" else 409
        raise HTTPException(
            status_code=status,
            detail={"error": exc.code, "message": exc.message},
        ) from None
    except UnsafeDatabaseConfigurationError as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": "app_database_not_configured", "message": str(exc)},
        ) from None


@router.get("/workflows/{workflow_id}/audit")
def read_audit(workflow_id: str, request: Request) -> dict[str, object]:
    detail = read_workflow(workflow_id, request)
    return {
        "workflow_id": detail.id,
        "events": [event.model_dump() for event in detail.audit_events],
    }


def _build_report(
    settings: Settings,
    source_id: str,
    migration_id: str,
    request_text: str,
    *,
    use_llm: bool = False,
    snapshot_session_id: str | None = None,
    provider=None,
):
    try:
        snapshot = (
            inspect_sandbox(settings)
            if source_id == SANDBOX_SOURCE_ID
            else inspect_source(settings, source_id)
        )
    except SourceNotFoundError:
        raise HTTPException(status_code=404, detail={"error": "unknown_source"}) from None
    except SourceNotConfiguredError:
        raise HTTPException(status_code=409, detail={"error": "source_not_configured"}) from None
    except SourceNotReadOnlyError:
        raise HTTPException(status_code=409, detail={"error": "source_not_read_only"}) from None
    except UnexpectedSourceDatabaseError:
        raise HTTPException(status_code=409, detail={"error": "unexpected_database"}) from None
    except SourceUnavailableError:
        raise HTTPException(status_code=503, detail={"error": "source_unavailable"}) from None
    proposal = create_proposal(
        settings,
        snapshot,
        request_text,
        use_llm=use_llm,
        provider=provider,
    )
    assessment = assess_risk(snapshot, proposal)
    try:
        saved = load_verified_artifact(ARTIFACTS_DIR, migration_id)
    except SandboxRejected as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": exc.code, "message": exc.message},
        ) from None
    if saved.source_id != source_id:
        raise HTTPException(
            status_code=409,
            detail={"error": "artifact_source_mismatch"},
        ) from None
    with tempfile.TemporaryDirectory() as temporary:
        fresh = generate_migration(snapshot, proposal, assessment, Path(temporary))
    matches = artifact_matches_plan(saved, fresh)
    rollback = None
    sandbox_run = None
    baseline_evidence = None
    snapshot_recovery = None
    if matches and snapshot_session_id is not None:
        try:
            session = load_checkpoint_session(snapshot_session_id, migration_id, saved.checksum)
            sandbox_run = session.validation_run
            baseline_evidence = session.baseline_evidence
            snapshot_recovery = (
                session.checkpoint
                if session.checkpoint.restore_status == "restore_verified"
                else None
            )
            rollback = load_rollback_evidence(
                migration_id,
                saved.checksum,
                session_id=snapshot_session_id,
            )
            if session.downgrade_report is not None:
                rollback = session.downgrade_report.model_copy(
                    update={"snapshot_recovery": snapshot_recovery}
                )
        except UnsafeDatabaseConfigurationError:
            rollback = None
        except SandboxCheckpointSessionError as exc:
            raise HTTPException(
                status_code=409,
                detail={"error": "sandbox_checkpoint_evidence_invalid", "message": str(exc)},
            ) from None
        except RollbackEvidenceError as exc:
            raise HTTPException(
                status_code=409,
                detail={"error": "rollback_evidence_invalid", "message": str(exc)},
            ) from None
    report = build_safety_report(
        proposal,
        assessment,
        saved,
        rollback,
        artifact_matches=matches,
        sandbox_run=sandbox_run,
        baseline_evidence=baseline_evidence,
        snapshot_recovery=snapshot_recovery,
        snapshot_session_id=snapshot_session_id,
    )
    return proposal, assessment, report, rollback


def _require_source(source_id: str) -> None:
    if source_id not in {BOOKSTORE_SOURCE_ID, SANDBOX_SOURCE_ID}:
        raise HTTPException(status_code=404, detail={"error": "unknown_source"}) from None
