"""OIDC session and role-gate tests. Provider interactions are mocked."""

from __future__ import annotations

from typing import Any

import pytest
from app.api.auth import auth_session
from app.core.config import Settings
from app.main import create_app
from app.services.auth import claim_roles
from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.testclient import TestClient
from pydantic import ValidationError
from tests.test_llm import _snapshot


def _oidc_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "auth_required": True,
        "oidc_metadata_url": "https://idp.example.test/.well-known/openid-configuration",
        "oidc_client_id": "schemapilot-client",
        "oidc_client_secret": "provider-secret-for-tests",
        "oidc_redirect_uri": "http://localhost:8000/api/v1/auth/callback",
        "auth_frontend_url": "http://localhost:5175",
        "auth_session_secret": "test-only-session-secret-with-at-least-32-characters",
        "auth_cookie_secure": False,
    }
    values.update(overrides)
    return Settings(**values)


def test_auth_required_refuses_incomplete_oidc_configuration() -> None:
    with pytest.raises(ValidationError, match="OIDC auth requires"):
        Settings(auth_required=True)


def test_auth_status_does_not_claim_identity_when_authentication_is_disabled() -> None:
    settings = Settings(auth_required=False)
    app = create_app(settings)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/auth/me",
            "headers": [],
            "query_string": b"",
            "server": ("test", 80),
            "client": ("test", 123),
            "scheme": "http",
            "app": app,
        }
    )

    response = auth_session(request)

    assert response.authenticated is False
    assert response.user is None
    assert response.can_access_team_workspace is True


def test_auth_routes_and_protected_api_require_oidc_session() -> None:
    client = TestClient(create_app(_oidc_settings()))

    session = client.get("/api/v1/auth/me")
    protected = client.get("/api/v1/sources")

    assert session.status_code == 200
    assert session.json()["enabled"] is True
    assert session.json()["authenticated"] is False
    assert protected.status_code == 401
    assert protected.json()["detail"]["error"] == "authentication_required"
    assert client.get("/docs").status_code == 404


def test_cors_preflight_allows_csrf_header_for_authenticated_writes() -> None:
    client = TestClient(create_app(_oidc_settings()))
    response = client.options(
        "/api/v1/workflows",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-csrf-token",
        },
    )
    assert response.status_code == 200
    assert "x-csrf-token" in response.headers["access-control-allow-headers"].lower()


def test_oidc_callback_creates_minimal_session_and_login_redirects() -> None:
    app = create_app(_oidc_settings())

    class FakeClient:
        async def authorize_redirect(self, _request, redirect_uri):
            assert redirect_uri == "http://localhost:8000/api/v1/auth/callback"
            return RedirectResponse("https://idp.example.test/authorize")

        async def authorize_access_token(self, _request):
            return {
                "access_token": "must-not-be-stored",
                "userinfo": {
                    "sub": "subject-1",
                    "iss": "https://idp.example.test",
                    "email": "member@example.test",
                    "name": "SchemaPilot Member",
                    "roles": ["engineer", "viewer"],
                },
            }

    class FakeOAuth:
        def create_client(self, _name: str) -> FakeClient:
            return FakeClient()

    app.state.oidc_oauth = FakeOAuth()
    client = TestClient(app, base_url="http://localhost")

    login = client.get("/api/v1/auth/login", follow_redirects=False)
    callback = client.get("/api/v1/auth/callback?code=opaque&state=opaque", follow_redirects=False)
    session = client.get("/api/v1/auth/me")

    assert login.status_code in {302, 307}
    assert login.headers["location"] == "https://idp.example.test/authorize"
    assert callback.status_code == 303
    assert callback.headers["location"] == "http://localhost:5175/#migration"
    assert session.status_code == 200
    assert session.json()["authenticated"] is True
    assert session.json()["user"]["email"] == "member@example.test"
    assert session.json()["user"]["roles"] == ["engineer", "viewer"]
    assert "must-not-be-stored" not in client.cookies.get("schemapilot_session", "")
    assert session.json()["csrf_token"]


def test_engineer_role_and_csrf_are_required_for_planning(monkeypatch: pytest.MonkeyPatch) -> None:
    app = create_app(_oidc_settings())
    monkeypatch.setattr("app.api.plans.inspect_source", lambda *_args: _snapshot())

    @app.get("/__test__/session/{role}")
    def create_test_session(role: str, request: Request):
        request.session["user"] = {"identity": f"{role}-subject", "roles": [role]}
        request.session["csrf_token"] = "csrf-test-token-at-least-32-chars"
        return {"ok": True}

    client = TestClient(app)
    client.get("/__test__/session/engineer")
    request_body: dict[str, Any] = {
        "request": "Add a nullable text column called phone_number to users.",
        "use_llm": False,
    }

    no_csrf = client.post("/api/v1/sources/bookstore-demo/plans", json=request_body)
    accepted = client.post(
        "/api/v1/sources/bookstore-demo/plans",
        json=request_body,
        headers={"X-CSRF-Token": "csrf-test-token-at-least-32-chars"},
    )
    client.get("/__test__/session/viewer")
    viewer_denied = client.post(
        "/api/v1/sources/bookstore-demo/plans",
        json=request_body,
        headers={"X-CSRF-Token": "csrf-test-token-at-least-32-chars"},
    )

    assert no_csrf.status_code == 403
    assert no_csrf.json()["detail"]["error"] == "csrf_validation_failed"
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "proposed"
    assert viewer_denied.status_code == 403
    assert viewer_denied.json()["detail"]["error"] == "permission_denied"


def test_role_claim_can_be_nested_and_is_filtered_to_strings() -> None:
    claims = {"realm_access": {"roles": ["engineer", "approver", 42, " "]}}
    assert claim_roles(claims, "realm_access.roles") == ("engineer", "approver")
