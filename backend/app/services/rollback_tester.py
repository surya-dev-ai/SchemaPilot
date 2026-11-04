"""Downgrade a sandbox only after a verified upgrade of the same artifact.

Downgrade SQL comes from the saved artifact. A successful downgrade command
is not treated as proof that former column values were recovered.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import OperationalError

from app.core.config import (
    DEMO_DATABASE_NAME,
    SANDBOX_DATABASE_NAME,
    SANDBOX_DATABASE_USER,
    Settings,
    UnsafeDatabaseConfigurationError,
    require_sandbox_execution,
)
from app.db.session import create_sandbox_engine
from app.demo.bookstore import EXPECTED_COUNTS
from app.schemas.artifacts import MigrationArtifact
from app.schemas.domain import SchemaSnapshot
from app.schemas.rollback import (
    BaselineEvidence,
    RollbackReport,
    RollbackStatus,
    SnapshotRecoveryReport,
)
from app.schemas.sandbox import SandboxCheck, SandboxRun
from app.services.migration_generator import ARTIFACTS_DIR
from app.services.sandbox_manager import (
    SandboxRejected,
    SandboxUnavailable,
    _assert_identity,
    _public_error,
    load_verified_artifact,
    prepare_sandbox_baseline,
    run_sandbox,
)
from app.services.sandbox_snapshots import (
    create_verified_checkpoint,
    restore_verified_checkpoint,
    sandbox_lifecycle_lock,
)
from app.services.schema_inspector import assemble_snapshot, load_catalog
from app.services.source_manager import SANDBOX_SOURCE_ID
from app.services.validator import parse_upgrade_sql

_IDENTIFIER = r"[a-z_][a-z0-9_]*"
_DROP_COLUMN = re.compile(
    rf'^ALTER TABLE "(?P<schema>{_IDENTIFIER})"\."(?P<table>{_IDENTIFIER})" '
    rf'DROP COLUMN "(?P<column>{_IDENTIFIER})";$'
)
_ADD_COLUMN = re.compile(
    rf'^ALTER TABLE "(?P<schema>{_IDENTIFIER})"\."(?P<table>{_IDENTIFIER})" '
    rf'ADD COLUMN "(?P<column>{_IDENTIFIER})" '
    r'(?P<data_type>TEXT|INTEGER|BIGINT|BOOLEAN|TIMESTAMP WITH TIME ZONE) NULL;$'
)
_DROP_INDEX = re.compile(
    rf'^DROP INDEX "(?P<schema>{_IDENTIFIER})"\."(?P<index>{_IDENTIFIER})";$'
)
_RENAME_COLUMN = re.compile(
    rf'^ALTER TABLE "(?P<schema>{_IDENTIFIER})"\."(?P<table>{_IDENTIFIER})" '
    rf'RENAME COLUMN "(?P<old>{_IDENTIFIER})" TO "(?P<new>{_IDENTIFIER})";$'
)
_RENAME_TABLE = re.compile(
    rf'^ALTER TABLE "(?P<schema>{_IDENTIFIER})"\."(?P<table>{_IDENTIFIER})" '
    rf'RENAME TO "(?P<new>{_IDENTIFIER})";$'
)
_BLOCKED = re.compile(
    r"\bdrop\s+table\b|\btruncate\b|\bexecute\b|\badd\s+constraint\b",
    re.IGNORECASE,
)
_SENTINEL = "schemapilot_sentinel"
_VALUE_LOSS = "Recreating a dropped column does not restore its former values."


class DowngradeRejected(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class DowngradeStatement:
    kind: str
    sql_text: str
    schema_name: str
    table: str
    name: str
    other_name: str | None = None


def classify_restoration(
    *,
    upgrade_passed: bool,
    evidence_complete: bool,
    downgrade_executed: bool,
    downgrade_failed: bool,
    schema_matches: bool | None,
    data_restored: bool | None,
    data_loss: bool,
) -> RollbackStatus:
    """Map observed evidence to a rollback status. Missing evidence stays unverified."""

    if not upgrade_passed or not evidence_complete or not downgrade_executed:
        return "not_verified"
    if downgrade_failed:
        return "failed"
    if data_loss:
        return "partial_restoration"
    if schema_matches is not True or data_restored is not True:
        return "failed"
    return "exact_restoration"


def run_rollback_test(
    settings: Settings,
    migration_id: str,
    *,
    directory: Path | None = None,
    preexisting_checkpoint: SnapshotRecoveryReport | None = None,
    _lifecycle_lock_held: bool = False,
) -> RollbackReport:
    """Upgrade through the sandbox runner, then downgrade that same artifact."""

    if _lifecycle_lock_held:
        return _run_rollback_test_locked(
            settings,
            migration_id,
            directory=directory,
            preexisting_checkpoint=preexisting_checkpoint,
        )
    try:
        with sandbox_lifecycle_lock(settings):
            return _run_rollback_test_locked(
                settings,
                migration_id,
                directory=directory,
                preexisting_checkpoint=preexisting_checkpoint,
            )
    except OperationalError:
        return _unverified(
            migration_id,
            _now(),
            error="Sandbox database is unavailable.",
        )


def _run_rollback_test_locked(
    settings: Settings,
    migration_id: str,
    *,
    directory: Path | None = None,
    preexisting_checkpoint: SnapshotRecoveryReport | None = None,
) -> RollbackReport:

    started = _now()
    folder = directory or ARTIFACTS_DIR
    try:
        artifact = load_verified_artifact(folder, migration_id)
    except SandboxRejected as exc:
        return _unverified(migration_id, started, error=exc.message)
    except (SandboxUnavailable, UnsafeDatabaseConfigurationError, OperationalError):
        return _unverified(migration_id, started, error="Sandbox database is unavailable.")
    preexisting = preexisting_checkpoint or create_verified_checkpoint(
        settings, None, _lifecycle_lock_held=True
    )
    if preexisting.backup_status != "verified":
        return _unverified(
            migration_id,
            started,
            checksum=artifact.checksum,
            fingerprint=artifact.schema_fingerprint,
            preexisting_sandbox_recovery=preexisting,
            error=preexisting.error or "The pre-existing sandbox state could not be protected.",
        )
    try:
        baseline_snapshot = prepare_sandbox_baseline(settings, _lifecycle_lock_held=True)
        evidence = read_baseline_evidence(settings, baseline_snapshot)
        checkpoint = create_verified_checkpoint(
            settings,
            baseline_snapshot.fingerprint,
            _lifecycle_lock_held=True,
        )
        if checkpoint.backup_status != "verified":
            original_restore = _safe_restore(settings, preexisting)
            return _unverified(
                migration_id,
                started,
                checksum=artifact.checksum,
                fingerprint=artifact.schema_fingerprint,
                snapshot_recovery=checkpoint,
                preexisting_sandbox_recovery=original_restore,
                error=checkpoint.error or "Sandbox checkpoint could not be verified.",
            )
        upgrade = run_sandbox(
            settings,
            migration_id,
            directory=folder,
            _lifecycle_lock_held=True,
        )
    except SandboxUnavailable:
        restored_checkpoint = (
            _safe_restore(settings, checkpoint)
            if "checkpoint" in locals() and checkpoint.backup_status == "verified"
            else None
        )
        original_restore = _safe_restore(settings, preexisting)
        return _unverified(
            migration_id,
            started,
            checksum=artifact.checksum,
            fingerprint=artifact.schema_fingerprint,
            snapshot_recovery=restored_checkpoint,
            preexisting_sandbox_recovery=original_restore,
            error="Sandbox database is unavailable.",
        )
    except (SandboxRejected, UnsafeDatabaseConfigurationError) as exc:
        message = _rejected_message(exc)
        restored_checkpoint = (
            _safe_restore(settings, checkpoint)
            if "checkpoint" in locals() and checkpoint.backup_status == "verified"
            else None
        )
        original_restore = _safe_restore(settings, preexisting)
        return _unverified(
            migration_id,
            started,
            checksum=artifact.checksum,
            fingerprint=artifact.schema_fingerprint,
            snapshot_recovery=restored_checkpoint,
            preexisting_sandbox_recovery=original_restore,
            error=message,
        )
    except Exception:
        restored_checkpoint = (
            _safe_restore(settings, checkpoint)
            if "checkpoint" in locals() and checkpoint.backup_status == "verified"
            else None
        )
        original_restore = _safe_restore(settings, preexisting)
        return _unverified(
            migration_id,
            started,
            checksum=artifact.checksum,
            fingerprint=artifact.schema_fingerprint,
            snapshot_recovery=restored_checkpoint,
            preexisting_sandbox_recovery=original_restore,
            error="Sandbox workflow failed unexpectedly; recovery was attempted.",
        )
    try:
        report = downgrade_verified_upgrade(
            settings,
            migration_id,
            folder,
            upgrade,
            evidence,
            started=started,
        )
    except Exception:
        report = _unverified(
            migration_id,
            started,
            checksum=artifact.checksum,
            fingerprint=artifact.schema_fingerprint,
            error="Sandbox downgrade verification failed unexpectedly.",
        )
    snapshot_recovery = _safe_restore(settings, checkpoint)
    original_restore = _safe_restore(settings, preexisting)
    return report.model_copy(
        update={
            "snapshot_recovery": snapshot_recovery,
            "preexisting_sandbox_recovery": original_restore,
        }
    )


def _safe_restore(settings: Settings, checkpoint: SnapshotRecoveryReport) -> SnapshotRecoveryReport:
    try:
        return restore_verified_checkpoint(
            settings,
            checkpoint,
            _lifecycle_lock_held=True,
        )
    except Exception:
        return checkpoint.model_copy(
            update={
                "restore_status": "verification_incomplete",
                "error": "Sandbox snapshot restore could not be completed or verified.",
            }
        )


def downgrade_verified_upgrade(
    settings: Settings,
    migration_id: str,
    directory: Path,
    upgrade: SandboxRun,
    evidence: BaselineEvidence | None,
    *,
    started: str | None = None,
) -> RollbackReport:
    """Run the saved downgrade only when this upgrade passed validation."""

    started_at = started or _now()
    if (
        upgrade.result != "passed"
        or not upgrade.upgrade_applied
        or evidence is None
        or not evidence.schema_fingerprint
        or upgrade.schema_fingerprint != evidence.schema_fingerprint
        or upgrade.migration_id != migration_id
    ):
        return _from_upgrade(
            upgrade,
            evidence,
            started_at,
            status="not_verified",
            downgrade_executed=False,
            error="Rollback requires a passed upgrade and matching baseline evidence.",
        )
    try:
        artifact = load_verified_artifact(directory, migration_id)
    except SandboxRejected as exc:
        return _from_upgrade(
            upgrade,
            evidence,
            started_at,
            status="not_verified",
            downgrade_executed=False,
            error=exc.message,
        )
    if artifact.checksum != upgrade.artifact_checksum:
        return _from_upgrade(
            upgrade,
            evidence,
            started_at,
            status="not_verified",
            downgrade_executed=False,
            error="The artifact checksum changed after the upgrade.",
        )
    try:
        statements = parse_downgrade_sql(artifact.downgrade_sql)
        assert_downgrade_matches(artifact, statements)
    except DowngradeRejected as exc:
        return _from_upgrade(
            upgrade,
            evidence,
            started_at,
            status="not_verified",
            downgrade_executed=False,
            error=exc.message,
        )
    data_loss = any(item.data_loss_on_downgrade for item in artifact.operation_reversibility)
    limitations = [_VALUE_LOSS] if data_loss else []
    try:
        observed, checks, failed, schema_matches, data_restored, downgrade_executed = _downgrade(
            settings,
            artifact,
            statements,
            evidence,
            data_loss,
        )
    except SandboxUnavailable:
        return _from_upgrade(
            upgrade,
            evidence,
            started_at,
            status="not_verified",
            downgrade_executed=False,
            limitations=limitations,
            error="Sandbox database is unavailable.",
        )
    except (SandboxRejected, UnsafeDatabaseConfigurationError) as exc:
        message = _rejected_message(exc)
        return _from_upgrade(
            upgrade,
            evidence,
            started_at,
            status="not_verified",
            downgrade_executed=False,
            limitations=limitations,
            error=message,
        )
    status = classify_restoration(
        upgrade_passed=True,
        evidence_complete=True,
        downgrade_executed=downgrade_executed,
        downgrade_failed=failed,
        schema_matches=schema_matches,
        data_restored=data_restored,
        data_loss=data_loss,
    )
    error = None
    if status == "failed":
        command_error = next(
            (
                check.detail
                for check in checks
                if check.name == "downgrade" and check.status == "failed"
            ),
            None,
        )
        error = command_error or "Downgrade did not restore the recorded baseline."
    elif not downgrade_executed:
        error = next(
            (
                check.detail
                for check in checks
                if check.name == "rollback_precondition" and check.status == "failed"
            ),
            "Downgrade was not run because its sandbox preconditions failed.",
        )
    return _from_upgrade(
        upgrade,
        evidence,
        started_at,
        status=status,
        downgrade_executed=downgrade_executed,
        schema_matches=schema_matches,
        observed=observed,
        checks=checks,
        limitations=limitations,
        error=error,
    )


def parse_downgrade_sql(downgrade_sql: str) -> list[DowngradeStatement]:
    """Accept only downgrade statements produced for an eligible artifact."""

    statements: list[DowngradeStatement] = []
    for raw_line in downgrade_sql.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _BLOCKED.search(line):
            raise DowngradeRejected(
                "policy_blocked",
                "The downgrade contains an operation the sandbox will not run.",
            )
        parsed = _parse_downgrade_line(line)
        if parsed is None or parsed.schema_name != "bookstore":
            raise DowngradeRejected(
                "unsupported_operation",
                "The downgrade SQL is not one of the supported statements.",
            )
        statements.append(parsed)
    if not statements:
        raise DowngradeRejected("unsupported_operation", "The artifact has no downgrade statement.")
    return statements


def assert_downgrade_matches(
    artifact: MigrationArtifact,
    statements: list[DowngradeStatement],
) -> None:
    if "def downgrade()" not in artifact.alembic_source:
        raise DowngradeRejected("artifact_inconsistent", "The Alembic module has no downgrade.")
    body = artifact.alembic_source.split("def downgrade()", 1)[1]
    if re.search(r"\bop\.(execute|drop_table)\b", body):
        raise DowngradeRejected(
            "policy_blocked",
            "The Alembic downgrade is not an eligible generated operation.",
        )
    for statement in statements:
        if not _downgrade_mentions(body, statement):
            raise DowngradeRejected(
                "artifact_inconsistent",
                "The downgrade SQL and the Alembic module do not describe the same change.",
            )


def read_baseline_evidence(settings: Settings, snapshot: SchemaSnapshot) -> BaselineEvidence:
    with _connect(settings) as connection:
        return _evidence(connection, snapshot.fingerprint)


def live_schema_matches(settings: Settings, fingerprint: str) -> bool:
    with _connect(settings) as connection:
        observed = _sandbox_snapshot(connection, SANDBOX_SOURCE_ID).fingerprint
    return observed == fingerprint


def _downgrade(
    settings: Settings,
    artifact: MigrationArtifact,
    statements: list[DowngradeStatement],
    evidence: BaselineEvidence,
    data_loss: bool,
) -> tuple[str, list[SandboxCheck], bool, bool, bool, bool]:
    checks: list[SandboxCheck] = []
    upgrade_statements = parse_upgrade_sql(artifact.sql_preview)
    with _connect(settings) as connection:
        failed = False
        if data_loss:
            try:
                with connection.begin():
                    _write_sentinels(connection, upgrade_statements)
            except Exception as exc:
                checks.append(
                    SandboxCheck(
                        name="rollback_precondition",
                        status="failed",
                        detail=_public_error(exc),
                    )
                )
                observed = _sandbox_snapshot(connection, artifact.source_id)
                current = _evidence(connection, observed.fingerprint)
                schema_matches = current.schema_fingerprint == evidence.schema_fingerprint
                data_restored = (
                    current.row_counts == evidence.row_counts and current.emails == evidence.emails
                )
                checks.extend(
                    [
                        SandboxCheck(
                            name="schema_fingerprint",
                            status="passed" if schema_matches else "failed",
                            detail=(
                                "Compared the post-downgrade fingerprint "
                                "with the recorded baseline."
                            ),
                        ),
                        SandboxCheck(
                            name="baseline_rows",
                            status="passed" if data_restored else "failed",
                            detail="Compared recorded row counts and user emails.",
                        ),
                        SandboxCheck(
                            name="former_column_values",
                            status="not_run",
                            detail=(
                                "The rollback precondition failed before sentinel "
                                "values were written."
                            ),
                        ),
                    ]
                )
                return (
                    current.schema_fingerprint,
                    checks,
                    True,
                    schema_matches,
                    data_restored,
                    False,
                )
        try:
            with connection.begin():
                for statement in statements:
                    connection.execute(text(statement.sql_text))
        except OperationalError as exc:
            failed = True
            checks.append(_failed_downgrade(exc))
        except Exception as exc:
            failed = True
            checks.append(_failed_downgrade(exc))
        else:
            checks.append(
                SandboxCheck(
                    name="downgrade",
                    status="passed",
                    detail="Downgrade statements finished.",
                )
            )
        observed = _sandbox_snapshot(connection, artifact.source_id)
        current = _evidence(connection, observed.fingerprint)
    schema_matches = current.schema_fingerprint == evidence.schema_fingerprint
    data_restored = current.row_counts == evidence.row_counts and current.emails == evidence.emails
    checks.append(
        SandboxCheck(
            name="schema_fingerprint",
            status="passed" if schema_matches else "failed",
            detail="Compared the post-downgrade fingerprint with the recorded baseline.",
        )
    )
    checks.append(
        SandboxCheck(
            name="baseline_rows",
            status="passed" if data_restored else "failed",
            detail="Compared recorded row counts and user emails.",
        )
    )
    if data_loss:
        checks.append(
            SandboxCheck(
                name="former_column_values",
                status="failed",
                detail=_VALUE_LOSS,
            )
        )
    return current.schema_fingerprint, checks, failed, schema_matches, data_restored, True


def _sandbox_snapshot(connection: Connection, source_id: str) -> SchemaSnapshot:
    """Fingerprint catalog state using the artifact's source identity."""

    database_name = (
        SANDBOX_DATABASE_NAME if source_id == SANDBOX_SOURCE_ID else DEMO_DATABASE_NAME
    )
    return assemble_snapshot(
        load_catalog(connection),
        source_id=source_id,
        database_name=database_name,
    )


