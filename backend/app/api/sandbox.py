"""Sandbox routes. They do not open the source or target database."""

import uuid

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.exc import OperationalError

from app.core.config import Settings, UnsafeDatabaseConfigurationError
from app.schemas.rollback import SnapshotRecoveryReport
from app.schemas.sandbox import (
    SandboxCheckpointSessionStatus,
    SandboxRun,
    SandboxRunRequest,
)
from app.services.migration_generator import ARTIFACTS_DIR
from app.services.rollback_tester import read_baseline_evidence
from app.services.sandbox_checkpoint_store import (
    SandboxCheckpointSession,
    SandboxCheckpointSessionError,
    assert_no_active_checkpoint_session,
    find_active_checkpoint_session,
    save_checkpoint_session,
    save_validation_evidence,
    transition_checkpoint_session,
)
from app.services.sandbox_manager import (
    SandboxRejected,
    SandboxUnavailable,
    load_verified_artifact,
    run_sandbox,
)
from app.services.sandbox_snapshots import (
    create_verified_checkpoint,
    restore_verified_checkpoint,
    sandbox_lifecycle_lock,
)
from app.services.schema_inspector import inspect_sandbox
from app.services.source_manager import (
    BOOKSTORE_SOURCE_ID,
    SANDBOX_SOURCE_ID,
    SourceNotConfiguredError,
    SourceUnavailableError,
)

router = APIRouter(tags=["sandbox"])


@router.get(
    "/sources/{source_id}/sandbox-session",
    response_model=SandboxCheckpointSessionStatus,
)
def get_sandbox_checkpoint_session(
    source_id: str,
) -> SandboxCheckpointSessionStatus:
    if source_id not in {BOOKSTORE_SOURCE_ID, SANDBOX_SOURCE_ID}:
        raise HTTPException(status_code=404, detail={"error": "unknown_source"}) from None
    try:
        session = find_active_checkpoint_session()
        if session is None:
            return SandboxCheckpointSessionStatus(active=False)
        artifact = load_verified_artifact(ARTIFACTS_DIR, session.migration_id)
        if artifact.checksum != session.artifact_checksum or artifact.source_id != source_id:
            raise SandboxCheckpointSessionError("Checkpoint session artifact no longer matches.")
        return SandboxCheckpointSessionStatus(
            active=True,
            migration_id=session.migration_id,
            snapshot_session_id=session.session_id,
            state=session.state,
            checkpoint_verified=session.checkpoint.backup_status == "verified",
            restore_status=session.checkpoint.restore_status,
            validation_run=session.validation_run,
            baseline_evidence=(
                {
                    "schema_fingerprint": session.baseline_evidence.schema_fingerprint,
                    "tables": session.baseline_evidence.tables,
                    "row_counts": session.baseline_evidence.row_counts,
                }
                if session.baseline_evidence is not None
                else None
            ),
            downgrade_report=(
                {
                    "migration_id": session.downgrade_report.migration_id,
                    "status": session.downgrade_report.status,
                    "downgrade_executed": session.downgrade_report.downgrade_executed,
                    "schema_matches_baseline": session.downgrade_report.schema_matches_baseline,
                    "data_checks": [
                        check.model_dump(mode="json")
                        for check in session.downgrade_report.data_checks
                    ],
                    "data_loss_limitations": session.downgrade_report.data_loss_limitations,
                    "error": session.downgrade_report.error,
                    "snapshot_session_id": session.session_id,
                }
                if session.downgrade_report is not None
                else None
            ),
            error=session.error,
        )
    except SandboxRejected as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": exc.code, "message": exc.message},
        ) from None
    except SandboxCheckpointSessionError:
        raise HTTPException(
            status_code=409,
            detail={"error": "sandbox_checkpoint_recovery_required"},
        ) from None


