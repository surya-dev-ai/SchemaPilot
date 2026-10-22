"""Process health. This route does not connect to PostgreSQL or run migrations."""

from fastapi import APIRouter, Request

from app import __version__
from app.core.config import Settings
from app.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    settings: Settings = request.app.state.settings
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=__version__,
        api_version="v1",
        target_execution_enabled=settings.target_execution_enabled,
        migrations_on_startup=False,
        database_connectivity="not_checked",
        app_database_configured=settings.database_configured(settings.app_database_url),
        sandbox_database_configured=settings.database_configured(settings.sandbox_database_url),
        target_database_configured=settings.database_configured(settings.target_database_url),
        llm_enabled=settings.llm_enabled,
        llm_configured=settings.llm_configured(),
        llm_provider=(settings.llm_provider if settings.llm_enabled else "none"),
        llm_model=(settings.llm_model if settings.llm_configured() else None),
        authentication_available=settings.authentication_available,
        phase="12",
    )
