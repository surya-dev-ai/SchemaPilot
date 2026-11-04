"""Rollback and safety-report routes. They do not approve or apply a target."""

import tempfile
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.exc import OperationalError

from app.core.config import Settings, UnsafeDatabaseConfigurationError
from app.schemas.report import SafetyReport, SafetyReportRequest
from app.schemas.rollback import RollbackReport
from app.schemas.sandbox import SandboxRunRequest
from app.services.llm.assisted_planner import create_proposal
from app.services.migration_generator import ARTIFACTS_DIR, generate_migration
from app.services.report_service import artifact_matches_plan, build_safety_report
from app.services.risk_engine import assess_risk
from app.services.rollback_evidence_store import (
    RollbackEvidenceError,
    load_rollback_evidence,
    save_rollback_evidence,
)
from app.services.rollback_tester import downgrade_verified_upgrade
from app.services.sandbox_checkpoint_store import (
    SandboxCheckpointSessionError,
    load_checkpoint_session,
    save_downgrade_evidence,
    transition_checkpoint_session,
)
from app.services.sandbox_manager import SandboxRejected, load_verified_artifact
from app.services.sandbox_snapshots import restore_verified_checkpoint, sandbox_lifecycle_lock
from app.services.schema_inspector import inspect_sandbox, inspect_source
from app.services.source_manager import (
    BOOKSTORE_SOURCE_ID,
    SANDBOX_SOURCE_ID,
    SourceNotConfiguredError,
    SourceNotFoundError,
    SourceNotReadOnlyError,
    SourceUnavailableError,
    UnexpectedSourceDatabaseError,
)

router = APIRouter(tags=["safety"])


@router.post(
    "/sources/{source_id}/artifacts/{migration_id}/downgrade",
    response_model=RollbackReport,
)
def run_sandbox_downgrade(
    source_id: str,
    migration_id: str,
    body: SandboxRunRequest,
    request: Request,
) -> RollbackReport:
    _require_source(source_id)
    if source_id != SANDBOX_SOURCE_ID:
        raise HTTPException(status_code=409, detail={"error": "sandbox_source_required"}) from None
    if body.confirm is not True or body.snapshot_session_id is None:
        raise HTTPException(
            status_code=409,
            detail={"error": "validated_sandbox_session_required"},
        ) from None
    settings: Settings = request.app.state.settings
    try:
        artifact = load_verified_artifact(ARTIFACTS_DIR, migration_id)
        if artifact.source_id != SANDBOX_SOURCE_ID:
            raise SandboxRejected("artifact_source_mismatch", "The artifact is not sandbox-only.")
        with sandbox_lifecycle_lock(settings):
            session = load_checkpoint_session(
                body.snapshot_session_id,
                migration_id,
                artifact.checksum,
            )
            if session.state != "ready" or session.validation_run is None:
                raise HTTPException(
                    status_code=409,
                    detail={"error": "passed_sandbox_validation_required"},
                ) from None
            if session.downgrade_report is not None:
                raise HTTPException(
                    status_code=409,
                    detail={"error": "sandbox_downgrade_already_recorded"},
                ) from None
            if session.validation_run.result != "passed":
                raise HTTPException(
                    status_code=409,
                    detail={"error": "passed_sandbox_validation_required"},
                ) from None
            report = downgrade_verified_upgrade(
                settings,
                migration_id,
                ARTIFACTS_DIR,
                session.validation_run,
                session.baseline_evidence,
            ).model_copy(update={"snapshot_session_id": session.session_id})
            session = save_downgrade_evidence(session, report)
            save_rollback_evidence(report)
            return report
    except UnsafeDatabaseConfigurationError as exc:
        raise _configuration_error(exc) from None
    except SandboxCheckpointSessionError as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": "pre_migration_snapshot_session_invalid", "message": str(exc)},
        ) from None
    except SandboxRejected as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": exc.code, "message": exc.message},
        ) from None
    except OperationalError:
        raise HTTPException(status_code=503, detail={"error": "sandbox_unavailable"}) from None
    except RollbackEvidenceError as exc:
        raise HTTPException(
            status_code=500,
            detail={"error": "rollback_evidence_store_failed", "message": str(exc)},
        ) from None


