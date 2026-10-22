"""Artifact routes. Generation does not apply SQL or open the source database."""

from fastapi import APIRouter, HTTPException, Request

from app.core.config import Settings
from app.schemas.artifacts import MigrationArtifact
from app.schemas.planning import PlanCreateRequest
from app.services.llm.assisted_planner import create_proposal
from app.services.migration_generator import ArtifactRejectedError, generate_migration
from app.services.risk_engine import assess_risk
from app.services.schema_inspector import inspect_source
from app.services.source_manager import (
    SourceNotConfiguredError,
    SourceNotFoundError,
    SourceNotReadOnlyError,
    SourceUnavailableError,
    UnexpectedSourceDatabaseError,
)

router = APIRouter(tags=["artifacts"])


@router.post("/sources/{source_id}/artifacts", response_model=MigrationArtifact)
def create_artifact(
    source_id: str,
    body: PlanCreateRequest,
    request: Request,
) -> MigrationArtifact:
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
        return generate_migration(snapshot, proposal, assessment)
    except ArtifactRejectedError as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": exc.code, "message": exc.message},
        ) from None
