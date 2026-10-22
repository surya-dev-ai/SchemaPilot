"""Demo safety tests. These tests do not connect to PostgreSQL."""

import pytest
from app.core.config import (
    Settings,
    UnsafeDatabaseConfigurationError,
    require_demo_database,
    require_demo_reset,
    resolve_app_database_url,
)
from app.demo.bookstore import USER_TABLE_COMMENT
from app.demo.cli import main
from app.demo.sql_script import read_sql_file, split_sql_script
from app.main import create_app
from fastapi.testclient import TestClient

DEMO_URL = "postgresql+psycopg://demo:local@127.0.0.1:5434/schemapilot_bookstore"
APP_URL = "postgresql+psycopg://app:local@127.0.0.1:5432/schemapilot"
SANDBOX_URL = "postgresql+psycopg://sandbox:local@127.0.0.1:5433/schemapilot_sandbox"
TARGET_URL = "postgresql+psycopg://target:local@127.0.0.1:5435/production"


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_name": "SchemaPilot",
        "api_v1_prefix": "/api/v1",
        "cors_origins": "http://localhost:5173,http://127.0.0.1:5173",
        "app_database_url": APP_URL,
        "sandbox_database_url": SANDBOX_URL,
        "target_database_url": None,
        "demo_database_url": DEMO_URL,
        "demo_environment": "disposable",
        "allow_demo_reset": False,
        "target_execution_enabled": False,
        "allow_app_migrations": False,
    }
    values.update(overrides)
    return Settings.model_construct(**values)


def _fail_if_called(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("demo command connected to a database")


def test_demo_url_is_required() -> None:
    with pytest.raises(UnsafeDatabaseConfigurationError, match="unspecified"):
        require_demo_database(_settings(demo_database_url=None))


def test_demo_environment_must_be_disposable() -> None:
    with pytest.raises(UnsafeDatabaseConfigurationError, match="disposable"):
        require_demo_database(_settings(demo_environment=""))


def test_demo_database_name_is_fixed() -> None:
    other = "postgresql+psycopg://demo:local@127.0.0.1:5434/postgres"
    with pytest.raises(UnsafeDatabaseConfigurationError, match="schemapilot_bookstore"):
        require_demo_database(_settings(demo_database_url=other))


def test_demo_url_cannot_match_target_app_or_sandbox() -> None:
    with pytest.raises(UnsafeDatabaseConfigurationError, match="target"):
        require_demo_database(
            _settings(demo_database_url=TARGET_URL, target_database_url=TARGET_URL)
        )
    with pytest.raises(UnsafeDatabaseConfigurationError, match="application"):
        require_demo_database(_settings(demo_database_url=APP_URL))
    with pytest.raises(UnsafeDatabaseConfigurationError, match="sandbox"):
        require_demo_database(_settings(demo_database_url=SANDBOX_URL))


def test_app_database_cannot_be_the_demo() -> None:
    with pytest.raises(UnsafeDatabaseConfigurationError, match="demo"):
        resolve_app_database_url(_settings(app_database_url=DEMO_URL, demo_database_url=DEMO_URL))


def test_reset_requires_explicit_confirmation_before_any_connection(monkeypatch) -> None:
    monkeypatch.setattr("app.demo.cli.get_settings", _fail_if_called)
    monkeypatch.setattr("app.db.session.create_engine", _fail_if_called)

    assert main(["reset"]) == 2


def test_reset_requires_the_allow_flag(monkeypatch) -> None:
    monkeypatch.setattr("app.db.session.create_engine", _fail_if_called)
    with pytest.raises(UnsafeDatabaseConfigurationError, match="ALLOW_DEMO_RESET"):
        require_demo_reset(_settings(allow_demo_reset=False), confirm=True)


def test_selected_demo_url_is_accepted() -> None:
    assert require_demo_database(_settings()) == DEMO_URL
    assert require_demo_reset(_settings(allow_demo_reset=True), confirm=True) == DEMO_URL


def test_init_does_not_connect_when_the_demo_is_not_selected(monkeypatch) -> None:
    monkeypatch.setattr("app.demo.cli.get_settings", lambda: _settings(demo_environment=""))
    monkeypatch.setattr("app.db.session.create_engine", _fail_if_called)

    assert main(["init"]) == 2


def test_application_startup_does_not_initialize_the_demo(monkeypatch) -> None:
    monkeypatch.setattr("app.demo.bookstore.initialize_demo", _fail_if_called)
    response = TestClient(create_app(_settings())).get("/api/v1/health")

    assert response.status_code == 200


def test_packaged_sql_contains_the_bookstore_contract() -> None:
    schema_statements = split_sql_script(read_sql_file("schema.sql"))
    seed_statements = split_sql_script(read_sql_file("seed.sql"))
    comment_statements = [
        statement
        for statement in schema_statements
        if statement.lstrip().upper().startswith("COMMENT")
    ]

    table_statements = [
        statement
        for statement in schema_statements
        if statement.lstrip().upper().startswith("CREATE TABLE")
    ]
    assert len(table_statements) == 4
    assert comment_statements == [
        "COMMENT ON TABLE bookstore.users IS '" + USER_TABLE_COMMENT + "'"
    ]
    assert all(not statement.lstrip().upper().startswith("DROP") for statement in schema_statements)
    assert all(not statement.lstrip().upper().startswith("DROP") for statement in seed_statements)
    seed_text = "\n".join(seed_statements)
    assert "mira@example.test" in seed_text
    assert "SKU-RARE-003" in seed_text
    assert "0, false" in seed_text
