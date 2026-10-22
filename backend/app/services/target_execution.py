"""Target execution gate. Target apply stays disabled in Phase 12.

This module documents the mandatory preflight. It does not apply SQL and has no
API route. Callers must fail closed when any required condition is missing.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.services.auth import AuthenticatedPrincipal, authentication_is_available


class TargetExecutionRejected(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class TargetExecutionPreflight:
    migration_id: str
    artifact_checksum: str
    report_checksum: str
    target_identity: str
    schema_fingerprint: str
    rollback_status: str
    eligible_for_review: bool
    report_stale: bool
    policy_blocked: bool
    missing_evidence: tuple[str, ...]
    not_run_checks: tuple[str, ...]
    sandbox_upgrade_passed: bool
    approval_present: bool
    approval_target_identity: str | None
    approval_artifact_checksum: str | None
    approval_report_checksum: str | None
    authentication_available: bool
    principal: AuthenticatedPrincipal | None


def assert_target_execution_allowed(
    settings: Settings,
    preflight: TargetExecutionPreflight,
) -> None:
    """Refuse target execution unless every required gate passes.

    Phase 12 keeps target execution disabled by default. Even when the flag is
    flipped, authentication and live evidence gates still fail closed.
    """

    if not settings.target_execution_enabled:
        raise TargetExecutionRejected(
            "target_execution_disabled",
            "Target execution is disabled. SCHEMAPILOT_TARGET_EXECUTION_ENABLED remains false.",
        )
    if not authentication_is_available(settings) or preflight.principal is None:
        raise TargetExecutionRejected(
            "authentication_unavailable",
            "Target execution requires a verified authenticated approver.",
        )
    if not settings.database_configured(settings.target_database_url):
        raise TargetExecutionRejected(
            "target_not_configured",
            "Target database URL is missing. Refusing to infer a target from source or sandbox.",
        )
    target_url = (settings.target_database_url or "").strip()
    app_url = (settings.app_database_url or "").strip()
    sandbox_url = (settings.sandbox_database_url or "").strip()
    demo_url = (settings.demo_database_url or "").strip()
    if target_url and target_url in {app_url, sandbox_url, demo_url}:
        raise TargetExecutionRejected(
            "target_identity_rejected",
            "Target URL must be distinct from application, sandbox, and demo databases.",
        )
    if preflight.report_stale or not preflight.eligible_for_review:
        raise TargetExecutionRejected(
            "stale_or_ineligible",
            "Stale evidence or ineligible review state blocks target execution.",
        )
    if preflight.policy_blocked or preflight.missing_evidence or preflight.not_run_checks:
        raise TargetExecutionRejected(
            "policy_or_evidence_blocked",
            "Policy blockers, missing evidence, or unresolved not_run checks block execution.",
        )
    if preflight.rollback_status == "not_verified":
        raise TargetExecutionRejected(
            "rollback_not_verified",
            "not_verified rollback evidence blocks target execution.",
        )
    if preflight.rollback_status not in {"exact_restoration", "partial_restoration"}:
        raise TargetExecutionRejected(
            "rollback_not_verified",
            "Rollback evidence must be exact_restoration or partial_restoration.",
        )
    if not preflight.sandbox_upgrade_passed:
        raise TargetExecutionRejected(
            "sandbox_evidence_missing",
            "Real sandbox upgrade evidence is required before target execution.",
        )
    if not preflight.approval_present:
        raise TargetExecutionRejected(
            "approval_required",
            "A persisted approval bound to artifact, report, and target is required.",
        )
    if preflight.approval_target_identity != preflight.target_identity:
        raise TargetExecutionRejected(
            "target_identity_mismatch",
            "Execution target identity must match the approved target identity.",
        )
    if preflight.approval_artifact_checksum != preflight.artifact_checksum:
        raise TargetExecutionRejected(
            "artifact_checksum_mismatch",
            "Approval is not bound to this artifact checksum.",
        )
    if preflight.approval_report_checksum != preflight.report_checksum:
        raise TargetExecutionRejected(
            "report_checksum_mismatch",
            "Approval is not bound to this report checksum.",
        )
    # Phase 12 never reaches a successful allow: authentication stays unavailable.
    raise TargetExecutionRejected(
        "target_execution_not_implemented",
        "Target execution is not implemented. Preflight refused to touch any target.",
    )