@router.post(
    "/sources/{source_id}/artifacts/{migration_id}/rollback",
    response_model=RollbackReport,
)
def run_rollback(
    source_id: str,
    migration_id: str,
    body: SandboxRunRequest,
    request: Request,
) -> RollbackReport:
    _require_source(source_id)
    if body.confirm is not True:
        raise HTTPException(status_code=409, detail={"error": "sandbox_not_confirmed"}) from None
    if body.snapshot_session_id is None:
        raise HTTPException(
            status_code=409,
            detail={"error": "pre_migration_snapshot_session_required"},
        ) from None
    settings: Settings = request.app.state.settings
    try:
        artifact = load_verified_artifact(ARTIFACTS_DIR, migration_id)
        with sandbox_lifecycle_lock(settings):
            session = load_checkpoint_session(
                body.snapshot_session_id,
                migration_id,
                artifact.checksum,
            )
            if artifact.source_id != source_id:
                raise SandboxRejected(
                    "artifact_id_mismatch",
                    "The artifact was not generated from the requested database source.",
                )
            if session.state not in {"ready", "running", "recovery_required"}:
                raise HTTPException(
                    status_code=409,
                    detail={"error": "pre_migration_snapshot_session_already_used"},
                ) from None
            session = transition_checkpoint_session(
                session,
                expected_state=session.state,
                new_state="running",
            )
            try:
                try:
                    restored = restore_verified_checkpoint(
                        settings,
                        session.checkpoint,
                        _lifecycle_lock_held=True,
                    )
                except Exception:
                    restored = session.checkpoint.model_copy(
                        update={
                            "restore_status": "verification_incomplete",
                            "error": "Sandbox snapshot restore could not be completed or verified.",
                        }
                    )
                verified = (
                    restored.restore_status == "restore_verified"
                    and restored.schema_match is True
                    and restored.data_match is True
                )
                report = RollbackReport(
                    migration_id=migration_id,
                    artifact_checksum=artifact.checksum,
                    source_id=source_id,
                    schema_fingerprint=(
                        session.checkpoint.baseline_schema_fingerprint or ""
                    ),
                    sandbox_database="schemapilot_sandbox",
                    sandbox_user="schemapilot_sandbox",
                    postgres_version="not queried",
                    started_at=_now(),
                    finished_at=_now(),
                    status=(
                        "exact_restoration"
                        if verified
                        else "failed"
                        if restored.restore_status in {"restore_failed", "verification_incomplete"}
                        else "not_verified"
                    ),
                    downgrade_executed=False,
                    schema_matches_baseline=restored.schema_match,
                    data_checks=restored.verification_checks,
                    data_loss_limitations=[
                        "Migration downgrade was not executed; "
                        "sandbox snapshot restoration was used."
                    ],
                    snapshot_recovery=restored,
                    preexisting_sandbox_recovery=restored,
                    snapshot_session_id=session.session_id,
                    error=(
                        None
                        if verified
                        else restored.error or "Sandbox restore is not verified."
                    ),
                )
                if session.downgrade_report is not None:
                    report = session.downgrade_report.model_copy(
                        update={
                            "snapshot_recovery": restored,
                            "preexisting_sandbox_recovery": restored,
                        }
                    )
                save_rollback_evidence(report)
                state = (
                    "completed"
                    if verified
                    else "recovery_required"
                )
                transition_checkpoint_session(
                    session,
                    expected_state="running",
                    new_state=state,
                    checkpoint=restored,
                    error=(
                        None
                        if state == "completed"
                        else "Original sandbox restore is not verified."
                    ),
                )
                return report
            except Exception:
                transition_checkpoint_session(
                    session,
                    expected_state="running",
                    new_state="recovery_required",
                    error="Rollback did not finish with verified original-state restoration.",
                )
                raise
    except UnsafeDatabaseConfigurationError as exc:
        raise _configuration_error(exc) from None
    except SandboxCheckpointSessionError as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": "pre_migration_snapshot_session_invalid", "message": str(exc)},
        ) from None
    except SandboxRejected as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": exc.code, "message": exc.message},
        ) from None
    except OperationalError:
        raise HTTPException(status_code=503, detail={"error": "sandbox_unavailable"}) from None
    except RollbackEvidenceError as exc:
        raise HTTPException(
            status_code=500,
            detail={"error": "rollback_evidence_store_failed", "message": str(exc)},
        ) from None


