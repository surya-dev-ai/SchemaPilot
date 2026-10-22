"""On-demand SQLAlchemy engines. Nothing here connects at import or application startup."""

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import (
    Settings,
    require_demo_database,
    require_sandbox_database,
    resolve_app_database_url,
)


def create_app_engine(settings: Settings) -> Engine:
    """Create an engine for the application metadata database.

    Callers must opt in. This function does not create tables or run Alembic.
    """

    url = resolve_app_database_url(settings)
    return create_engine(url, pool_pre_ping=True)


def create_demo_engine(settings: Settings) -> Engine:
    """Create an engine for the disposable bookstore demo.

    Callers must opt in. This function does not connect, create tables, or run Alembic.
    Demo initialization and reset use this engine. Schema inspection does not.
    """

    url = require_demo_database(settings)
    return create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 5})


def create_bookstore_source_engine(settings: Settings) -> Engine:
    """Create a short-lived read-only engine for bookstore schema inspection.

    The URL is the configured disposable demo database after the same isolation
    checks as demo setup. Credentials stay in ``SCHEMAPILOT_DEMO_DATABASE_URL``
    and are not copied into API responses. PostgreSQL is opened with
    ``default_transaction_read_only=on``. Callers must dispose the engine when
    the snapshot is finished. This engine is not used to initialize or reset
    the demo.
    """

    url = require_demo_database(settings)
    return create_engine(
        url,
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": 5,
            "options": "-c default_transaction_read_only=on",
        },
    )


def create_sandbox_engine(settings: Settings) -> Engine:
    """Create an engine for the disposable sandbox database.

    Callers must opt in. This function does not connect, copy the source, or
    run a migration. It refuses source, application, and target URLs.
    """

    url = require_sandbox_database(settings)
    return create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 5})


def create_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def assert_startup_will_not_migrate(settings: Settings) -> None:
    """Document the startup boundary. This function deliberately does not connect or migrate.

    ``settings`` is accepted so callers pass the active configuration into the
    startup path. Phase 1 has no target-execution route.
    """

    del settings
