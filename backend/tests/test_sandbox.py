"""Sandbox unit tests. These tests do not open PostgreSQL and do not prove a live upgrade."""

import hashlib
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.core.config import (
    Settings,
    UnsafeDatabaseConfigurationError,
    require_sandbox_database,
    require_sandbox_execution,
)
from app.db import session as session_module
from app.main import create_app
from app.schemas.artifacts import MigrationArtifact, OperationReversibility
from app.schemas.domain import ColumnSnapshot, SchemaSnapshot, TableSnapshot
from app.schemas.rollback import SnapshotRecoveryReport
from app.schemas.sandbox import SandboxRun, SandboxRunRequest
from app.services.migration_generator import canonical_artifact_json, generate_migration
from app.services.planner import propose_migration
from app.services.risk_engine import assess_risk
from app.services.sandbox_manager import (
    SandboxRejected,
    SandboxUnavailable,
    _assert_identity,
    load_verified_artifact,
    run_sandbox,
)
from app.services.validator import assert_alembic_matches, parse_upgrade_sql
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

SANDBOX_URL = (
    "postgresql+psycopg://schemapilot_sandbox:change_me_local_sandbox"
    "@127.0.0.1:5433/schemapilot_sandbox"
)
VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"


def _column(table: str, name: str, *, nullable: bool = False, position: int = 1) -> ColumnSnapshot:
    return ColumnSnapshot(
        id=f"bookstore.{table}.{name}",
        name=name,
        ordinal_position=position,
        data_type="text",
        udt_name="text",
        nullable=nullable,
        identity="none",
        generated="never",
    )


def _snapshot() -> SchemaSnapshot:
    return SchemaSnapshot(
        source_id="bookstore-demo",
        database_name="schemapilot_bookstore",
        schema_name="bookstore",
        fingerprint="fingerprint-1",
        tables=[
            TableSnapshot(
                id="bookstore.users",
                schema_name="bookstore",
                name="users",
                columns=[
                    _column("users", "id"),
                    _column("users", "email", position=2),
                    _column("users", "display_name", nullable=True, position=3),
                ],
                constraints=[],
                indexes=[],
            ),
            TableSnapshot(
                id="bookstore.orders",
                schema_name="bookstore",
                name="orders",
                columns=[
                    _column("orders", "id"),
                    _column("orders", "user_id", position=2),
                    _column("orders", "status", position=3),
                ],
                constraints=[],
                indexes=[],
            ),
        ],
        dependencies=[],
    )


def _artifact(snapshot: SchemaSnapshot, request: str, directory: Path) -> MigrationArtifact:
    proposal = propose_migration(snapshot, request)
    assessment = assess_risk(snapshot, proposal)
    return generate_migration(snapshot, proposal, assessment, directory)


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_name": "SchemaPilot",
        "api_v1_prefix": "/api/v1",
        "cors_origins": "http://localhost:5173",
        "app_database_url": None,
        "sandbox_database_url": None,
        "target_database_url": None,
        "demo_database_url": None,
        "demo_environment": "",
        "allow_demo_reset": False,
        "allow_sandbox_execution": False,
        "target_execution_enabled": False,
        "allow_app_migrations": False,
    }
    values.update(overrides)
    return Settings.model_construct(**values)  # type: ignore[arg-type]


def _sign(artifact: MigrationArtifact) -> MigrationArtifact:
    digest = hashlib.sha256(canonical_artifact_json(artifact).encode("ascii")).hexdigest()
    return artifact.model_copy(update={"checksum": f"sha256:{digest}"})