@router.post(
    "/sources/{source_id}/artifacts/{migration_id}/report",
    response_model=SafetyReport,
)
def create_safety_report(
    source_id: str,
    migration_id: str,
    body: SafetyReportRequest,
    request: Request,
) -> SafetyReport:
    _require_source(source_id)
    if body.confirm is not True:
        raise HTTPException(status_code=409, detail={"error": "sandbox_not_confirmed"}) from None
    settings: Settings = request.app.state.settings
    try:
        snapshot = (
            inspect_sandbox(settings)
            if source_id == SANDBOX_SOURCE_ID
            else inspect_source(settings, source_id)
        )
    except SourceNotFoundError:
        raise HTTPException(status_code=404, detail={"error": "unknown_source"}) from None
    except SourceNotConfiguredError:
        raise HTTPException(status_code=409, detail={"error": "source_not_configured"}) from None
    except SourceNotReadOnlyError:
        raise HTTPException(status_code=409, detail={"error": "source_not_read_only"}) from None
    except UnexpectedSourceDatabaseError:
        raise HTTPException(status_code=409, detail={"error": "unexpected_database"}) from None
    except SourceUnavailableError:
        raise HTTPException(status_code=503, detail={"error": "source_unavailable"}) from None
    provider = getattr(request.app.state, "llm_provider", None)
    proposal = create_proposal(
        settings,
        snapshot,
        body.request,
        use_llm=body.use_llm,
        provider=provider,
    )
    assessment = assess_risk(snapshot, proposal)
    try:
        saved = load_verified_artifact(ARTIFACTS_DIR, migration_id)
    except SandboxRejected as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": exc.code, "message": exc.message},
        ) from None
    if saved.source_id != source_id:
        raise HTTPException(
            status_code=409,
            detail={"error": "artifact_source_mismatch"},
        ) from None
    with tempfile.TemporaryDirectory() as temporary:
        fresh = generate_migration(snapshot, proposal, assessment, Path(temporary))
    matches = artifact_matches_plan(saved, fresh)
    rollback = None
    sandbox_run = None
    baseline_evidence = None
    snapshot_recovery = None
    if matches and body.snapshot_session_id is not None:
        try:
            session = load_checkpoint_session(
                body.snapshot_session_id,
                migration_id,
                saved.checksum,
            )
            sandbox_run = session.validation_run
            baseline_evidence = session.baseline_evidence
            snapshot_recovery = (
                session.checkpoint
                if session.checkpoint.restore_status == "restore_verified"
                else None
            )
            rollback = load_rollback_evidence(
                migration_id,
                saved.checksum,
                session_id=body.snapshot_session_id,
            )
            if session.downgrade_report is not None:
                rollback = session.downgrade_report.model_copy(
                    update={"snapshot_recovery": snapshot_recovery}
                )
        except UnsafeDatabaseConfigurationError as exc:
            raise _configuration_error(exc) from None
        except SandboxCheckpointSessionError as exc:
            raise HTTPException(
                status_code=409,
                detail={"error": "sandbox_checkpoint_evidence_invalid", "message": str(exc)},
            ) from None
        except RollbackEvidenceError as exc:
            raise HTTPException(
                status_code=409,
                detail={"error": "rollback_evidence_invalid", "message": str(exc)},
            ) from None
    return build_safety_report(
        proposal,
        assessment,
        saved,
        rollback,
        artifact_matches=matches,
        sandbox_run=sandbox_run,
        baseline_evidence=baseline_evidence,
        snapshot_recovery=snapshot_recovery,
        snapshot_session_id=body.snapshot_session_id,
    )


def _require_source(source_id: str) -> None:
    if source_id not in {BOOKSTORE_SOURCE_ID, SANDBOX_SOURCE_ID}:
        raise HTTPException(status_code=404, detail={"error": "unknown_source"}) from None


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _configuration_error(exc: UnsafeDatabaseConfigurationError) -> HTTPException:
    message = str(exc)
    if message.startswith("Refusing to run the sandbox"):
        code = "sandbox_not_enabled"
    elif "credentials" in message or "not schemapilot_sandbox" in message:
        code = "sandbox_identity_rejected"
    else:
        code = "sandbox_not_configured"
    return HTTPException(status_code=409, detail={"error": code, "message": message})
