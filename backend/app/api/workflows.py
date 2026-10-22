"""Persisted workflow history and approval foundation routes."""

import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from app.core.config import Settings, UnsafeDatabaseConfigurationError
from app.schemas.workflow import (
    ApprovalCreateRequest,
    ApprovalSummary,
    WorkflowDetail,
    WorkflowListResponse,
    WorkflowPersistRequest,
)
from app.services.llm.assisted_planner import create_proposal
from app.services.migration_generator import ARTIFACTS_DIR, generate_migration
from app.services.report_service import artifact_matches_plan, build_safety_report
from app.services.risk_engine import assess_risk
from app.services.rollback_tester import run_rollback_test
from app.services.sandbox_manager import SandboxRejected, load_verified_artifact
from app.services.schema_inspector import inspect_source
from app.services.source_manager import (
    BOOKSTORE_SOURCE_ID,
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
        provider=provider,
    )
    try:
        return persist_workflow(
            settings,
            proposal=proposal,
            assessment=assessment,
            report=report,
            rollback=rollback,
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


@router.get("/workflows", response_model=WorkflowListResponse)
def read_workflows(request: Request) -> WorkflowListResponse:
    settings: Settings = request.app.state.settings
    try:
        return list_workflows(settings)
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
        return get_workflow(settings, workflow_id)
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


@router.post("/workflows/{workflow_id}/approvals", response_model=ApprovalSummary)
def create_approval(
    workflow_id: str,
    body: ApprovalCreateRequest,
    request: Request,
) -> ApprovalSummary:
    settings: Settings = request.app.state.settings
    try:
        return record_approval(settings, workflow_id, body)
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
    provider=None,
):
    try:
        snapshot = inspect_source(settings, source_id)
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
    with tempfile.TemporaryDirectory() as temporary:
        fresh = generate_migration(snapshot, proposal, assessment, Path(temporary))
    matches = artifact_matches_plan(saved, fresh)
    rollback = None
    if matches:
        try:
            rollback = run_rollback_test(settings, migration_id)
        except UnsafeDatabaseConfigurationError:
            rollback = None
    report = build_safety_report(
        proposal,
        assessment,
        saved,
        rollback,
        artifact_matches=matches,
    )
    return proposal, assessment, report, rollback


def _require_source(source_id: str) -> None:
    if source_id != BOOKSTORE_SOURCE_ID:
        raise HTTPException(status_code=404, detail={"error": "unknown_source"}) from None
