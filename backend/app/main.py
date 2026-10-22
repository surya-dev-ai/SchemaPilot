"""FastAPI application factory.

Startup creates the HTTP app and CORS policy only. It does not open a database
connection, create tables, or run Alembic.
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.db.session import assert_startup_will_not_migrate


def create_app(settings: Settings | None = None) -> FastAPI:
    active_settings = settings or get_settings()
    assert_startup_will_not_migrate(active_settings)

    app = FastAPI(
        title=active_settings.app_name,
        version="0.1.0",
        summary="Phase 1 foundation. Target execution is disabled.",
    )
    app.state.settings = active_settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=active_settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Accept", "Content-Type"],
    )
    app.include_router(api_router, prefix=active_settings.api_v1_prefix)

    @app.exception_handler(RequestValidationError)
    async def reject_malformed_request(
        _request: Request,
        _exc: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": {"error": "malformed_request"}})

    return app


app = create_app()
