"""Planning routes. The planner itself does not open a database connection."""

from fastapi import APIRouter, HTTPException, Request

from app.core.config import Settings
from app.schemas.planning import MigrationProposal, PlanCreateRequest
from app.services.llm.assisted_planner import create_proposal
from app.services.schema_inspector import inspect_source
from app.services.source_manager import (
    SourceNotConfiguredError,
    SourceNotFoundError,
    SourceNotReadOnlyError,
    SourceUnavailableError,
    UnexpectedSourceDatabaseError,
)

router = APIRouter(tags=["plans"])


@router.post("/sources/{source_id}/plans", response_model=MigrationProposal)
def create_plan(source_id: str, body: PlanCreateRequest, request: Request) -> MigrationProposal:
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
    return create_proposal(
        settings,
        snapshot,
        body.request,
        use_llm=body.use_llm,
        provider=provider,
    )
