"""OIDC sign-in routes. Access and refresh tokens are never stored in session cookies."""

from __future__ import annotations

import secrets
from typing import Any
from urllib.parse import urlencode

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.core.config import Settings
from app.schemas.auth import AuthenticatedUser, AuthSessionResponse
from app.services.auth import (
    can_access_team_workspace,
    claim_groups,
    claim_roles,
    principal_from_request,
    require_api_principal,
)

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.get("/me", response_model=AuthSessionResponse)
def auth_session(request: Request) -> AuthSessionResponse:
    settings: Settings = request.app.state.settings
    if not settings.authentication_available:
        return AuthSessionResponse(
            enabled=False,
            authenticated=False,
            can_access_team_workspace=True,
        )
    principal = principal_from_request(request)
    if principal is None:
        return AuthSessionResponse(enabled=True, authenticated=False)
    token = request.session.get("csrf_token")
    if not isinstance(token, str) or len(token) < 32:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return AuthSessionResponse(
        enabled=True,
        authenticated=True,
        user=AuthenticatedUser(
            email=principal.email,
            display_name=principal.display_name,
            roles=list(principal.roles),
        ),
        csrf_token=token,
        can_access_team_workspace=can_access_team_workspace(settings, principal),
    )


@router.get("/login")
async def login(request: Request):
    settings: Settings = request.app.state.settings
    if not settings.authentication_available:
        raise HTTPException(status_code=404, detail={"error": "authentication_disabled"})
    oauth: OAuth = request.app.state.oidc_oauth
    client = oauth.create_client("schemapilot")
    return await client.authorize_redirect(request, settings.oidc_redirect_uri)


@router.get("/callback")
async def callback(request: Request):
    settings: Settings = request.app.state.settings
    if not settings.authentication_available:
        raise HTTPException(status_code=404, detail={"error": "authentication_disabled"})
    try:
        oauth: OAuth = request.app.state.oidc_oauth
        client = oauth.create_client("schemapilot")
        token = await client.authorize_access_token(request)
        info = token.get("userinfo")
        claims: dict[str, Any] = dict(info) if isinstance(info, dict) else {}
        subject = claims.get("sub")
        issuer = claims.get("iss")
        if not isinstance(subject, str) or not subject.strip():
            raise ValueError("OIDC response did not contain a subject.")
        identity = f"{issuer}|{subject}" if isinstance(issuer, str) and issuer else subject
        roles = list(claim_roles(claims, settings.auth_role_claim))[:50]
        groups = list(claim_groups(claims, settings.auth_group_claim))[:100]
        request.session.clear()
        request.session["user"] = {
            "identity": identity[:512],
            "email": _safe_claim(claims.get("email")),
            "name": _safe_claim(claims.get("name")),
            "roles": roles,
            "groups": groups,
        }
        request.session["csrf_token"] = secrets.token_urlsafe(32)
    except Exception:
        # Provider errors can contain authorization codes or endpoint details.
        # Do not reflect or log them; the browser gets a generic error marker.
        return RedirectResponse(_frontend_url(settings, auth_error="login_failed"), status_code=303)
    return RedirectResponse(_frontend_url(settings), status_code=303)


@router.post("/logout", response_model=AuthSessionResponse)
def logout(request: Request) -> AuthSessionResponse:
    if request.app.state.settings.authentication_available:
        require_api_principal(request)
        request.session.clear()
    return AuthSessionResponse(
        enabled=bool(request.app.state.settings.authentication_available), authenticated=False
    )


def register_oidc(settings: Settings) -> OAuth:
    """Create the provider-agnostic OIDC client from trusted local configuration."""

    oauth = OAuth()
    if settings.authentication_available:
        oauth.register(
            name="schemapilot",
            client_id=settings.oidc_client_id,
            client_secret=settings.oidc_client_secret,
            server_metadata_url=settings.oidc_metadata_url,
            client_kwargs={"scope": "openid profile email"},
        )
    return oauth


def _frontend_url(settings: Settings, *, auth_error: str | None = None) -> str:
    base = settings.auth_frontend_url.rstrip("/")
    if auth_error:
        return f"{base}/?{urlencode({'auth_error': auth_error})}#migration"
    return f"{base}/#migration"


def _safe_claim(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip()[:256] or None
