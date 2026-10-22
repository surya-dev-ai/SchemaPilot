"""Health and startup safety tests."""

from app.core.config import Settings
from app.db import session as session_module
from app.main import create_app
from fastapi.testclient import TestClient


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_name": "SchemaPilot",
        "api_v1_prefix": "/api/v1",
        "cors_origins": "http://localhost:5173,http://127.0.0.1:5173",
        "app_database_url": None,
        "sandbox_database_url": None,
        "target_database_url": None,
        "target_execution_enabled": False,
        "allow_app_migrations": False,
        "authentication_available": False,
        "llm_enabled": False,
        "llm_api_key": None,
        "llm_api_base": "https://api.openai.com/v1",
        "llm_model": "gpt-4o-mini",
        "llm_timeout_seconds": 20.0,
        "llm_fallback_to_deterministic": True,
        "llm_provider": "openai_compatible",
    }
    values.update(overrides)
    return Settings.model_construct(**values)


def test_health_reports_foundation_status() -> None:
    client = TestClient(create_app(_settings()))
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "status": "ok",
        "service": "SchemaPilot",
        "version": "0.1.0",
        "api_version": "v1",
        "target_execution_enabled": False,
        "migrations_on_startup": False,
        "database_connectivity": "not_checked",
        "app_database_configured": False,
        "sandbox_database_configured": False,
        "target_database_configured": False,
        "llm_enabled": False,
        "llm_configured": False,
        "llm_provider": "none",
        "llm_model": None,
        "authentication_available": False,
        "phase": "12",
    }
    serialized = response.text.lower()
    assert "postgresql" not in serialized
    assert "password" not in serialized
    assert "change_me" not in serialized


def test_health_reports_configured_databases_without_urls() -> None:
    client = TestClient(
        create_app(
            _settings(
                app_database_url="postgresql+psycopg://app:secret@127.0.0.1:5432/schemapilot",
                sandbox_database_url="postgresql+psycopg://sandbox:secret@127.0.0.1:5433/sandbox",
            )
        )
    )
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["app_database_configured"] is True
    assert body["sandbox_database_configured"] is True
    assert body["database_connectivity"] == "not_checked"
    assert "secret" not in response.text
    assert "postgresql" not in response.text


def test_startup_does_not_open_a_database(monkeypatch) -> None:
    def fail_if_called(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("application startup created a database engine")

    monkeypatch.setattr(session_module, "create_engine", fail_if_called)
    client = TestClient(create_app(_settings(allow_app_migrations=True)))

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["migrations_on_startup"] is False


def test_health_stays_available_and_execution_routes_stay_absent() -> None:
    paths = set(create_app(_settings()).openapi()["paths"])
    assert "/api/v1/health" in paths
    assert "/api/v1/sources" in paths
    assert "/api/v1/sources/{source_id}/schema" in paths
    assert "/api/v1/sources/{source_id}/plans" in paths
    assert "/api/v1/sources/{source_id}/risk" in paths
    assert "/api/v1/sources/{source_id}/artifacts" in paths
    assert "/api/v1/sources/{source_id}/artifacts/{migration_id}/sandbox" in paths
    assert "/api/v1/sources/{source_id}/artifacts/{migration_id}/rollback" in paths
    assert "/api/v1/sources/{source_id}/artifacts/{migration_id}/report" in paths
    assert "/api/v1/sources/{source_id}/artifacts/{migration_id}/workflows" in paths
    assert "/api/v1/workflows" in paths
    assert "/api/v1/workflows/{workflow_id}" in paths
    assert "/api/v1/workflows/{workflow_id}/approvals" in paths
    assert "/api/v1/apply" not in paths
    assert "/api/v1/reset" not in paths
    assert "/api/v1/execute" not in paths


def test_local_frontend_origin_is_allowed() -> None:
    client = TestClient(create_app(_settings()))
    response = client.get("/api/v1/health", headers={"Origin": "http://localhost:5173"})

    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