def _write(artifact: MigrationArtifact, directory: Path) -> MigrationArtifact:
    signed = _sign(artifact)
    (directory / f"{signed.migration_id}.json").write_text(
        signed.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (directory / f"{signed.migration_id}.py").write_text(
        signed.alembic_source,
        encoding="utf-8",
        newline="\n",
    )
    return signed


class _Scalar:
    def __init__(self, value: str) -> None:
        self.value = value

    def scalar_one(self) -> str:
        return self.value


class _Connection:
    def __init__(self, database: str, user: str) -> None:
        self.values = [database, user]

    def execute(self, _statement: object) -> _Scalar:
        return _Scalar(self.values.pop(0))


def test_sandbox_url_must_be_the_dedicated_database() -> None:
    enabled = _settings(sandbox_database_url=SANDBOX_URL, allow_sandbox_execution=True)
    assert require_sandbox_database(enabled) == SANDBOX_URL
    assert require_sandbox_execution(enabled) == SANDBOX_URL
    demo = (
        "postgresql+psycopg://schemapilot_demo:change_me_local_demo"
        "@127.0.0.1:5434/schemapilot_bookstore"
    )
    wrong_name = SANDBOX_URL.replace("/schemapilot_sandbox", "/schemapilot")
    with pytest.raises(UnsafeDatabaseConfigurationError):
        require_sandbox_database(_settings())
    with pytest.raises(UnsafeDatabaseConfigurationError):
        require_sandbox_database(_settings(sandbox_database_url=demo))
    with pytest.raises(UnsafeDatabaseConfigurationError):
        require_sandbox_database(
            _settings(sandbox_database_url=SANDBOX_URL, demo_database_url=SANDBOX_URL)
        )
    with pytest.raises(UnsafeDatabaseConfigurationError):
        require_sandbox_database(
            _settings(sandbox_database_url=SANDBOX_URL, app_database_url=SANDBOX_URL)
        )
    with pytest.raises(UnsafeDatabaseConfigurationError):
        require_sandbox_database(
            _settings(sandbox_database_url=SANDBOX_URL, target_database_url=SANDBOX_URL)
        )
    wrong_user = SANDBOX_URL.replace("schemapilot_sandbox:", "schemapilot_demo:")
    with pytest.raises(UnsafeDatabaseConfigurationError):
        require_sandbox_database(_settings(sandbox_database_url=wrong_user))
    with pytest.raises(UnsafeDatabaseConfigurationError):
        require_sandbox_database(_settings(sandbox_database_url=wrong_name))
    with pytest.raises(UnsafeDatabaseConfigurationError):
        require_sandbox_execution(_settings(sandbox_database_url=SANDBOX_URL))


def test_connection_identity_is_required_before_changes() -> None:
    _assert_identity(_Connection("schemapilot_sandbox", "schemapilot_sandbox"))
    with pytest.raises(SandboxRejected) as exc:
        _assert_identity(_Connection("schemapilot_bookstore", "schemapilot_sandbox"))
    assert exc.value.code == "sandbox_identity_rejected"
    with pytest.raises(SandboxRejected):
        _assert_identity(_Connection("schemapilot_sandbox", "schemapilot_demo"))


@pytest.mark.parametrize(
    "request_text",
    [
        "Add a nullable text column called nickname to users",
        "Add an index on the user_id column of orders",
        "Rename the status column on orders to order_status",
        "Rename table users to customers",
        "Drop the status column from orders",
    ],
)
def test_generated_operations_stay_eligible(request_text: str, tmp_path: Path) -> None:
    artifact = _artifact(_snapshot(), request_text, tmp_path)
    loaded = load_verified_artifact(tmp_path, artifact.migration_id)
    statements = parse_upgrade_sql(loaded.sql_preview)
    assert_alembic_matches(loaded, statements)
    assert loaded.applied is False
    assert "DROP TABLE" not in loaded.sql_preview


def test_tampered_sql_module_and_id_are_rejected(tmp_path: Path) -> None:
    artifact = _artifact(
        _snapshot(),
        "Add a nullable text column called nickname to users",
        tmp_path,
    )
    json_path = tmp_path / f"{artifact.migration_id}.json"
    module_path = tmp_path / f"{artifact.migration_id}.py"
    original = json_path.read_text(encoding="utf-8")
    tampered = original.replace("TEXT NULL", "TEXT NOT NULL")
    json_path.write_text(tampered, encoding="utf-8")
    with pytest.raises(SandboxRejected) as checksum_error:
        load_verified_artifact(tmp_path, artifact.migration_id)
    json_path.write_text(original, encoding="utf-8")
    edited = module_path.read_text(encoding="utf-8") + "\n# edited\n"
    module_path.write_text(edited, encoding="utf-8")
    with pytest.raises(SandboxRejected) as module_error:
        load_verified_artifact(tmp_path, artifact.migration_id)
    with pytest.raises(SandboxRejected) as id_error:
        load_verified_artifact(tmp_path, "spdeadbeef0000")
    assert checksum_error.value.code == "checksum_mismatch"
    assert module_error.value.code == "alembic_mismatch"
    assert id_error.value.code == "artifact_not_found"


def test_blocked_sql_and_unresolved_not_null_are_rejected(tmp_path: Path) -> None:
    blocked = _manual_artifact(
        'ALTER TABLE "bookstore"."orders" DROP TABLE "orders";',
        "    op.drop_table(\"orders\", schema=\"bookstore\")\n",
    )
    not_null = _manual_artifact(
        'ALTER TABLE "bookstore"."users" ADD COLUMN "nickname" TEXT NULL;',
        "    op.add_column(\n        \"users\",\n"
        "        sa.Column(\"nickname\", sa.Text(), nullable=False),\n"
        "        schema=\"bookstore\",\n    )\n",
    )
    _write(blocked, tmp_path)
    with pytest.raises(SandboxRejected) as blocked_error:
        load_verified_artifact(tmp_path, blocked.migration_id)
    other = tmp_path / "other"
    other.mkdir()
    _write(not_null, other)
    with pytest.raises(SandboxRejected) as pending_error:
        load_verified_artifact(other, not_null.migration_id)
    assert blocked_error.value.code == "policy_blocked"
    assert pending_error.value.code == "data_check_not_run"


def test_unavailable_database_is_not_a_passed_upgrade(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = _artifact(
        _snapshot(),
        "Add a nullable text column called nickname to users",
        tmp_path,
    )

    class _Engine:
        def connect(self) -> None:
            raise OperationalError("SELECT 1", {}, Exception("postgresql://secret@db/prod"))

        def dispose(self) -> None:
            return None

    monkeypatch.setattr(session_module, "create_engine", lambda *_args, **_kwargs: _Engine())
    settings = _settings(sandbox_database_url=SANDBOX_URL, allow_sandbox_execution=True)
    with pytest.raises(SandboxUnavailable) as exc:
        run_sandbox(settings, artifact.migration_id, directory=tmp_path)
    assert "secret" not in str(exc.value)
    assert "postgresql" not in str(exc.value)
    assert exc.value.__cause__ is None


def test_sandbox_modules_do_not_use_source_engines_or_revision_history() -> None:
    root = Path(__file__).resolve().parents[1] / "app" / "services"
    for name in ("sandbox_manager.py", "validator.py"):
        source = (root / name).read_text(encoding="utf-8")
        assert ".comment" not in source
        assert "create_demo_engine" not in source
        assert "create_bookstore_source_engine" not in source
        assert "alembic/versions" not in source
    assert VERSIONS.is_dir()


def test_sandbox_route_rejects_bad_requests_without_connecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_called(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("sandbox route opened a database")

    monkeypatch.setattr(session_module, "create_engine", fail_if_called)
    monkeypatch.setattr(session_module, "create_demo_engine", fail_if_called)
    monkeypatch.setattr(session_module, "create_bookstore_source_engine", fail_if_called)
    monkeypatch.setattr(session_module, "create_sandbox_engine", fail_if_called)
    client = TestClient(create_app(_settings()))
    unknown = client.post(
        "/api/v1/sources/other/artifacts/sp0123456789ab/sandbox",
        json={"confirm": True},
    )
    unconfirmed = client.post(
        "/api/v1/sources/bookstore-demo/artifacts/sp0123456789ab/sandbox",
        json={"confirm": False},
    )
    extra = client.post(
        "/api/v1/sources/bookstore-demo/artifacts/sp0123456789ab/sandbox",
        json={"confirm": True, "database_url": "postgresql://secret@db/prod"},
    )
    assert unknown.status_code == 404
    assert unknown.json()["detail"]["error"] == "unknown_source"
    assert unconfirmed.status_code == 409
    assert unconfirmed.json()["detail"]["error"] == "sandbox_not_confirmed"
    assert extra.status_code == 422
    assert "secret" not in extra.text


def test_sandbox_route_checkpoints_before_running_the_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import sandbox as sandbox_api

    artifact = _artifact(
        _snapshot(),
        "Add a nullable text column called nickname to users",
        tmp_path,
    )
    events: list[str] = []
    checkpoint = SnapshotRecoveryReport(
        checkpoint_id="a" * 32,
        backup_status="verified",
        restore_status="not_attempted",
        baseline_schema_fingerprint="original-schema",
        restored_schema_fingerprint="original-schema",
        baseline_data_fingerprint="original-data",
        restored_data_fingerprint="original-data",
        schema_match=True,
        data_match=True,
        checkpoint_retained=True,
    )

    @contextmanager
    def fake_lifecycle_lock(_settings):
        yield

    def save_session(session) -> None:
        events.append("save-session")
        assert session.state == "ready"
        assert session.checkpoint.checkpoint_id == checkpoint.checkpoint_id

    def fake_run(*_args, **_kwargs):
        events.append("run-migration")
        return SandboxRun(
            migration_id=artifact.migration_id,
            source_id=artifact.source_id,
            schema_fingerprint=artifact.schema_fingerprint,
            artifact_checksum=artifact.checksum,
            sandbox_database="schemapilot_sandbox",
            sandbox_user="schemapilot_sandbox",
            postgres_version="16.0",
            started_at="2026-11-01T00:00:00+00:00",
            finished_at="2026-11-01T00:00:01+00:00",
            result="passed",
            upgrade_applied=True,
            restored=False,
            cleaned_up=False,
            checks=[],
            observed_tables=["users"],
        )

    monkeypatch.setattr(sandbox_api, "ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(sandbox_api, "load_verified_artifact", lambda *_args: artifact)
    monkeypatch.setattr(sandbox_api, "sandbox_lifecycle_lock", fake_lifecycle_lock)
    monkeypatch.setattr(sandbox_api, "assert_no_active_checkpoint_session", lambda: None)
    monkeypatch.setattr(sandbox_api, "inspect_sandbox", lambda *_args: _snapshot())
    monkeypatch.setattr(sandbox_api, "read_baseline_evidence", lambda *_args: None)

    def create_checkpoint(*_args, **_kwargs):
        events.append("capture-checkpoint")
        return checkpoint

    monkeypatch.setattr(sandbox_api, "create_verified_checkpoint", create_checkpoint)
    monkeypatch.setattr(sandbox_api, "save_checkpoint_session", save_session)
    monkeypatch.setattr(sandbox_api, "save_validation_evidence", lambda *_args: None)
    monkeypatch.setattr(sandbox_api, "run_sandbox", fake_run)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=_settings())))

    result = sandbox_api.run_artifact_in_sandbox(
        "bookstore-demo",
        artifact.migration_id,
        SandboxRunRequest(confirm=True),
        request,
    )
    assert events == ["capture-checkpoint", "save-session", "run-migration"]
    assert result.pre_migration_snapshot_verified is True
    assert result.snapshot_session_id is not None


def test_checkpoint_session_status_discovers_only_matching_active_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import sandbox as sandbox_api
    from app.services import sandbox_checkpoint_store as checkpoint_store

    artifact = _artifact(
        _snapshot(),
        "Add a nullable text column called nickname to users",
        tmp_path,
    )
    checkpoint = SnapshotRecoveryReport(
        checkpoint_id="a" * 32,
        backup_status="verified",
        restore_status="not_attempted",
        baseline_schema_fingerprint="original-schema",
        restored_schema_fingerprint="original-schema",
        baseline_data_fingerprint="original-data",
        restored_data_fingerprint="original-data",
        schema_match=True,
        data_match=True,
        checkpoint_retained=True,
    )
    session = checkpoint_store.SandboxCheckpointSession(
        session_id="b" * 32,
        migration_id=artifact.migration_id,
        artifact_checksum=artifact.checksum,
        state="recovery_required",
        checkpoint=checkpoint,
        error="Restore verification is incomplete.",
    )
    sessions_dir = tmp_path / "sessions"
    checkpoint_store.save_checkpoint_session(session, directory=sessions_dir)
    monkeypatch.setattr(sandbox_api, "ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(checkpoint_store, "CHECKPOINT_SESSION_DIR", sessions_dir)

    status = sandbox_api.get_sandbox_checkpoint_session("bookstore-demo")

    assert status.active is True
    assert status.snapshot_session_id == session.session_id
    assert status.state == "recovery_required"
    assert status.checkpoint_verified is True
    assert status.restore_status == "not_attempted"
    assert "checkpoint_id" not in status.model_dump()


def test_sandbox_route_hides_unavailable_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from contextlib import contextmanager

    from app.api import sandbox as sandbox_api

    artifact = _artifact(
        _snapshot(),
        "Add a nullable text column called nickname to users",
        tmp_path,
    )

    def unavailable(*_args: object, **_kwargs: object) -> None:
        raise SandboxUnavailable

    @contextmanager
    def fake_lock(_settings):
        yield

    checkpoint = SnapshotRecoveryReport(
        checkpoint_id="a" * 32,
        backup_status="verified",
        restore_status="not_attempted",
        baseline_schema_fingerprint="original",
        baseline_data_fingerprint="original-data",
    )
    monkeypatch.setattr(sandbox_api, "ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(sandbox_api, "load_verified_artifact", lambda *_args: artifact)
    monkeypatch.setattr(sandbox_api, "sandbox_lifecycle_lock", fake_lock)
    monkeypatch.setattr(sandbox_api, "assert_no_active_checkpoint_session", lambda: None)
    monkeypatch.setattr(sandbox_api, "inspect_sandbox", lambda *_args: _snapshot())
    monkeypatch.setattr(sandbox_api, "read_baseline_evidence", lambda *_args: None)
    monkeypatch.setattr(
        sandbox_api,
        "create_verified_checkpoint",
        lambda *_args, **_kwargs: checkpoint,
    )
    monkeypatch.setattr(sandbox_api, "save_checkpoint_session", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        sandbox_api,
        "transition_checkpoint_session",
        lambda session, **kwargs: session.model_copy(update=kwargs),
    )
    monkeypatch.setattr(
        sandbox_api,
        "restore_verified_checkpoint",
        lambda *_args, **_kwargs: checkpoint,
    )
    monkeypatch.setattr(sandbox_api, "run_sandbox", unavailable)
    client = TestClient(
        create_app(_settings(allow_sandbox_execution=True, sandbox_database_url=SANDBOX_URL))
    )
    response = client.post(
        "/api/v1/sources/bookstore-demo/artifacts/sp0123456789ab/sandbox",
        json={"confirm": True},
    )
    assert response.status_code == 503
    assert response.json()["detail"]["error"] == "sandbox_unavailable"
    assert "postgresql" not in response.text


def _manual_artifact(sql_preview: str, upgrade: str) -> MigrationArtifact:
    source = (
        '"""manual artifact\n"""\n'
        "from alembic import op\n"
        "import sqlalchemy as sa\n\n"
        'revision = "sp0123456789ab"\n'
        "down_revision = None\n"
        "branch_labels = None\n"
        "depends_on = None\n"
        "schemapilot_applied = False\n\n\n"
        "def upgrade() -> None:\n"
        f"{upgrade}\n\n"
        "def downgrade() -> None:\n"
        "    pass\n"
    )
    return MigrationArtifact(
        migration_id="sp0123456789ab",
        source_id="bookstore-demo",
        schema_name="bookstore",
        schema_fingerprint="fingerprint-1",
        summary="manual",
        status="generated",
        applied=False,
        operation_ids=["op-1"],
        sql_preview=sql_preview,
        downgrade_sql="",
        alembic_source=source,
        reversibility="reversible",
        operation_reversibility=[
            OperationReversibility(
                operation_id="op-1",
                kind="add_column",
                reversibility="reversible",
                upgrade_effect="manual",
                downgrade_effect="manual",
                data_loss_on_downgrade=False,
            )
        ],
        checksum="",
        location="",
    )
