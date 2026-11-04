"""Durably store verified sandbox evidence without rerunning destructive steps."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from app.schemas.rollback import RollbackReport

ROLLBACK_EVIDENCE_DIR = Path(__file__).resolve().parents[2] / "artifacts" / "rollback-evidence"
_MIGRATION_ID = re.compile(r"^sp[0-9a-f]{12}$")
_SESSION_ID = re.compile(r"^[0-9a-f]{32}$")
_FORMAT_VERSION = 1


class RollbackEvidenceError(Exception):
    """Stored sandbox evidence is missing, invalid, or bound to another artifact."""


def save_rollback_evidence(
    report: RollbackReport,
    *,
    directory: Path | None = None,
) -> None:
    if (
        _MIGRATION_ID.fullmatch(report.migration_id) is None
        or not report.artifact_checksum
        or report.snapshot_session_id is None
        or _SESSION_ID.fullmatch(report.snapshot_session_id) is None
    ):
        raise RollbackEvidenceError("Rollback evidence identity is invalid.")
    payload = report.model_dump(mode="json")
    encoded_payload = _canonical(payload)
    envelope = {
        "format_version": _FORMAT_VERSION,
        "artifact_checksum": report.artifact_checksum,
        "payload_checksum": "sha256:" + hashlib.sha256(encoded_payload).hexdigest(),
        "report": payload,
    }
    content = _canonical(envelope)
    folder = directory or ROLLBACK_EVIDENCE_DIR
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{report.migration_id}-{report.snapshot_session_id}.json"
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{report.migration_id}.",
            suffix=".tmp",
            dir=folder,
            delete=False,
        ) as stream:
            temporary = stream.name
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except OSError as exc:
        if temporary:
            try:
                Path(temporary).unlink(missing_ok=True)
            except OSError:
                pass
        raise RollbackEvidenceError("Rollback evidence could not be saved.") from exc


def load_rollback_evidence(
    migration_id: str,
    artifact_checksum: str,
    *,
    session_id: str | None = None,
    directory: Path | None = None,
) -> RollbackReport | None:
    if (
        _MIGRATION_ID.fullmatch(migration_id) is None
        or not artifact_checksum
        or session_id is None
        or _SESSION_ID.fullmatch(session_id) is None
    ):
        raise RollbackEvidenceError("Rollback evidence identity is invalid.")
    path = (directory or ROLLBACK_EVIDENCE_DIR) / f"{migration_id}-{session_id}.json"
    if not path.is_file():
        return None
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
        if envelope.get("format_version") != _FORMAT_VERSION:
            raise RollbackEvidenceError("Rollback evidence format is unsupported.")
        payload = envelope["report"]
        report = RollbackReport.model_validate(payload)
        digest = "sha256:" + hashlib.sha256(_canonical(payload)).hexdigest()
        if (
            report.migration_id != migration_id
            or report.snapshot_session_id != session_id
            or report.artifact_checksum != artifact_checksum
            or envelope.get("artifact_checksum") != artifact_checksum
            or envelope.get("payload_checksum") != digest
        ):
            raise RollbackEvidenceError("Rollback evidence checksum or artifact binding differs.")
        return report
    except RollbackEvidenceError:
        raise
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise RollbackEvidenceError("Stored rollback evidence is invalid.") from exc


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
