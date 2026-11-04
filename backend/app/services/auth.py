"""OIDC identity, application-session, CSRF, and role helpers."""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request

from app.core.config import Settings


class AuthenticationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    """A verified OIDC identity. Never infer this from a request body."""

    identity: str
    scheme: str
    email: str | None = None
    display_name: str | None = None
    roles: tuple[str, ...] = ()
    groups: tuple[str, ...] = ()


def authentication_is_available(settings: Settings) -> bool:
    """The app advertises auth only when OIDC is required and fully configured."""

    return bool(settings.authentication_available)


def principal_from_request(request: Request) -> AuthenticatedPrincipal | None:
    if "session" not in request.scope:
        return None
    session_user = request.session.get("user")
    if not isinstance(session_user, dict):
        return None
    identity = session_user.get("identity")
    if not isinstance(identity, str) or not identity.strip():
        return None
    raw_roles = session_user.get("roles", [])
    roles = (
        tuple(item for item in raw_roles if isinstance(item, str))
        if isinstance(raw_roles, list)
        else ()
    )
    raw_groups = session_user.get("groups", [])
    groups = (
        tuple(item for item in raw_groups if isinstance(item, str))
        if isinstance(raw_groups, list)
        else ()
    )
    return AuthenticatedPrincipal(
        identity=identity,
        scheme="oidc",
        email=_optional_text(session_user.get("email")),
        display_name=_optional_text(session_user.get("name")),
        roles=roles,
        groups=groups,
    )


def require_api_principal(request: Request) -> AuthenticatedPrincipal | None:
    """Protect application APIs and enforce same-site CSRF for mutations."""

    settings: Settings = request.app.state.settings
    if not authentication_is_available(settings):
        return None
    principal = principal_from_request(request)
    if principal is None:
        raise HTTPException(
            status_code=401,
            detail={"error": "authentication_required", "message": "Sign in to continue."},
        )
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        expected = request.session.get("csrf_token", "")
        supplied = request.headers.get("x-csrf-token", "")
        if (
            not isinstance(expected, str)
            or not expected
            or not hmac.compare_digest(expected, supplied)
        ):
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "csrf_validation_failed",
                    "message": "Refresh the page and try again.",
                },
            )
    request.state.principal = principal
    return principal


def require_role(request: Request, role: str) -> AuthenticatedPrincipal | None:
    """Require a configured OIDC role for write/approval operations."""

    principal = require_api_principal(request)
    if principal is None:
        return None
    settings: Settings = request.app.state.settings
    admin_roles = _csv_roles(settings.auth_admin_roles)
    if _has_any_role(principal, admin_roles):
        return principal
    allowed = _csv_roles(getattr(settings, f"auth_{role}_roles"))
    if not _has_any_role(principal, allowed):
        raise HTTPException(
            status_code=403,
            detail={"error": "permission_denied", "message": f"The {role} role is required."},
        )
    return principal


def require_engineer(request: Request) -> AuthenticatedPrincipal | None:
    return require_role(request, "engineer")


def require_approver(request: Request) -> AuthenticatedPrincipal | None:
    return require_role(request, "approver")


def require_authenticated_principal(
    settings: Settings,
    principal: AuthenticatedPrincipal | None,
) -> AuthenticatedPrincipal:
    """Return the principal or refuse. Request-body usernames are not accepted."""

    if not authentication_is_available(settings):
        raise AuthenticationError(
            "authentication_unavailable",
            "Authentication is not configured. Verified approvals cannot be recorded.",
        )
    if principal is None or not principal.identity.strip():
        raise AuthenticationError("unauthenticated", "An authenticated principal is required.")
    return principal


def claim_roles(claims: dict[str, Any], claim_path: str) -> tuple[str, ...]:
    """Read configured roles from a simple or dotted OIDC claim path."""

    value: Any = claims
    for part in claim_path.split("."):
        value = value.get(part) if isinstance(value, dict) else None
    if isinstance(value, str):
        candidates = [value]
    elif isinstance(value, list):
        candidates = value
    else:
        candidates = []
    return tuple(
        item.strip()[:128] for item in candidates if isinstance(item, str) and item.strip()
    )


def claim_groups(claims: dict[str, Any], claim_path: str) -> tuple[str, ...]:
    return claim_roles(claims, claim_path)


def has_configured_role(
    settings: Settings,
    principal: AuthenticatedPrincipal,
    role: str,
) -> bool:
    if _has_any_role(principal, _csv_roles(settings.auth_admin_roles)):
        return True
    return _has_any_role(principal, _csv_roles(getattr(settings, f"auth_{role}_roles")))


def can_access_team_workspace(
    settings: Settings,
    principal: AuthenticatedPrincipal | None,
) -> bool:
    if not settings.authentication_available:
        return True
    if principal is None:
        return False
    if _has_any_role(principal, _csv_roles(settings.auth_admin_roles)):
        return True
    allowed_groups = _csv_roles(settings.auth_team_groups)
    return bool({group.casefold() for group in principal.groups}.intersection(allowed_groups))


def _has_any_role(principal: AuthenticatedPrincipal, allowed: set[str]) -> bool:
    normalized = {role.casefold() for role in principal.roles}
    return bool(normalized.intersection(allowed))


def _csv_roles(value: str) -> set[str]:
    return {role.strip().casefold() for role in value.split(",") if role.strip()}


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value[:256] or None
