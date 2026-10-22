"""Live application-database workflow persistence.

Skipped when SCHEMAPILOT_APP_DATABASE_URL is unset or PostgreSQL is unreachable.
These tests create metadata tables with SQLAlchemy create_all for the app DB only.
They do not run Alembic and do not open the source or sandbox databases.
"""

from pathlib import Path

import pytest
from app.core.config import Settings, UnsafeDatabaseConfigurationError, resolve_app_database_url
from app.db.session import create_app_engine
from app.schemas.workflow import ApprovalCreateRequest
from app.services.workflow_store import (
    WorkflowStoreError,
    create_tables,
    get_workflow,
    list_workflows,
    persist_workflow,
    record_approval,
)
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from tests.test_workflow_store import _eligible_bundle

pytestmark = pytest.mark.integration


@pytest.fixture
def app_db_settings() -> Settings:
    settings = Settings(_env_file=".env")
    try:
        resolve_app_database_url(settings)
    except UnsafeDatabaseConfigurationError as exc:
        pytest.skip(
            "Application database integration test not run. "
            f"{exc} Start app-db and set SCHEMAPILOT_APP_DATABASE_URL."
        )
    engine = create_app_engine(settings)
    try:
        with engine.connect() as connection:
            current = connection.execute(text("SELECT current_database()")).scalar_one()
            if current != "schemapilot":
                pytest.skip(
                    "Application database integration test not run. "
                    "Connected database is not schemapilot."
                )
            connection.execute(text("SELECT 1"))
    except OperationalError:
        pytest.skip(
            "Application database integration test not run. "
            "The application PostgreSQL service is not reachable."
        )
    finally:
        engine.dispose()
    return settings


def test_live_app_database_persists_a_workflow(app_db_settings: Settings, tmp_path: Path) -> None:
    del tmp_path
    engine = create_app_engine(app_db_settings)
    try:
        create_tables(engine)
        proposal, assessment, report, rollback = _eligible_bundle()
        # Use a unique checksum so repeated local runs do not collide.
        unique = report.model_copy(
            update={"artifact_checksum": f"sha256:live-{Path(report.migration_id).name}-workflow"}
        )
        unique_rollback = rollback.model_copy(
            update={"artifact_checksum": unique.artifact_checksum}
        )
        unique_sandbox = unique.sandbox
        if unique_sandbox is not None:
            unique = unique.model_copy(
                update={
                    "sandbox": unique_sandbox.model_copy(
                        update={"artifact_checksum": unique.artifact_checksum}
                    )
                }
            )
        detail = persist_workflow(
            app_db_settings,
            proposal=proposal,
            assessment=assessment,
            report=unique,
            rollback=unique_rollback,
            engine=engine,
        )
        listed = list_workflows(app_db_settings, engine=engine)
        assert any(item.id == detail.id for item in listed.workflows)
        loaded = get_workflow(app_db_settings, detail.id, engine=engine)
        assert loaded.artifact_checksum == unique.artifact_checksum
        assert "://" not in loaded.model_dump_json()
        with pytest.raises(WorkflowStoreError) as unauth:
            record_approval(
                app_db_settings,
                detail.id,
                ApprovalCreateRequest(target_identity="staging-review-target", confirm=True),
                engine=engine,
            )
        assert unauth.value.code == "authentication_unavailable"
    finally:
        engine.dispose()
