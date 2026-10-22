"""Shared fixtures. The bookstore fixture resets only the disposable demo database."""

import pytest
from app.core.config import (
    Settings,
    UnsafeDatabaseConfigurationError,
    require_demo_database,
    require_demo_reset,
)
from app.demo.bookstore import reset_demo
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError


@pytest.fixture
def seeded_demo() -> Settings:
    settings = Settings(_env_file=".env")
    try:
        require_demo_reset(settings, confirm=True)
        url = require_demo_database(settings)
    except UnsafeDatabaseConfigurationError as exc:
        pytest.skip(
            "Bookstore integration test not run. "
            f"{exc} Start the disposable demo-db service before running these tests."
        )
    engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 3})
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except OperationalError:
        pytest.skip(
            "Bookstore integration test not run. "
            "The disposable demo PostgreSQL service is not reachable."
        )
    finally:
        engine.dispose()
    reset_demo(settings, confirm=True)
    return settings
