"""Authentication and authorization boundary.

Phase 12 does not implement a login provider. Approvals and target execution
must fail closed until a real authenticated principal is available.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings


class AuthenticationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    """A verified human or service identity. Never invent this from request bodies."""

    identity: str
    scheme: str


def authentication_is_available(settings: Settings) -> bool:
    """True only when a real auth provider is configured and enabled."""

    return bool(getattr(settings, "authentication_available", False))


def require_authenticated_principal(
    settings: Settings,
    principal: AuthenticatedPrincipal | None,
) -> AuthenticatedPrincipal:
    """Return the principal or refuse. Request-body usernames are not accepted."""

    if not authentication_is_available(settings):
        raise AuthenticationError(
            "authentication_unavailable",
            "Authentication is not implemented. Verified approvals cannot be recorded.",
        )
    if principal is None or not principal.identity.strip():
        raise AuthenticationError(
            "unauthenticated",
            "An authenticated principal is required.",
        )
    return principal