def _write_sentinels(connection: Connection, statements: list) -> None:
    for statement in statements:
        if statement.kind != "add_column" or statement.column is None:
            continue
        connection.execute(
            text(
                f'UPDATE "{statement.schema_name}"."{statement.table}" '
                f'SET "{statement.column}" = :sentinel'
            ),
            {"sentinel": _SENTINEL},
        )


def _evidence(connection: Connection, fingerprint: str) -> BaselineEvidence:
    table_names = list(
        connection.execute(
            text(
                "SELECT c.relname FROM pg_catalog.pg_class AS c "
                "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'bookstore' AND c.relkind = 'r' ORDER BY c.relname"
            )
        ).scalars()
    )
    counts = {
        table: int(
            connection.execute(text(f'SELECT count(*) FROM "bookstore"."{table}"')).scalar_one()
        )
        for table in EXPECTED_COUNTS
        if table in table_names and _safe_name(table)
    }
    emails: list[str] = []
    if "users" in table_names:
        emails = list(
            connection.execute(text("SELECT email FROM bookstore.users ORDER BY id")).scalars()
        )
    return BaselineEvidence(
        schema_fingerprint=fingerprint,
        tables=table_names,
        row_counts=counts,
        emails=emails,
    )


def _connect(settings: Settings):
    try:
        require_sandbox_execution(settings)
    except UnsafeDatabaseConfigurationError:
        raise
    engine = create_sandbox_engine(settings)
    try:
        try:
            connection = engine.connect()
        except OperationalError:
            raise SandboxUnavailable from None
    except SandboxUnavailable:
        engine.dispose()
        raise

    class _Closing:
        def __enter__(self) -> Connection:
            return connection

        def __exit__(self, exc_type, exc, traceback) -> None:
            connection.close()
            engine.dispose()

    try:
        _assert_identity(connection)
        connection.commit()
    except Exception:
        connection.close()
        engine.dispose()
        raise
    return _Closing()


