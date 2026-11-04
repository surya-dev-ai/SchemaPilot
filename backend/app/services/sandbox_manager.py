"""Validate a verified artifact against the existing, identity-checked sandbox."""

import re
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import OperationalError

from app.core.config import (
    SANDBOX_DATABASE_NAME,
    SANDBOX_DATABASE_USER,
    Settings,
    require_sandbox_execution,
)
from app.db.session import create_sandbox_engine
from app.demo.sql_script import read_sql_file, split_sql_script
from app.schemas.artifacts import MigrationArtifact
from app.schemas.domain import SchemaSnapshot
from app.schemas.sandbox import SandboxCheck, SandboxRun
from app.services.migration_generator import ARTIFACTS_DIR, verify_artifact
from app.services.schema_inspector import assemble_snapshot, load_catalog
from app.services.validator import (
    ArtifactNotEligible,
    assert_alembic_matches,
    parse_upgrade_sql,
    validate_upgrade,
)

_MIGRATION_ID = re.compile(r"^sp[0-9a-f]{12}$")
_RESET = "DROP SCHEMA IF EXISTS bookstore CASCADE"
_BASELINE_TIMEOUT_MS = 15000


class SandboxRejected(Exception):
    """Raised before an upgrade when the artifact or sandbox identity is refused."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class SandboxUnavailable(Exception):
    """Raised when the sandbox database cannot be contacted. The message has no URL."""

    def __init__(self) -> None:
        super().__init__("Sandbox database is unavailable.")


def load_verified_artifact(directory: Path, migration_id: str) -> MigrationArtifact:
    """Load the canonical JSON and require the sibling module to match it."""

    if _MIGRATION_ID.fullmatch(migration_id) is None:
        raise SandboxRejected(
            "artifact_id_mismatch",
            "The artifact id does not match a generated migration id.",
        )
    json_path = directory / f"{migration_id}.json"
    module_path = directory / f"{migration_id}.py"
    if not json_path.is_file():
        raise SandboxRejected("artifact_not_found", "The artifact record was not found.")
    try:
        artifact = MigrationArtifact.model_validate_json(json_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise SandboxRejected("checksum_mismatch", "The artifact record is not valid.") from exc
    if artifact.migration_id != migration_id or artifact.source_id not in {
        "bookstore-demo",
        "sandbox",
    }:
        raise SandboxRejected(
            "artifact_id_mismatch",
            "The artifact record does not match the requested id or source.",
        )
    if artifact.schema_name != "bookstore" or not verify_artifact(artifact):
        raise SandboxRejected(
            "checksum_mismatch",
            "The artifact checksum does not match its canonical contents.",
        )
    if not module_path.is_file():
        raise SandboxRejected(
            "alembic_mismatch",
            "The Alembic module does not match the checksum-verified artifact.",
        )
    module_text = module_path.read_text(encoding="utf-8")
    if module_text != artifact.alembic_source:
        raise SandboxRejected(
            "alembic_mismatch",
            "The Alembic module does not match the checksum-verified artifact.",
        )
    try:
        statements = parse_upgrade_sql(artifact.sql_preview)
        assert_alembic_matches(artifact, statements)
    except ArtifactNotEligible as exc:
        raise SandboxRejected(exc.code, exc.message) from exc
    return artifact


def run_sandbox(
    settings: Settings,
    migration_id: str,
    *,
    directory: Path | None = None,
    statement_timeout_ms: int = 5000,
    _lifecycle_lock_held: bool = False,
) -> SandboxRun:
    """Checkpointing is handled by the API; validate and apply only inside sandbox."""

    if not _lifecycle_lock_held:
        from app.services.sandbox_snapshots import sandbox_lifecycle_lock

        try:
            with sandbox_lifecycle_lock(settings):
                return run_sandbox(
                    settings,
                    migration_id,
                    directory=directory,
                    statement_timeout_ms=statement_timeout_ms,
                    _lifecycle_lock_held=True,
                )
        except OperationalError:
            raise SandboxUnavailable from None

    started = _now()
    artifact = load_verified_artifact(directory or ARTIFACTS_DIR, migration_id)
    statements = parse_upgrade_sql(artifact.sql_preview)
    timeout_ms = _timeout(statement_timeout_ms)
    with _session(settings) as connection:
        _assert_identity(connection)
        version = str(connection.execute(text("SHOW server_version")).scalar_one())
        connection.commit()

        before = assemble_snapshot(
            load_catalog(connection),
            source_id=artifact.source_id,
            database_name=(
                SANDBOX_DATABASE_NAME
                if artifact.source_id == "sandbox"
                else "schemapilot_bookstore"
            ),
        )
        fingerprint = before.fingerprint
        baseline_counts = _row_counts(connection)
        connection.commit()
        if fingerprint != artifact.schema_fingerprint:
            return _finish(
                    artifact,
                    version=version,
                    started=started,
                    result="rejected",
                    upgrade_applied=False,
                    restored=False,
                    cleaned_up=False,
                    checks=[
                        _check("baseline_fingerprint", "failed", "The fingerprints differ."),
                        _check("upgrade", "not_run", "The artifact was not executed."),
                        _check(
                            "risk_row_checks",
                            "not_run",
                            "Unresolved risk row checks are not treated as passed.",
                        ),
                    ],
                    observed=_table_names(connection),
                    error="Artifact fingerprint does not match the sandbox baseline.",
                )
        try:
            with connection.begin():
                _set_timeout(connection, timeout_ms, local=True)
                for statement in statements:
                    connection.execute(text(statement.sql_text))
        except OperationalError as exc:
            return _upgrade_failure(connection, artifact, version, started, exc)
        except Exception as exc:
            return _upgrade_failure(connection, artifact, version, started, exc)
        checks = validate_upgrade(connection, statements, baseline_counts)
        passed = all(check.status != "failed" for check in checks)
        return _finish(
            artifact,
            version=version,
            started=started,
            result="passed" if passed else "failed",
            upgrade_applied=True,
            restored=False,
            cleaned_up=False,
            checks=checks,
            observed=_table_names(connection),
            error=None if passed else "Sandbox validation reported a failed check.",
            )


def prepare_sandbox_baseline(
    settings: Settings,
    *,
    _lifecycle_lock_held: bool = False,
) -> SchemaSnapshot:
    """Explicitly reset the disposable bookstore sandbox to packaged fixtures.

    The returned snapshot identifies the sandbox, not the demo source. Its
    fingerprint is used by sandbox artifacts and checkpoint verification.
    """

    if not _lifecycle_lock_held:
        from app.services.sandbox_snapshots import sandbox_lifecycle_lock

        with sandbox_lifecycle_lock(settings):
            return prepare_sandbox_baseline(settings, _lifecycle_lock_held=True)

    with _session(settings) as connection:
        _assert_identity(connection)
        connection.commit()

        with connection.begin():
            _set_timeout(connection, _BASELINE_TIMEOUT_MS, local=False)
            _prepare_baseline(connection)
        snapshot: SchemaSnapshot = assemble_snapshot(
            load_catalog(connection),
            source_id="sandbox",
            database_name=SANDBOX_DATABASE_NAME,
        )
        return snapshot


def cleanup_sandbox(settings: Settings, *, _lifecycle_lock_held: bool = False) -> SandboxRun:
    """Explicitly drop the bookstore schema on the sandbox for test cleanup."""

    if not _lifecycle_lock_held:
        from app.services.sandbox_snapshots import sandbox_lifecycle_lock

        with sandbox_lifecycle_lock(settings):
            return cleanup_sandbox(settings, _lifecycle_lock_held=True)

    started = _now()
    with _session(settings) as connection:
        _assert_identity(connection)
        version = str(connection.execute(text("SHOW server_version")).scalar_one())
        connection.commit()
        with connection.begin():
            _set_timeout(connection, _BASELINE_TIMEOUT_MS, local=False)
            _execute_reset(connection)
        tables = list(_table_names(connection))
        cleaned = tables == []
        return SandboxRun(
                migration_id="sandbox-cleanup",
                source_id="bookstore-demo",
                schema_fingerprint="",
                artifact_checksum="",
                sandbox_database=SANDBOX_DATABASE_NAME,
                sandbox_user=SANDBOX_DATABASE_USER,
                postgres_version=version,
                started_at=started,
                finished_at=_now(),
                result="passed" if cleaned else "failed",
                upgrade_applied=False,
                restored=False,
                cleaned_up=cleaned,
                checks=[
                    _check(
                        "cleanup",
                        "passed" if cleaned else "failed",
                        "Observed the bookstore tables after the schema drop.",
                    )
                ],
                observed_tables=tables,
                error=None if cleaned else "Bookstore tables were still present after cleanup.",
            )

def probe_statement_timeout(settings: Settings, *, timeout_ms: int = 50) -> SandboxRun:
    """Prove the sandbox statement timeout on a sleep. This does not apply an artifact."""

    started = _now()
    with _session(settings) as connection:
        _assert_identity(connection)
        version = str(connection.execute(text("SHOW server_version")).scalar_one())

        # Identity and version queries trigger SQLAlchemy autobegin.
        # End that read-only transaction before opening the timeout transaction.
        connection.commit()

        try:
            with connection.begin():
                _set_timeout(connection, _timeout(timeout_ms), local=True)
                connection.execute(text("SELECT pg_sleep(1)"))
        except OperationalError as exc:
            if not _is_timeout(exc):
                raise SandboxUnavailable from None

            # The timeout aborts the current PostgreSQL transaction.
            # Roll it back before collecting the result evidence.
            if connection.in_transaction():
                connection.rollback()

            return _timeout_run(
                version,
                started,
                connection,
                check_status="passed",
                detail="The sleep was cancelled by the sandbox statement timeout.",
                error="Sandbox statement exceeded the timeout.",
            )

        return _timeout_run(
            version,
            started,
            connection,
            check_status="failed",
            detail="The sleep finished before the timeout.",
            error="Sandbox statement timeout did not cancel the probe.",
        )

def _timeout_run(
    version: str,
    started: str,
    connection: Connection,
    *,
    check_status: str,
    detail: str,
    error: str,
) -> SandboxRun:
    return SandboxRun(
        migration_id="sandbox-timeout-probe",
        source_id="bookstore-demo",
        schema_fingerprint="",
        artifact_checksum="",
        sandbox_database=SANDBOX_DATABASE_NAME,
        sandbox_user=SANDBOX_DATABASE_USER,
        postgres_version=version,
        started_at=started,
        finished_at=_now(),
        result="failed",
        upgrade_applied=False,
        restored=False,
        cleaned_up=False,
        checks=[_check("statement_timeout", check_status, detail)],
        observed_tables=list(_table_names(connection)),
        error=error,
    )


def _upgrade_failure(
    connection: Connection,
    artifact: MigrationArtifact,
    version: str,
    started: str,
    exc: Exception,
) -> SandboxRun:
    try:
        restored = assemble_snapshot(
            load_catalog(connection),
            source_id=artifact.source_id,
            database_name=(
                SANDBOX_DATABASE_NAME
                if artifact.source_id == "sandbox"
                else "schemapilot_bookstore"
            ),
        ).fingerprint == artifact.schema_fingerprint
    except Exception:
        restored = False
    status = "passed" if restored else "failed"
    detail = (
        "The failed upgrade transaction rolled back to the artifact schema."
        if restored
        else "The sandbox schema does not match the artifact baseline."
    )
    return _finish(
        artifact,
        version=version,
        started=started,
        result="failed",
        upgrade_applied=False,
        restored=restored,
        cleaned_up=False,
        checks=[
            _check("upgrade", "failed", _public_error(exc)),
            _check("baseline_restored", status, detail),
            _check(
                "risk_row_checks",
                "not_run",
                "Unresolved risk row checks are not treated as passed.",
            ),
        ],
        observed=_table_names(connection),
        error=_public_error(exc),
    )


def _prepare_baseline(connection: Connection) -> None:
    _execute_reset(connection)
    _execute_allowlisted(connection, read_sql_file("schema.sql"), ("CREATE", "COMMENT"))
    _execute_allowlisted(connection, read_sql_file("seed.sql"), ("INSERT", "SELECT"))


def _execute_reset(connection: Connection) -> None:
    connection.execute(text(_RESET))


def _execute_allowlisted(connection: Connection, script: str, prefixes: tuple[str, ...]) -> None:
    for statement in split_sql_script(script):
        if not statement.lstrip().upper().startswith(prefixes):
            raise SandboxRejected(
                "unsafe_baseline",
                "Refusing to run a baseline statement outside the packaged allowlist.",
            )
        connection.execute(text(statement))


def _engine(settings: Settings):
    require_sandbox_execution(settings)
    return create_sandbox_engine(settings)


@contextmanager
def _session(settings: Settings):
    engine = _engine(settings)
    try:
        try:
            connection = engine.connect()
        except OperationalError:
            raise SandboxUnavailable from None
        try:
            yield connection
        finally:
            connection.close()
    finally:
        engine.dispose()


def _assert_identity(connection: Connection) -> None:
    current_database = connection.execute(text("SELECT current_database()")).scalar_one()
    current_user = connection.execute(text("SELECT current_user")).scalar_one()
    if current_database != SANDBOX_DATABASE_NAME or current_user != SANDBOX_DATABASE_USER:
        raise SandboxRejected(
            "sandbox_identity_rejected",
            "Refusing to continue because the connection is not the dedicated sandbox.",
        )


def _set_timeout(connection: Connection, timeout_ms: int, *, local: bool) -> None:
    connection.execute(
        text("SELECT set_config('statement_timeout', :timeout, :local)"),
        {"timeout": f"{timeout_ms}ms", "local": local},
    )


def _timeout(value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 30000:
        raise SandboxRejected("unsafe_timeout", "Sandbox statement timeout is outside 1..30000 ms.")
    return value


def _table_names(connection: Connection) -> list[str]:
    rows = connection.execute(
        text(
            "SELECT c.relname FROM pg_catalog.pg_class AS c "
            "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'bookstore' AND c.relkind = 'r' ORDER BY c.relname"
        )
    ).scalars()
    return list(rows)


def _row_counts(connection: Connection) -> dict[str, int]:
    names = _table_names(connection)
    preparer = connection.dialect.identifier_preparer
    return {
        name: int(
            connection.execute(
                text(
                    "SELECT count(*) FROM "
                    f'"bookstore".{preparer.quote(name)}'
                )
            ).scalar_one()
        )
        for name in names
    }


def _finish(
    artifact: MigrationArtifact,
    *,
    version: str,
    started: str,
    result: str,
    upgrade_applied: bool,
    restored: bool,
    cleaned_up: bool,
    checks: list[SandboxCheck],
    observed: list[str],
    error: str | None,
) -> SandboxRun:
    return SandboxRun(
        migration_id=artifact.migration_id,
        source_id=artifact.source_id,
        schema_fingerprint=artifact.schema_fingerprint,
        artifact_checksum=artifact.checksum,
        sandbox_database=SANDBOX_DATABASE_NAME,
        sandbox_user=SANDBOX_DATABASE_USER,
        postgres_version=version,
        started_at=started,
        finished_at=_now(),
        result=result,  # type: ignore[arg-type]
        upgrade_applied=upgrade_applied,
        restored=restored,
        cleaned_up=cleaned_up,
        checks=checks,
        observed_tables=observed,
        error=error,
    )


def _check(name: str, status: str, detail: str) -> SandboxCheck:
    return SandboxCheck(name=name, status=status, detail=detail)  # type: ignore[arg-type]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _is_timeout(exc: OperationalError) -> bool:
    original = getattr(exc, "orig", None)
    sqlstate = getattr(original, "sqlstate", None)
    if sqlstate == "57014":
        return True
    message = str(original or "").lower()
    return "statement timeout" in message and "://" not in message


def _public_error(exc: Exception) -> str:
    if _is_timeout(exc) if isinstance(exc, OperationalError) else False:
        return "Sandbox statement exceeded the timeout."
    original = getattr(exc, "orig", None)
    message = str(original or exc).split("\n", 1)[0]
    if "://" in message or "password" in message.lower() or "postgresql" in message.lower():
        return "Sandbox upgrade failed."
    return message[:240] or "Sandbox upgrade failed."
