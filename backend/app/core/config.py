"""Environment-backed settings. Defaults keep target execution off."""

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine.url import make_url

DEMO_DATABASE_NAME = "schemapilot_bookstore"
DEMO_ENVIRONMENT_DISPOSABLE = "disposable"
SANDBOX_DATABASE_NAME = "schemapilot_sandbox"
SANDBOX_DATABASE_USER = "schemapilot_sandbox"


class Settings(BaseSettings):
    """Runtime configuration loaded from the environment and an optional .env file."""

    app_name: str = "SchemaPilot"
    api_v1_prefix: str = "/api/v1"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    app_database_url: str | None = None
    sandbox_database_url: str | None = None
    target_database_url: str | None = None
    demo_database_url: str | None = None
    demo_environment: str = ""
    allow_demo_reset: bool = False
    allow_sandbox_execution: bool = False
    target_execution_enabled: bool = False
    allow_app_migrations: bool = False
    # Computed from auth_required and complete OIDC configuration.
    authentication_available: bool = False
    auth_required: bool = False
    oidc_metadata_url: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: str | None = None
    oidc_redirect_uri: str | None = None
    auth_frontend_url: str = "http://127.0.0.1:5175"
    auth_session_secret: str | None = None
    auth_cookie_secure: bool = True
    auth_role_claim: str = "roles"
    auth_group_claim: str = "groups"
    auth_team_groups: str = ""
    auth_admin_roles: str = "admin"
    auth_engineer_roles: str = "engineer"
    auth_approver_roles: str = "approver"
    auth_viewer_roles: str = "viewer"
    # Optional LLM assist. Credentials stay server-side; defaults keep LLM off.
    llm_enabled: bool = False
    llm_api_key: str | None = None
    llm_api_base: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_timeout_seconds: float = 20.0
    llm_fallback_to_deterministic: bool = True
    llm_provider: str = "openai_compatible"

    model_config = SettingsConfigDict(
        env_prefix="SCHEMAPILOT_",
        env_file=".env",
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_auth_configuration(self) -> "Settings":
        oidc_values = (
            self.oidc_metadata_url,
            self.oidc_client_id,
            self.oidc_client_secret,
            self.oidc_redirect_uri,
            self.auth_session_secret,
        )
        configured = all(value and value.strip() for value in oidc_values)
        if self.auth_required and not configured:
            raise ValueError(
                "OIDC auth requires metadata URL, client ID/secret, redirect URI, "
                "and a session secret."
            )
        if self.auth_required and self.auth_session_secret and len(self.auth_session_secret) < 32:
            raise ValueError("SCHEMAPILOT_AUTH_SESSION_SECRET must be at least 32 characters.")
        self.authentication_available = bool(self.auth_required and configured)
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    def database_configured(self, url: str | None) -> bool:
        return bool(url and url.strip())

    def llm_configured(self) -> bool:
        return bool(self.llm_enabled and self.llm_api_key and str(self.llm_api_key).strip())


class UnsafeDatabaseConfigurationError(RuntimeError):
    """Raised when a database URL would target an unspecified or protected database."""


def resolve_app_database_url(settings: Settings) -> str:
    """Return the application database URL after isolation checks.

    The URL must be set explicitly. It must be different from the sandbox URL
    and from any configured target URL.
    """

    app_url = (settings.app_database_url or "").strip()
    sandbox_url = (settings.sandbox_database_url or "").strip()
    target_url = (settings.target_database_url or "").strip()

    if not app_url:
        raise UnsafeDatabaseConfigurationError(
            "SCHEMAPILOT_APP_DATABASE_URL is required. Refusing to use an unspecified database."
        )
    if target_url and app_url == target_url:
        raise UnsafeDatabaseConfigurationError(
            "Refusing to use the target database as the application database."
        )
    if sandbox_url and app_url == sandbox_url:
        raise UnsafeDatabaseConfigurationError(
            "Refusing to use the sandbox database as the application database."
        )
    demo_url = _configured_url(settings, "demo_database_url")
    if demo_url and app_url == demo_url:
        raise UnsafeDatabaseConfigurationError(
            "Refusing to use the demo database as the application database."
        )
    return app_url


def _configured_url(settings: Settings, field_name: str) -> str:
    value = getattr(settings, field_name, None)
    if value is None:
        return ""
    return str(value).strip()


def require_demo_database(settings: Settings) -> str:
    """Return the disposable bookstore URL, or refuse to use any other database."""

    demo_url = _configured_url(settings, "demo_database_url")
    app_url = _configured_url(settings, "app_database_url")
    sandbox_url = _configured_url(settings, "sandbox_database_url")
    target_url = _configured_url(settings, "target_database_url")
    environment = _configured_url(settings, "demo_environment")

    if not demo_url:
        raise UnsafeDatabaseConfigurationError(
            "SCHEMAPILOT_DEMO_DATABASE_URL is required. "
            "Refusing to initialize an unspecified database."
        )
    if environment != DEMO_ENVIRONMENT_DISPOSABLE:
        raise UnsafeDatabaseConfigurationError(
            "Refusing to touch the demo database unless SCHEMAPILOT_DEMO_ENVIRONMENT=disposable."
        )
    if target_url and demo_url == target_url:
        raise UnsafeDatabaseConfigurationError(
            "Refusing to initialize the configured target database."
        )
    if app_url and demo_url == app_url:
        raise UnsafeDatabaseConfigurationError(
            "Refusing to use the application database as the bookstore demo."
        )
    if sandbox_url and demo_url == sandbox_url:
        raise UnsafeDatabaseConfigurationError(
            "Refusing to use the sandbox database as the bookstore demo."
        )
    try:
        database_name = make_url(demo_url).database
    except Exception as exc:
        raise UnsafeDatabaseConfigurationError("Demo database URL is invalid.") from exc
    if database_name != DEMO_DATABASE_NAME:
        raise UnsafeDatabaseConfigurationError(
            "Refusing to initialize a database that is not schemapilot_bookstore."
        )
    return demo_url


def require_demo_reset(settings: Settings, *, confirm: bool) -> str:
    """Return the demo URL only when a destructive reset was explicitly selected."""

    if not confirm:
        raise UnsafeDatabaseConfigurationError(
            "Refusing to reset without an explicit confirmation that the "
            "disposable demo schema will be dropped."
        )
    demo_url = require_demo_database(settings)
    if not getattr(settings, "allow_demo_reset", False):
        raise UnsafeDatabaseConfigurationError(
            "Refusing to reset the demo database. Set SCHEMAPILOT_ALLOW_DEMO_RESET=true "
            "only for the disposable bookstore database."
        )
    return demo_url


def require_sandbox_database(settings: Settings) -> str:
    """Return the sandbox URL only when it is the dedicated sandbox database."""

    sandbox_url = _configured_url(settings, "sandbox_database_url")
    app_url = _configured_url(settings, "app_database_url")
    demo_url = _configured_url(settings, "demo_database_url")
    target_url = _configured_url(settings, "target_database_url")
    if not sandbox_url:
        raise UnsafeDatabaseConfigurationError(
            "SCHEMAPILOT_SANDBOX_DATABASE_URL is required. "
            "Refusing to use an unspecified database."
        )
    if app_url and sandbox_url == app_url:
        raise UnsafeDatabaseConfigurationError(
            "Refusing to use the application database as the sandbox."
        )
    if demo_url and sandbox_url == demo_url:
        raise UnsafeDatabaseConfigurationError(
            "Refusing to use the bookstore source database as the sandbox."
        )
    if target_url and sandbox_url == target_url:
        raise UnsafeDatabaseConfigurationError(
            "Refusing to use the target database as the sandbox."
        )
    try:
        parsed = make_url(sandbox_url)
    except Exception as exc:
        raise UnsafeDatabaseConfigurationError("Sandbox database URL is invalid.") from exc
    if parsed.database != SANDBOX_DATABASE_NAME:
        raise UnsafeDatabaseConfigurationError(
            "Refusing to use a database that is not schemapilot_sandbox."
        )
    if parsed.username != SANDBOX_DATABASE_USER:
        raise UnsafeDatabaseConfigurationError(
            "Refusing to use sandbox credentials other than schemapilot_sandbox."
        )
    return sandbox_url


def require_sandbox_execution(settings: Settings) -> str:
    """Return the sandbox URL only when sandbox execution was explicitly enabled."""

    sandbox_url = require_sandbox_database(settings)
    if not getattr(settings, "allow_sandbox_execution", False):
        raise UnsafeDatabaseConfigurationError(
            "Refusing to run the sandbox. Set SCHEMAPILOT_ALLOW_SANDBOX_EXECUTION=true "
            "only for the disposable schemapilot_sandbox database."
        )
    return sandbox_url


def require_app_migration_database(settings: Settings) -> str:
    """Return the application database URL or refuse to migrate."""

    if not settings.allow_app_migrations:
        raise UnsafeDatabaseConfigurationError(
            "Refusing to run Alembic. Set SCHEMAPILOT_ALLOW_APP_MIGRATIONS=true "
            "only when SCHEMAPILOT_APP_DATABASE_URL points at the local application database."
        )
    return resolve_app_database_url(settings)


@lru_cache
def get_settings() -> Settings:
    return Settings()


def clear_settings_cache() -> None:
    get_settings.cache_clear()
