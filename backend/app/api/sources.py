"""Read-only source and schema routes. These handlers do not run at startup."""

from fastapi import APIRouter, HTTPException, Request

from app.core.config import Settings
from app.schemas.domain import SchemaSnapshot, SourceListResponse
from app.services.schema_inspector import inspect_source
from app.services.source_manager import (
    SourceNotConfiguredError,
    SourceNotFoundError,
    SourceNotReadOnlyError,
    SourceUnavailableError,
    UnexpectedSourceDatabaseError,
    list_sources,
)

router = APIRouter(tags=["sources"])


@router.get("/sources", response_model=SourceListResponse)
def get_sources(request: Request) -> SourceListResponse:
    settings: Settings = request.app.state.settings
    return list_sources(settings)


@router.get("/sources/{source_id}/schema", response_model=SchemaSnapshot)
def get_source_schema(source_id: str, request: Request) -> SchemaSnapshot:
    settings: Settings = request.app.state.settings
    try:
        return inspect_source(settings, source_id)
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
