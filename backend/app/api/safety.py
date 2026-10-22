"""Rollback and safety-report routes. They do not approve or apply a target."""

import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from app.core.config import Settings, UnsafeDatabaseConfigurationError
from app.schemas.report import SafetyReport, SafetyReportRequest
from app.schemas.rollback import RollbackReport
from app.schemas.sandbox import SandboxRunRequest
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

router = APIRouter(tags=["safety"])


@router.post(
    "/sources/{source_id}/artifacts/{migration_id}/rollback",
    response_model=RollbackReport,
)
def run_rollback(
    source_id: str,
    migration_id: str,
    body: SandboxRunRequest,
    request: Request,
) -> RollbackReport:
    _require_source(source_id)
    if body.confirm is not True:
        raise HTTPException(status_code=409, detail={"error": "sandbox_not_confirmed"}) from None
    settings: Settings = request.app.state.settings
    try:
        return run_rollback_test(settings, migration_id)
    except UnsafeDatabaseConfigurationError as exc:
        raise _configuration_error(exc) from None


@router.post(
    "/sources/{source_id}/artifacts/{migration_id}/report",
    response_model=SafetyReport,
)
def create_safety_report(
    source_id: str,
    migration_id: str,
    body: SafetyReportRequest,
    request: Request,
) -> SafetyReport:
    _require_source(source_id)
    if body.confirm is not True:
        raise HTTPException(status_code=409, detail={"error": "sandbox_not_confirmed"}) from None
    settings: Settings = request.app.state.settings
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
    provider = getattr(request.app.state, "llm_provider", None)
    proposal = create_proposal(
        settings,
        snapshot,
        body.request,
        use_llm=body.use_llm,
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
        except UnsafeDatabaseConfigurationError as exc:
            raise _configuration_error(exc) from None
    return build_safety_report(
        proposal,
        assessment,
        saved,
        rollback,
        artifact_matches=matches,
    )


def _require_source(source_id: str) -> None:
    if source_id != BOOKSTORE_SOURCE_ID:
        raise HTTPException(status_code=404, detail={"error": "unknown_source"}) from None


def _configuration_error(exc: UnsafeDatabaseConfigurationError) -> HTTPException:
    message = str(exc)
    if message.startswith("Refusing to run the sandbox"):
        code = "sandbox_not_enabled"
    elif "credentials" in message or "not schemapilot_sandbox" in message:
        code = "sandbox_identity_rejected"
    else:
        code = "sandbox_not_configured"
    return HTTPException(status_code=409, detail={"error": code, "message": message})