@router.post(
    "/sources/{source_id}/artifacts/{migration_id}/sandbox",
    response_model=SandboxRun,
)
def run_artifact_in_sandbox(
    source_id: str,
    migration_id: str,
    body: SandboxRunRequest,
    request: Request,
) -> SandboxRun:
    if source_id not in {BOOKSTORE_SOURCE_ID, SANDBOX_SOURCE_ID}:
        raise HTTPException(status_code=404, detail={"error": "unknown_source"}) from None
    if body.confirm is not True:
        raise HTTPException(status_code=409, detail={"error": "sandbox_not_confirmed"}) from None
    settings: Settings = request.app.state.settings
    try:
        artifact = load_verified_artifact(ARTIFACTS_DIR, migration_id)
        if artifact.source_id != source_id:
            raise SandboxRejected(
                "artifact_id_mismatch",
                "The artifact was not generated from the requested database source.",
            )
        with sandbox_lifecycle_lock(settings):
            assert_no_active_checkpoint_session()
            baseline_snapshot = inspect_sandbox(settings)
            if baseline_snapshot.fingerprint != artifact.schema_fingerprint:
                raise HTTPException(
                    status_code=409,
                    detail={"error": "artifact_schema_mismatch"},
                ) from None
            baseline_evidence = read_baseline_evidence(settings, baseline_snapshot)
            checkpoint = create_verified_checkpoint(
                settings,
                None,
                _lifecycle_lock_held=True,
            )
            if checkpoint.backup_status != "verified":
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": "pre_migration_snapshot_unverified",
                        "message": checkpoint.error
                        or "The sandbox state could not be protected before validation.",
                    },
                )
            session_id = uuid.uuid4().hex
            session = SandboxCheckpointSession(
                session_id=session_id,
                migration_id=migration_id,
                artifact_checksum=artifact.checksum,
                state="ready",
                checkpoint=checkpoint,
                baseline_evidence=baseline_evidence,
            )
            save_checkpoint_session(session)
            try:
                run = run_sandbox(
                    settings,
                    migration_id,
                    _lifecycle_lock_held=True,
                )
            except Exception:
                restored = _safe_restore(settings, checkpoint)
                state = (
                    "completed"
                    if restored.restore_status == "restore_verified"
                    else "recovery_required"
                )
                transition_checkpoint_session(
                    session,
                    expected_state="ready",
                    new_state=state,
                    checkpoint=restored,
                    error=(
                        None
                        if state == "completed"
                        else "Pre-validation state restore is not verified."
                    ),
                )
                raise HTTPException(
                    status_code=503,
                    detail={
                        "error": "sandbox_unavailable",
                        "pre_migration_restore": restored.restore_status,
                        "snapshot_session_id": session_id,
                    },
                ) from None
            recorded_run = run.model_copy(
                update={
                    "snapshot_session_id": session_id,
                    "pre_migration_snapshot_verified": True,
                }
            )
            save_validation_evidence(session, recorded_run)
            return recorded_run
    except SandboxRejected as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": exc.code, "message": exc.message},
        ) from None
    except SandboxUnavailable:
        raise HTTPException(status_code=503, detail={"error": "sandbox_unavailable"}) from None
    except SourceNotConfiguredError:
        raise HTTPException(status_code=409, detail={"error": "sandbox_not_configured"}) from None
    except SourceUnavailableError:
        raise HTTPException(status_code=503, detail={"error": "sandbox_unavailable"}) from None
    except OperationalError:
        raise HTTPException(status_code=503, detail={"error": "sandbox_unavailable"}) from None
    except UnsafeDatabaseConfigurationError as exc:
        message = str(exc)
        if message.startswith("Refusing to run the sandbox"):
            code = "sandbox_not_enabled"
        elif "credentials" in message or "not schemapilot_sandbox" in message:
            code = "sandbox_identity_rejected"
        else:
            code = "sandbox_not_configured"
        raise HTTPException(
            status_code=409,
            detail={"error": code, "message": message},
        ) from None
    except SandboxCheckpointSessionError:
        raise HTTPException(
            status_code=500,
            detail={"error": "pre_migration_snapshot_evidence_unavailable"},
        ) from None


def _safe_restore(settings: Settings, checkpoint: SnapshotRecoveryReport) -> SnapshotRecoveryReport:
    try:
        return restore_verified_checkpoint(settings, checkpoint, _lifecycle_lock_held=True)
    except Exception:
        return checkpoint.model_copy(
            update={
                "restore_status": "verification_incomplete",
                "error": "Sandbox snapshot restore could not be completed or verified.",
            }
        )
