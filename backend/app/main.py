"""FastAPI application factory.

Startup creates the HTTP app and CORS policy only. It does not open a database
connection, create tables, or run Alembic.
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware

from app.api.auth import register_oidc
from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.db.session import assert_startup_will_not_migrate


def create_app(settings: Settings | None = None) -> FastAPI:
    active_settings = settings or get_settings()
    assert_startup_will_not_migrate(active_settings)

    app = FastAPI(
        title=active_settings.app_name,
        version="0.1.0",
        summary="SchemaPilot migration workspace. Target execution is disabled.",
        docs_url=None if active_settings.authentication_available else "/docs",
        redoc_url=None if active_settings.authentication_available else "/redoc",
        openapi_url=None if active_settings.authentication_available else "/openapi.json",
    )
    app.state.settings = active_settings
    app.state.oidc_oauth = register_oidc(active_settings)
    if active_settings.authentication_available:
        app.add_middleware(
            SessionMiddleware,
            secret_key=active_settings.auth_session_secret,
            session_cookie="schemapilot_session",
            max_age=8 * 60 * 60,
            same_site="lax",
            https_only=active_settings.auth_cookie_secure,
        )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=active_settings.cors_origin_list,
        allow_credentials=active_settings.authentication_available,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Accept", "Content-Type", "X-CSRF-Token"],
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
