"""Create, test, and restore retained checkpoints inside the isolated sandbox cluster.

Checkpoints use PostgreSQL CREATE DATABASE ... TEMPLATE, so schema, table data,
indexes, constraints, and database-local catalog state are copied by PostgreSQL.
They remain on the same cluster and are not an off-host production backup.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.engine.url import make_url
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import (
    SANDBOX_DATABASE_NAME,
    SANDBOX_DATABASE_USER,
    Settings,
    require_sandbox_execution,
)
from app.schemas.domain import SchemaSnapshot
from app.schemas.rollback import SnapshotRecoveryReport
from app.schemas.sandbox import SandboxCheck
from app.services.schema_inspector import assemble_snapshot, load_catalog
from app.services.source_manager import SANDBOX_SOURCE_ID

_CHECKPOINT_PREFIX = "schemapilot_checkpoint_"
_VERIFY_PREFIX = "schemapilot_verify_"
_REPLACEMENT_PREFIX = "schemapilot_replacement_"
_PREVIOUS_PREFIX = "schemapilot_previous_"
_FAILED_PREFIX = "schemapilot_failed_"
_CHECKPOINT_ID = re.compile(r"^[0-9a-f]{32}$")
_LIFECYCLE_LOCK_KEY = 0x534348454D415049


def create_verified_checkpoint(
    settings: Settings,
    expected_schema_fingerprint: str | None,
    *,
    _lifecycle_lock_held: bool = False,
) -> SnapshotRecoveryReport:
    """Clone the current sandbox and prove a second clone matches before migration."""

    if not _lifecycle_lock_held:
        with sandbox_lifecycle_lock(settings):
            return create_verified_checkpoint(
                settings,
                expected_schema_fingerprint,
                _lifecycle_lock_held=True,
            )

    captured_at = _now()
    checkpoint_id = uuid.uuid4().hex
    checkpoint_name = _checkpoint_name(checkpoint_id)
    verify_name = _VERIFY_PREFIX + checkpoint_id
    checkpoint_created = False
    try:
        url = make_url(require_sandbox_execution(settings))
        baseline_schema, baseline_data = _inspect_database(url, SANDBOX_DATABASE_NAME)
        if expected_schema_fingerprint and baseline_schema != expected_schema_fingerprint:
            return SnapshotRecoveryReport(
                checkpoint_id=checkpoint_id,
                captured_at=captured_at,
                backup_status="failed",
                restore_status="not_attempted",
                baseline_schema_fingerprint=baseline_schema,
                baseline_data_fingerprint=baseline_data,
                error="Sandbox baseline did not match the expected schema.",
            )
        with _maintenance_engine(url) as engine:
            with engine.connect() as connection:
                _assert_maintenance_identity(connection)
                _create_database(connection, checkpoint_name, SANDBOX_DATABASE_NAME)
                checkpoint_created = True
                _create_database(connection, verify_name, checkpoint_name)

        restored_schema, restored_data = _inspect_database(url, verify_name)
        schema_match = restored_schema == baseline_schema
        data_match = restored_data == baseline_data
        checks = [
            _check(
                "checkpoint_schema_restore",
                schema_match,
                "The checkpoint clone was compared with the pre-migration schema.",
            ),
            _check(
                "checkpoint_data_restore",
                data_match,
                "All rows in the bookstore schema were compared with the pre-migration data.",
            ),
        ]
        _drop_database(url, verify_name)
        verified = schema_match and data_match
        return SnapshotRecoveryReport(
            checkpoint_id=checkpoint_id,
            captured_at=captured_at,
            backup_status="verified" if verified else "failed",
            restore_status="not_attempted",
            baseline_schema_fingerprint=baseline_schema,
            restored_schema_fingerprint=restored_schema,
            baseline_data_fingerprint=baseline_data,
            restored_data_fingerprint=restored_data,
            schema_match=schema_match,
            data_match=data_match,
            verification_checks=checks,
            checkpoint_retained=True,
            error=None if verified else "Checkpoint test-restore did not match the baseline.",
        )
    except (SQLAlchemyError, RuntimeError, ValueError):
        # Verification databases are disposable scratch copies. A checkpoint is
        # intentionally retained for evidence/recovery, but scratch copies must
        # not accumulate if clone or inspection fails midway.
        try:
            if "url" in locals() and _database_exists_by_url(url, verify_name):
                _drop_database(url, verify_name)
        except Exception:
            pass
        return SnapshotRecoveryReport(
            checkpoint_id=checkpoint_id,
            captured_at=captured_at,
            backup_status="unavailable",
            restore_status="not_attempted",
            checkpoint_retained=checkpoint_created,
            error="Sandbox checkpoint could not be created or verified.",
        )


def restore_verified_checkpoint(
    settings: Settings,
    checkpoint: SnapshotRecoveryReport,
    *,
    _lifecycle_lock_held: bool = False,
) -> SnapshotRecoveryReport:
    """Replace only schemapilot_sandbox from a retained verified checkpoint."""

    if not _lifecycle_lock_held:
        with sandbox_lifecycle_lock(settings):
            return restore_verified_checkpoint(
                settings,
                checkpoint,
                _lifecycle_lock_held=True,
            )

    if checkpoint.backup_status != "verified" or checkpoint.checkpoint_id is None:
        return checkpoint.model_copy(
            update={
                "restore_status": "backup_unavailable",
                "error": checkpoint.error or "No verified sandbox checkpoint is available.",
            }
        )
    if _CHECKPOINT_ID.fullmatch(checkpoint.checkpoint_id) is None:
        return checkpoint.model_copy(
            update={
                "restore_status": "backup_unavailable",
                "error": "Sandbox checkpoint identity is invalid.",
            }
        )

    url = make_url(require_sandbox_execution(settings))
    checkpoint_name = _checkpoint_name(checkpoint.checkpoint_id)
    verify_name = _VERIFY_PREFIX + checkpoint.checkpoint_id
    try:
        with _maintenance_engine(url) as engine:
            with engine.connect() as connection:
                _assert_maintenance_identity(connection)
                if not _database_exists(connection, checkpoint_name):
                    return checkpoint.model_copy(
                        update={
                            "restore_status": "backup_unavailable",
                            "checkpoint_retained": False,
                            "error": "The retained sandbox checkpoint is unavailable.",
                        }
                    )
                _create_database(connection, verify_name, checkpoint_name)

        probe_schema, probe_data = _inspect_database(url, verify_name)
        probe_matches = (
            probe_schema == checkpoint.baseline_schema_fingerprint
            and probe_data == checkpoint.baseline_data_fingerprint
        )
        _drop_database(url, verify_name)
        if not probe_matches:
            return checkpoint.model_copy(
                update={
                    "restore_status": "verification_incomplete",
                    "restored_schema_fingerprint": probe_schema,
                    "restored_data_fingerprint": probe_data,
                    "schema_match": probe_schema == checkpoint.baseline_schema_fingerprint,
                    "data_match": probe_data == checkpoint.baseline_data_fingerprint,
                    "verification_checks": [
                        *_checkpoint_checks(
                            probe_schema == checkpoint.baseline_schema_fingerprint,
                            probe_data == checkpoint.baseline_data_fingerprint,
                            "checkpoint_pre_restore_probe",
                        )
                    ],
                    "error": "Checkpoint verification failed; the sandbox was left unchanged.",
                }
            )

        # Build and verify a replacement first, then rename the old database
        # aside. The old database remains available until the new canonical
        # database has passed final verification.
        replacement_name = _REPLACEMENT_PREFIX + checkpoint.checkpoint_id
        previous_name = _PREVIOUS_PREFIX + checkpoint.checkpoint_id
        failed_name = _FAILED_PREFIX + checkpoint.checkpoint_id
        _restore_checkpoint_database(
            url,
            checkpoint_name,
            replacement_name,
            previous_name,
            failed_name,
            checkpoint,
        )

        restored_schema, restored_data = _inspect_database(url, SANDBOX_DATABASE_NAME)
        schema_match = restored_schema == checkpoint.baseline_schema_fingerprint
        data_match = restored_data == checkpoint.baseline_data_fingerprint
        verified = schema_match and data_match
        return checkpoint.model_copy(
            update={
                "restore_status": "restore_verified" if verified else "restore_failed",
                "restored_schema_fingerprint": restored_schema,
                "restored_data_fingerprint": restored_data,
                "schema_match": schema_match,
                "data_match": data_match,
                "verification_checks": [
                    *checkpoint.verification_checks,
                    *_checkpoint_checks(schema_match, data_match, "sandbox_restore"),
                ],
                "checkpoint_retained": True,
                "error": None if verified else "Restored sandbox did not match the checkpoint.",
            }
        )
    except (SQLAlchemyError, RuntimeError, ValueError):
        try:
            if _database_exists_by_url(url, verify_name):
                _drop_database(url, verify_name)
        except Exception:
            pass
        return checkpoint.model_copy(
            update={
                "restore_status": "verification_incomplete",
                "checkpoint_retained": True,
                "verification_checks": [
                    *checkpoint.verification_checks,
                    SandboxCheck(
                        name="sandbox_restore",
                        status="not_run",
                        detail="The sandbox restore or its verification could not complete.",
                    ),
                ],
                "error": "Sandbox snapshot restore could not be completed or verified.",
            }
        )


def _restore_checkpoint_database(
    url: URL,
    checkpoint_name: str,
    replacement_name: str,
    previous_name: str,
    failed_name: str,
    checkpoint: SnapshotRecoveryReport,
) -> None:
    """Resume a known swap state, and only discard the prior DB after verification."""
    with _maintenance_engine(url) as engine:
        with engine.connect() as connection:
            _assert_maintenance_identity(connection)
            canonical_exists = _database_exists(connection, SANDBOX_DATABASE_NAME)
            replacement_exists = _database_exists(connection, replacement_name)
            previous_exists = _database_exists(connection, previous_name)
            failed_exists = _database_exists(connection, failed_name)

    if failed_exists:
        raise RuntimeError("A failed sandbox recovery database needs operator review.")

    if canonical_exists:
        canonical_schema, canonical_data = _inspect_database(url, SANDBOX_DATABASE_NAME)
        canonical_matches = (
            canonical_schema == checkpoint.baseline_schema_fingerprint
            and canonical_data == checkpoint.baseline_data_fingerprint
        )
        if canonical_matches:
            if replacement_exists:
                raise RuntimeError("An unexpected staged sandbox replacement remains.")
            if previous_exists:
                _drop_database(
                    url,
                    previous_name,
                    allowed_prefixes=(_PREVIOUS_PREFIX,),
                )
            return
        if previous_exists:
            raise RuntimeError(
                "The canonical sandbox and retained previous database need operator review."
            )
        if not replacement_exists:
            _create_verified_replacement(url, checkpoint_name, replacement_name, checkpoint)
        else:
            _verify_staged_replacement(url, replacement_name, checkpoint)
        _swap_sandbox_database(
            url,
            replacement_name,
            previous_name,
            failed_name,
            checkpoint,
        )
        return

    # A process may have exited after sandbox -> previous but before the
    # replacement was promoted. The checkpoint remains authoritative; validate
    # an existing stage or rebuild it from that checkpoint if it is absent.
    if not replacement_exists:
        _create_verified_replacement(url, checkpoint_name, replacement_name, checkpoint)
    else:
        _verify_staged_replacement(url, replacement_name, checkpoint)

    with _maintenance_engine(url) as engine:
        with engine.connect() as connection:
            _assert_maintenance_identity(connection)
            if _database_exists(connection, SANDBOX_DATABASE_NAME):
                raise RuntimeError("The canonical sandbox reappeared during recovery.")
            if not _database_exists(connection, replacement_name):
                raise RuntimeError("The verified sandbox replacement is unavailable.")
            connection.execute(
                text(
                    f'ALTER DATABASE "{replacement_name}" RENAME TO "{SANDBOX_DATABASE_NAME}"'
                )
            )

    restored_schema, restored_data = _inspect_database(url, SANDBOX_DATABASE_NAME)
    if (
        restored_schema != checkpoint.baseline_schema_fingerprint
        or restored_data != checkpoint.baseline_data_fingerprint
    ):
        raise RuntimeError("Restored sandbox did not match the retained checkpoint.")

    # Keep the previous database until the promoted canonical database has
    # passed both schema and row-content verification.
    if previous_exists:
        _drop_database(url, previous_name, allowed_prefixes=(_PREVIOUS_PREFIX,))


def _verify_staged_replacement(
    url: URL,
    replacement_name: str,
    checkpoint: SnapshotRecoveryReport,
) -> None:
    _assert_database_name(replacement_name, (_REPLACEMENT_PREFIX,))
    schema, data = _inspect_database(url, replacement_name)
    if (
        schema != checkpoint.baseline_schema_fingerprint
        or data != checkpoint.baseline_data_fingerprint
    ):
        raise RuntimeError("The staged sandbox replacement does not match its checkpoint.")


@contextmanager
def sandbox_lifecycle_lock(settings: Settings):
    """Serialize destructive sandbox operations across threads and processes."""

    url = make_url(require_sandbox_execution(settings))
    with _maintenance_engine(url) as engine:
        with engine.connect() as connection:
            _assert_maintenance_identity(connection)
            connection.execute(text("SELECT set_config('statement_timeout', '30000', false)"))
            connection.execute(
                text("SELECT pg_advisory_lock(:lock_key)"),
                {"lock_key": _LIFECYCLE_LOCK_KEY},
            )
            try:
                yield
            finally:
                connection.execute(
                    text("SELECT pg_advisory_unlock(:lock_key)"),
                    {"lock_key": _LIFECYCLE_LOCK_KEY},
                )


def _inspect_database(url: URL, database_name: str) -> tuple[str, str]:
    engine = create_engine(
        url.set(database=database_name),
        pool_pre_ping=True,
        connect_args={"connect_timeout": 5},
    )
    try:
        with engine.connect() as connection:
            current_database, current_user = connection.execute(
                text("SELECT current_database(), current_user")
            ).one()
            if current_database != database_name or current_user != SANDBOX_DATABASE_USER:
                raise RuntimeError("Sandbox database identity was not verified.")
            snapshot: SchemaSnapshot = assemble_snapshot(
                load_catalog(connection),
                source_id=SANDBOX_SOURCE_ID,
                database_name=SANDBOX_DATABASE_NAME,
            )
            return snapshot.fingerprint, _data_fingerprint(connection)
    finally:
        engine.dispose()


def _data_fingerprint(connection) -> str:
    digest = hashlib.sha256()
    tables = connection.execute(
        text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'bookstore' AND table_type = 'BASE TABLE' "
            "ORDER BY table_name"
        )
    ).scalars()
    preparer = connection.dialect.identifier_preparer
    for table in tables:
        table_name = str(table)
        digest.update(table_name.encode("utf-8"))
        quoted_table = preparer.quote(table_name)
        rows = connection.execute(
            text(
                "SELECT to_jsonb(row_value)::text FROM "
                f'"bookstore".{quoted_table} AS row_value '
                "ORDER BY to_jsonb(row_value)::text"
            )
        ).scalars()
        for row in rows:
            encoded = str(row).encode("utf-8")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
    sequences = connection.execute(
        text(
            "SELECT schemaname, sequencename, last_value "
            "FROM pg_catalog.pg_sequences WHERE schemaname = 'bookstore' "
            "ORDER BY sequencename"
        )
    )
    for schema_name, sequence_name, last_value in sequences:
        digest.update(f"sequence:{schema_name}.{sequence_name}:{last_value}".encode())
    return digest.hexdigest()


@contextmanager
def _maintenance_engine(url: URL):
    engine = create_engine(
        url.set(database="postgres"),
        pool_pre_ping=True,
        isolation_level="AUTOCOMMIT",
        connect_args={"connect_timeout": 5},
    )
    try:
        yield engine
    finally:
        engine.dispose()


def _assert_maintenance_identity(connection) -> None:
    database, user = connection.execute(
        text("SELECT current_database(), current_user")
    ).one()
    if database != "postgres" or user != SANDBOX_DATABASE_USER:
        raise RuntimeError("Sandbox maintenance connection identity was not verified.")


def _create_database(connection, name: str, template: str) -> None:
    if not re.fullmatch(r"[a-z0-9_]{1,63}", name) or not re.fullmatch(
        r"[a-z0-9_]{1,63}", template
    ):
        raise ValueError("Invalid generated sandbox database name.")
    if _database_exists(connection, name):
        raise RuntimeError("Generated sandbox checkpoint name already exists.")
    connection.execute(
        text(
            f'CREATE DATABASE "{name}" WITH TEMPLATE "{template}" '
            f'OWNER "{SANDBOX_DATABASE_USER}"'
        )
    )


def _create_verified_replacement(
    url: URL,
    checkpoint_name: str,
    replacement_name: str,
    checkpoint: SnapshotRecoveryReport,
) -> None:
    try:
        with _maintenance_engine(url) as engine:
            with engine.connect() as connection:
                _assert_maintenance_identity(connection)
                _create_database(connection, replacement_name, checkpoint_name)
        schema, data = _inspect_database(url, replacement_name)
        if (
            schema != checkpoint.baseline_schema_fingerprint
            or data != checkpoint.baseline_data_fingerprint
        ):
            raise RuntimeError("Sandbox replacement clone did not match its checkpoint.")
    except Exception:
        try:
            _drop_database(url, replacement_name, allowed_prefixes=(_REPLACEMENT_PREFIX,))
        except Exception:
            pass
        raise


def _swap_sandbox_database(
    url: URL,
    replacement_name: str,
    previous_name: str,
    failed_name: str,
    checkpoint: SnapshotRecoveryReport,
) -> None:
    renamed_previous = False
    swapped = False
    try:
        with _maintenance_engine(url) as engine:
            with engine.connect() as connection:
                _assert_maintenance_identity(connection)
                if _database_exists(connection, previous_name) or _database_exists(
                    connection, failed_name
                ):
                    raise RuntimeError("A prior sandbox replacement recovery database exists.")
                connection.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_catalog.pg_stat_activity "
                        "WHERE datname = :database AND pid <> pg_backend_pid()"
                    ),
                    {"database": SANDBOX_DATABASE_NAME},
                )
                connection.execute(
                    text(
                        f'ALTER DATABASE "{SANDBOX_DATABASE_NAME}" RENAME TO "{previous_name}"'
                    )
                )
                renamed_previous = True
                connection.execute(
                    text(
                        f'ALTER DATABASE "{replacement_name}" RENAME TO "{SANDBOX_DATABASE_NAME}"'
                    )
                )
                swapped = True

        schema, data = _inspect_database(url, SANDBOX_DATABASE_NAME)
        if (
            schema != checkpoint.baseline_schema_fingerprint
            or data != checkpoint.baseline_data_fingerprint
        ):
            _rollback_database_swap(url, previous_name, failed_name, swapped, renamed_previous)
            raise RuntimeError("Restored sandbox verification did not match its checkpoint.")

        # Discard the renamed previous sandbox only after the new canonical DB
        # has passed final data and schema verification.
        with _maintenance_engine(url) as engine:
            with engine.connect() as connection:
                _assert_maintenance_identity(connection)
                connection.execute(text(f'DROP DATABASE "{previous_name}" WITH (FORCE)'))
    except Exception:
        if renamed_previous:
            try:
                _rollback_database_swap(url, previous_name, failed_name, swapped, True)
            except Exception:
                # The previous DB remains under its recovery name. Never delete
                # it as part of exception handling.
                pass
        try:
            # A failed second rename can leave the verified replacement under
            # its staging name. Remove it only after proving the old canonical
            # sandbox is back and the previous-name recovery database is gone.
            canonical_is_restored = _database_exists_by_url(url, SANDBOX_DATABASE_NAME)
            previous_is_retained = _database_exists_by_url(url, previous_name)
            replacement_is_staged = _database_exists_by_url(url, replacement_name)
            if canonical_is_restored and not previous_is_retained and replacement_is_staged:
                _drop_database(
                    url,
                    replacement_name,
                    allowed_prefixes=(_REPLACEMENT_PREFIX,),
                )
        except Exception:
            # Cleanup is best-effort; the caller still reports an unverified restore.
            pass
        raise


def _rollback_database_swap(
    url: URL,
    previous_name: str,
    failed_name: str,
    swapped: bool,
    renamed_previous: bool,
) -> None:
    if not renamed_previous:
        return
    with _maintenance_engine(url) as engine:
        with engine.connect() as connection:
            _assert_maintenance_identity(connection)
            if swapped and _database_exists(connection, SANDBOX_DATABASE_NAME):
                if _database_exists(connection, failed_name):
                    raise RuntimeError("A failed sandbox recovery database already exists.")
                connection.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_catalog.pg_stat_activity "
                        "WHERE datname = :database AND pid <> pg_backend_pid()"
                    ),
                    {"database": SANDBOX_DATABASE_NAME},
                )
                connection.execute(
                    text(
                        f'ALTER DATABASE "{SANDBOX_DATABASE_NAME}" RENAME TO "{failed_name}"'
                    )
                )
            if not _database_exists(connection, SANDBOX_DATABASE_NAME):
                connection.execute(
                    text(f'ALTER DATABASE "{previous_name}" RENAME TO "{SANDBOX_DATABASE_NAME}"')
                )


def _assert_database_name(name: str, prefixes: tuple[str, ...]) -> None:
    if not name.startswith(prefixes) or not re.fullmatch(r"[a-z0-9_]{1,63}", name):
        raise ValueError("Refusing to modify a database outside the sandbox recovery namespace.")


def _database_exists(connection, name: str) -> bool:
    return bool(
        connection.execute(
            text("SELECT 1 FROM pg_catalog.pg_database WHERE datname = :name"),
            {"name": name},
        ).scalar_one_or_none()
    )


def _database_exists_by_url(url: URL, name: str) -> bool:
    with _maintenance_engine(url) as engine:
        with engine.connect() as connection:
            _assert_maintenance_identity(connection)
            return _database_exists(connection, name)


def _drop_database(
    url: URL,
    name: str,
    *,
    allowed_prefixes: tuple[str, ...] = (_VERIFY_PREFIX,),
) -> None:
    _assert_database_name(name, allowed_prefixes)
    with _maintenance_engine(url) as engine:
        with engine.connect() as connection:
            _assert_maintenance_identity(connection)
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


def _checkpoint_name(checkpoint_id: str) -> str:
    return _CHECKPOINT_PREFIX + checkpoint_id


def _checkpoint_checks(schema_matches: bool, data_matches: bool, prefix: str) -> list[SandboxCheck]:
    return [
        SandboxCheck(
            name=f"{prefix}_schema",
            status="passed" if schema_matches else "failed",
            detail="Compared the inspected schema fingerprint with the checkpoint baseline.",
        ),
        SandboxCheck(
            name=f"{prefix}_data",
            status="passed" if data_matches else "failed",
            detail="Compared canonical row content for every table in the bookstore schema.",
        ),
    ]


def _check(name: str, matched: bool, detail: str) -> SandboxCheck:
    return SandboxCheck(
        name=name,
        status="passed" if matched else "failed",
        detail=detail,
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()