def _parse_downgrade_line(line: str) -> DowngradeStatement | None:
    match = _ADD_COLUMN.fullmatch(line)
    if match is not None:
        return DowngradeStatement(
            "add_column",
            line,
            match.group("schema"),
            match.group("table"),
            match.group("column"),
            match.group("data_type"),
        )
    match = _DROP_COLUMN.fullmatch(line)
    if match is not None:
        return DowngradeStatement(
            "drop_column",
            line,
            match.group("schema"),
            match.group("table"),
            match.group("column"),
        )
    match = _DROP_INDEX.fullmatch(line)
    if match is not None:
        return DowngradeStatement(
            "drop_index",
            line,
            match.group("schema"),
            "",
            match.group("index"),
        )
    match = _RENAME_COLUMN.fullmatch(line)
    if match is not None:
        return DowngradeStatement(
            "rename_column",
            line,
            match.group("schema"),
            match.group("table"),
            match.group("new"),
            match.group("old"),
        )
    match = _RENAME_TABLE.fullmatch(line)
    if match is not None:
        return DowngradeStatement(
            "rename_table",
            line,
            match.group("schema"),
            match.group("table"),
            match.group("new"),
        )
    return None


def _downgrade_mentions(body: str, statement: DowngradeStatement) -> bool:
    if statement.kind == "add_column":
        return "op.add_column(" in body and f'"{statement.name}"' in body
    if statement.kind == "drop_column":
        return "op.drop_column(" in body and f'"{statement.name}"' in body
    if statement.kind == "drop_index":
        return "op.drop_index(" in body and f'"{statement.name}"' in body
    if statement.kind == "rename_column":
        return "op.alter_column(" in body and f'"{statement.name}"' in body
    return "op.rename_table(" in body and f'"{statement.name}"' in body


