"""Configured database sources. Request bodies cannot supply connection URLs."""

from app.core.config import (
    DEMO_DATABASE_NAME,
    Settings,
    UnsafeDatabaseConfigurationError,
    require_demo_database,
)
from app.schemas.domain import SourceListResponse, SourceSummary

BOOKSTORE_SOURCE_ID = "bookstore-demo"
BOOKSTORE_SCHEMA_NAME = "bookstore"


class SourceNotFoundError(LookupError):
    """Raised when the path does not name a known source."""


class SourceNotConfiguredError(RuntimeError):
    """Raised when the bookstore demo is not selected by configuration."""


class SourceUnavailableError(RuntimeError):
    """Raised when the selected source cannot be contacted."""


class SourceNotReadOnlyError(RuntimeError):
    """Raised when the inspection session is not read-only."""


class UnexpectedSourceDatabaseError(RuntimeError):
    """Raised when the connected database is not the disposable bookstore database."""


def list_sources(settings: Settings) -> SourceListResponse:
    """Return the fixed source catalog without opening a database connection."""

    return SourceListResponse(
        sources=[
            SourceSummary(
                id=BOOKSTORE_SOURCE_ID,
                kind="demo",
                display_name="Bookstore demo",
                database_name=DEMO_DATABASE_NAME,
                schema_name=BOOKSTORE_SCHEMA_NAME,
                configured=bookstore_source_configured(settings),
                access="read_only",
            )
        ]
    )


def bookstore_source_configured(settings: Settings) -> bool:
    try:
        require_demo_database(settings)
    except UnsafeDatabaseConfigurationError:
        return False
    return True


def require_bookstore_source(settings: Settings, source_id: str) -> None:
    if source_id != BOOKSTORE_SOURCE_ID:
        raise SourceNotFoundError
    if not bookstore_source_configured(settings):
        raise SourceNotConfiguredError
