"""Persist artifact-bound pre-validation sandbox checkpoints."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from app.schemas.rollback import BaselineEvidence, RollbackReport, SnapshotRecoveryReport
from app.schemas.sandbox import SandboxRun

CHECKPOINT_SESSION_DIR = Path(__file__).resolve().parents[2] / "artifacts" / "sandbox-checkpoints"
_SESSION_ID = re.compile(r"^[0-9a-f]{32}$")
_CHECKPOINT_ID = re.compile(r"^[0-9a-f]{32}$")
_MIGRATION_ID = re.compile(r"^sp[0-9a-f]{12}$")
_FORMAT_VERSION = 1

CheckpointSessionState = Literal["ready", "running", "completed", "recovery_required"]


class SandboxCheckpointSession(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    migration_id: str
    artifact_checksum: str
    state: CheckpointSessionState
    checkpoint: SnapshotRecoveryReport
    baseline_evidence: BaselineEvidence | None = None
    validation_run: SandboxRun | None = None
    downgrade_report: RollbackReport | None = None
    error: str | None = None

    @model_validator(mode="after")
    def evidence_matches_session(self) -> SandboxCheckpointSession:
        if self.validation_run is not None:
            run = self.validation_run
            if (
                run.migration_id != self.migration_id
                or run.artifact_checksum != self.artifact_checksum
                or run.snapshot_session_id != self.session_id
                or run.pre_migration_snapshot_verified is not True
                or self.baseline_evidence is None
                or self.baseline_evidence.schema_fingerprint != run.schema_fingerprint
                or self.checkpoint.baseline_schema_fingerprint != run.schema_fingerprint
            ):
                raise ValueError("validation_run evidence does not match its checkpoint session")
        if self.downgrade_report is not None:
            report = self.downgrade_report
            if (
                self.validation_run is None
                or report.migration_id != self.migration_id
                or report.artifact_checksum != self.artifact_checksum
                or report.snapshot_session_id != self.session_id
                or report.source_id != self.validation_run.source_id
                or report.upgrade is None
                or report.upgrade.migration_id != self.validation_run.migration_id
                or report.upgrade.artifact_checksum != self.validation_run.artifact_checksum
                or report.upgrade.snapshot_session_id != self.session_id
                or (
                    not report.downgrade_executed
                    and report.status in {"exact_restoration", "partial_restoration"}
                )
            ):
                raise ValueError("downgrade evidence does not match its checkpoint session")
        return self


class SandboxCheckpointSessionError(Exception):
    """A pre-validation checkpoint is missing, corrupt, or in the wrong state."""


def assert_no_active_checkpoint_session(*, directory: Path | None = None) -> None:
    folder = directory or CHECKPOINT_SESSION_DIR
    if not folder.exists():
        return
    for path in folder.glob("*.json"):
        try:
            existing_payload = json.loads(path.read_text(encoding="utf-8"))["session"]
            existing = SandboxCheckpointSession.model_validate(existing_payload)
            existing = load_checkpoint_session(
                existing.session_id,
                existing.migration_id,
                existing.artifact_checksum,
                directory=folder,
            )
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise SandboxCheckpointSessionError(
                "An existing sandbox checkpoint session needs operator review."
            ) from exc
        if existing.state in {"ready", "running", "recovery_required"}:
            raise SandboxCheckpointSessionError(
                "A previous sandbox validation still needs rollback or recovery."
            )


def save_checkpoint_session(
    session: SandboxCheckpointSession,
    *,
    directory: Path | None = None,
) -> None:
    _validate_identity(session.session_id, session.migration_id, session.artifact_checksum)
    _validate_checkpoint_evidence(session.checkpoint, require_retained=True)
    folder = directory or CHECKPOINT_SESSION_DIR
    folder.mkdir(parents=True, exist_ok=True)
    assert_no_active_checkpoint_session(directory=folder)
    if (folder / f"{session.session_id}.json").exists():
        raise SandboxCheckpointSessionError("Sandbox checkpoint session identity already exists.")
    _write(session, folder)


def load_checkpoint_session(
    session_id: str,
    migration_id: str,
    artifact_checksum: str,
    *,
    directory: Path | None = None,
) -> SandboxCheckpointSession:
    _validate_identity(session_id, migration_id, artifact_checksum)
    path = (directory or CHECKPOINT_SESSION_DIR) / f"{session_id}.json"
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
        payload = envelope["session"]
        session = SandboxCheckpointSession.model_validate(payload)
        expected = "sha256:" + hashlib.sha256(_canonical(payload)).hexdigest()
        if (
            envelope.get("format_version") != _FORMAT_VERSION
            or envelope.get("payload_checksum") != expected
            or session.session_id != session_id
            or session.migration_id != migration_id
            or session.artifact_checksum != artifact_checksum
        ):
            raise SandboxCheckpointSessionError("Sandbox checkpoint session verification failed.")
        _validate_checkpoint_evidence(session.checkpoint)
        return session
    except SandboxCheckpointSessionError:
        raise
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise SandboxCheckpointSessionError(
            "Sandbox checkpoint session is unavailable or invalid."
        ) from exc


def find_active_checkpoint_session(
    migration_id: str | None = None,
    artifact_checksum: str | None = None,
    *,
    directory: Path | None = None,
) -> SandboxCheckpointSession | None:
    if (migration_id is None) != (artifact_checksum is None):
        raise SandboxCheckpointSessionError("Artifact identity is incomplete.")
    if migration_id is not None and artifact_checksum is not None:
        _validate_identity("0" * 32, migration_id, artifact_checksum)
    folder = directory or CHECKPOINT_SESSION_DIR
    if not folder.exists():
        return None
    matches: list[SandboxCheckpointSession] = []
    for path in folder.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))["session"]
            candidate = SandboxCheckpointSession.model_validate(payload)
            verified = load_checkpoint_session(
                candidate.session_id,
                candidate.migration_id,
                candidate.artifact_checksum,
                directory=folder,
            )
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise SandboxCheckpointSessionError(
                "An existing sandbox checkpoint session needs operator review."
            ) from exc
        if (
            (migration_id is None or verified.migration_id == migration_id)
            and (artifact_checksum is None or verified.artifact_checksum == artifact_checksum)
            and verified.state in {"ready", "running", "recovery_required"}
        ):
            matches.append(verified)
    if len(matches) > 1:
        raise SandboxCheckpointSessionError(
            "Multiple active checkpoint sessions need operator review."
        )
    return matches[0] if matches else None


def transition_checkpoint_session(
    session: SandboxCheckpointSession,
    *,
    expected_state: CheckpointSessionState,
    new_state: CheckpointSessionState,
    checkpoint: SnapshotRecoveryReport | None = None,
    error: str | None = None,
    directory: Path | None = None,
) -> SandboxCheckpointSession:
    if session.state != expected_state:
        raise SandboxCheckpointSessionError(
            "Sandbox checkpoint session is not in the expected state."
        )
    allowed_transitions = {
        "ready": {"running", "completed", "recovery_required"},
        "running": {"running", "completed", "recovery_required"},
        "recovery_required": {"running"},
        "completed": set(),
    }
    if new_state not in allowed_transitions[session.state]:
        raise SandboxCheckpointSessionError(
            "Sandbox checkpoint session state transition is not allowed."
        )
    next_checkpoint = checkpoint or session.checkpoint
    if (
        next_checkpoint.checkpoint_id != session.checkpoint.checkpoint_id
        or next_checkpoint.captured_at != session.checkpoint.captured_at
        or next_checkpoint.baseline_schema_fingerprint
        != session.checkpoint.baseline_schema_fingerprint
        or next_checkpoint.baseline_data_fingerprint
        != session.checkpoint.baseline_data_fingerprint
        or next_checkpoint.backup_status != session.checkpoint.backup_status
    ):
        raise SandboxCheckpointSessionError(
            "Sandbox checkpoint identity and baseline cannot change during a session."
        )
    _validate_checkpoint_evidence(next_checkpoint)
    if new_state == "completed" and (
        next_checkpoint.restore_status != "restore_verified"
        or next_checkpoint.schema_match is not True
        or next_checkpoint.data_match is not True
    ):
        raise SandboxCheckpointSessionError(
            "Completing a checkpoint session requires verified restoration evidence."
        )
    updated = session.model_copy(
        update={
            "state": new_state,
            "checkpoint": next_checkpoint,
            "error": error,
        }
    )
    _write(updated, directory or CHECKPOINT_SESSION_DIR)
    return updated


def save_validation_evidence(
    session: SandboxCheckpointSession,
    validation_run: SandboxRun,
    *,
    directory: Path | None = None,
) -> SandboxCheckpointSession:
    current = load_checkpoint_session(
        session.session_id,
        session.migration_id,
        session.artifact_checksum,
        directory=directory,
    )
    if current.state != "ready" or current.validation_run is not None:
        raise SandboxCheckpointSessionError("Sandbox validation evidence cannot be replaced.")
    updated = current.model_copy(update={"validation_run": validation_run})
    try:
        updated = SandboxCheckpointSession.model_validate(updated.model_dump(mode="python"))
    except ValueError as exc:
        raise SandboxCheckpointSessionError("Sandbox validation evidence is inconsistent.") from exc
    _write(updated, directory or CHECKPOINT_SESSION_DIR)
    return updated


def save_downgrade_evidence(
    session: SandboxCheckpointSession,
    report: RollbackReport,
    *,
    directory: Path | None = None,
) -> SandboxCheckpointSession:
    current = load_checkpoint_session(
        session.session_id,
        session.migration_id,
        session.artifact_checksum,
        directory=directory,
    )
    if (
        current.state != "ready"
        or current.validation_run is None
        or current.downgrade_report is not None
    ):
        raise SandboxCheckpointSessionError("Sandbox downgrade evidence cannot be replaced.")
    updated = current.model_copy(update={"downgrade_report": report})
    try:
        updated = SandboxCheckpointSession.model_validate(updated.model_dump(mode="python"))
    except ValueError as exc:
        raise SandboxCheckpointSessionError("Sandbox downgrade evidence is inconsistent.") from exc
    _write(updated, directory or CHECKPOINT_SESSION_DIR)
    return updated


def _write(session: SandboxCheckpointSession, folder: Path) -> None:
    payload = session.model_dump(mode="json")
    envelope = {
        "format_version": _FORMAT_VERSION,
        "payload_checksum": "sha256:" + hashlib.sha256(_canonical(payload)).hexdigest(),
        "session": payload,
    }
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{session.session_id}.json"
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=f".{session.session_id}.", suffix=".tmp", dir=folder, delete=False
        ) as stream:
            temporary = stream.name
            stream.write(_canonical(envelope))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except OSError as exc:
        if temporary:
            try:
                Path(temporary).unlink(missing_ok=True)
            except OSError:
                pass
        raise SandboxCheckpointSessionError(
            "Sandbox checkpoint session could not be saved."
        ) from exc


def _validate_identity(session_id: str, migration_id: str, checksum: str) -> None:
    if (
        _SESSION_ID.fullmatch(session_id) is None
        or _MIGRATION_ID.fullmatch(migration_id) is None
        or not checksum
    ):
        raise SandboxCheckpointSessionError("Sandbox checkpoint session identity is invalid.")


def _validate_checkpoint_evidence(
    checkpoint: SnapshotRecoveryReport,
    *,
    require_retained: bool = False,
) -> None:
    if (
        checkpoint.backup_status != "verified"
        or checkpoint.checkpoint_id is None
        or _CHECKPOINT_ID.fullmatch(checkpoint.checkpoint_id) is None
        or not checkpoint.baseline_schema_fingerprint
        or not checkpoint.baseline_data_fingerprint
        or checkpoint.schema_match is not True
        or checkpoint.data_match is not True
        or checkpoint.restored_schema_fingerprint
        != checkpoint.baseline_schema_fingerprint
        or checkpoint.restored_data_fingerprint != checkpoint.baseline_data_fingerprint
        or (require_retained and not checkpoint.checkpoint_retained)
    ):
        raise SandboxCheckpointSessionError(
            "A session requires complete verified checkpoint evidence."
        )


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