def _safe_name(value: str) -> bool:
    return re.fullmatch(_IDENTIFIER, value) is not None


def _unverified(
    migration_id: str,
    started: str,
    *,
    checksum: str = "",
    fingerprint: str = "",
    snapshot_recovery: SnapshotRecoveryReport | None = None,
    preexisting_sandbox_recovery: SnapshotRecoveryReport | None = None,
    error: str,
) -> RollbackReport:
    return RollbackReport(
        migration_id=migration_id,
        artifact_checksum=checksum,
        source_id="bookstore-demo",
        schema_fingerprint=fingerprint,
        sandbox_database="",
        sandbox_user="",
        postgres_version="",
        started_at=started,
        finished_at=_now(),
        status="not_verified",
        downgrade_executed=False,
        data_checks=[],
        data_loss_limitations=[],
        error=error,
        snapshot_recovery=snapshot_recovery,
        preexisting_sandbox_recovery=preexisting_sandbox_recovery,
    )


def _from_upgrade(
    upgrade: SandboxRun,
    evidence: BaselineEvidence | None,
    started: str,
    *,
    status: RollbackStatus,
    downgrade_executed: bool,
    schema_matches: bool | None = None,
    observed: str | None = None,
    checks: list[SandboxCheck] | None = None,
    limitations: list[str] | None = None,
    snapshot_recovery: SnapshotRecoveryReport | None = None,
    error: str | None,
) -> RollbackReport:
    return RollbackReport(
        migration_id=upgrade.migration_id,
        artifact_checksum=upgrade.artifact_checksum,
        source_id=upgrade.source_id,
        schema_fingerprint=upgrade.schema_fingerprint,
        sandbox_database=upgrade.sandbox_database or SANDBOX_DATABASE_NAME,
        sandbox_user=upgrade.sandbox_user or SANDBOX_DATABASE_USER,
        postgres_version=upgrade.postgres_version,
        started_at=started,
        finished_at=_now(),
        status=status,
        upgrade=upgrade,
        baseline=evidence,
        observed_fingerprint=observed,
        downgrade_executed=downgrade_executed,
        schema_matches_baseline=schema_matches,
        data_checks=checks or [],
        data_loss_limitations=limitations or [],
        error=error,
        snapshot_recovery=snapshot_recovery,
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _failed_downgrade(exc: Exception) -> SandboxCheck:
    return SandboxCheck(
        name="downgrade",
        status="failed",
        detail=_public_error(exc),
    )


def _rejected_message(exc: Exception) -> str:
    message = getattr(exc, "message", None)
    if isinstance(message, str) and message.strip():
        return message
    text_value = str(exc)
    if "://" in text_value or "password" in text_value.lower():
        return "Sandbox database is unavailable."
    return text_value or "Sandbox request was rejected."
