"""Database URL guards. These tests do not connect to PostgreSQL."""

import pytest
from app.core.config import (
    Settings,
    UnsafeDatabaseConfigurationError,
    require_app_migration_database,
    resolve_app_database_url,
)


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_database_url": "postgresql+psycopg://app:local@127.0.0.1:5432/schemapilot",
        "sandbox_database_url": "postgresql+psycopg://sandbox:local@127.0.0.1:5433/schemapilot_sandbox",
        "target_database_url": None,
        "target_execution_enabled": False,
        "allow_app_migrations": False,
    }
    values.update(overrides)
    return Settings.model_construct(**values)


def test_target_execution_defaults_off(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "SCHEMAPILOT_TARGET_EXECUTION_ENABLED",
        "SCHEMAPILOT_APP_DATABASE_URL",
        "SCHEMAPILOT_ALLOW_APP_MIGRATIONS",
    ):
        monkeypatch.delenv(key, raising=False)

    settings = Settings(_env_file=None)
    assert settings.target_execution_enabled is False
    assert settings.allow_app_migrations is False


def test_missing_app_database_is_refused() -> None:
    with pytest.raises(UnsafeDatabaseConfigurationError, match="unspecified"):
        resolve_app_database_url(_settings(app_database_url=None))


def test_app_database_cannot_be_the_target() -> None:
    shared = "postgresql+psycopg://shared:local@127.0.0.1:5432/production"
    with pytest.raises(UnsafeDatabaseConfigurationError, match="target"):
        resolve_app_database_url(_settings(app_database_url=shared, target_database_url=shared))


def test_app_database_cannot_be_the_sandbox() -> None:
    shared = "postgresql+psycopg://shared:local@127.0.0.1:5433/schemapilot_sandbox"
    with pytest.raises(UnsafeDatabaseConfigurationError, match="sandbox"):
        resolve_app_database_url(_settings(app_database_url=shared, sandbox_database_url=shared))


def test_migrations_require_explicit_opt_in() -> None:
    with pytest.raises(UnsafeDatabaseConfigurationError, match="ALLOW_APP_MIGRATIONS"):
        require_app_migration_database(_settings())


def test_migrations_accept_a_distinct_app_database() -> None:
    settings = _settings(allow_app_migrations=True)
    assert resolve_app_database_url(settings) == settings.app_database_url
    assert require_app_migration_database(settings) == settings.app_database_url
