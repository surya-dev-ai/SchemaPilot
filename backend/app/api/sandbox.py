"""Sandbox routes. They do not open the source or target database."""

from fastapi import APIRouter, HTTPException, Request

from app.core.config import Settings, UnsafeDatabaseConfigurationError
from app.schemas.sandbox import SandboxRun, SandboxRunRequest
from app.services.sandbox_manager import SandboxRejected, SandboxUnavailable, run_sandbox
from app.services.source_manager import BOOKSTORE_SOURCE_ID

router = APIRouter(tags=["sandbox"])


@router.post(
    "/sources/{source_id}/artifacts/{migration_id}/sandbox",
    response_model=SandboxRun,
)
def run_artifact_in_sandbox(
    source_id: str,
    migration_id: str,
    body: SandboxRunRequest,
    request: Request,
) -> SandboxRun:
    if source_id != BOOKSTORE_SOURCE_ID:
        raise HTTPException(status_code=404, detail={"error": "unknown_source"}) from None
    if body.confirm is not True:
        raise HTTPException(status_code=409, detail={"error": "sandbox_not_confirmed"}) from None
    settings: Settings = request.app.state.settings
    try:
        return run_sandbox(settings, migration_id)
    except SandboxRejected as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": exc.code, "message": exc.message},
        ) from None
    except SandboxUnavailable:
        raise HTTPException(status_code=503, detail={"error": "sandbox_unavailable"}) from None
    except UnsafeDatabaseConfigurationError as exc:
        message = str(exc)
        if message.startswith("Refusing to run the sandbox"):
            code = "sandbox_not_enabled"
        elif "credentials" in message or "not schemapilot_sandbox" in message:
            code = "sandbox_identity_rejected"
        else:
            code = "sandbox_not_configured"
        raise HTTPException(
            status_code=409,
            detail={"error": code, "message": message},
        ) from None
