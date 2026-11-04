"""Build a safety report from plan, risk, artifact, and sandbox evidence.

This module does not connect to a database and does not approve a migration.
"""

from app.schemas.artifacts import MigrationArtifact
from app.schemas.planning import MigrationProposal
from app.schemas.report import BaselineEvidenceSummary, SafetyReport
from app.schemas.risk import RiskAssessment
from app.schemas.rollback import BaselineEvidence, RollbackReport, SnapshotRecoveryReport
from app.schemas.sandbox import SandboxRun


def artifact_matches_plan(saved: MigrationArtifact, fresh: MigrationArtifact) -> bool:
    """True when the saved artifact is the one this plan and snapshot would generate."""

    return (
        saved.migration_id == fresh.migration_id
        and saved.checksum == fresh.checksum
        and saved.schema_fingerprint == fresh.schema_fingerprint
    )


def build_safety_report(
    proposal: MigrationProposal,
    assessment: RiskAssessment,
    artifact: MigrationArtifact,
    rollback: RollbackReport | None,
    *,
    artifact_matches: bool,
    sandbox_run: SandboxRun | None = None,
    baseline_evidence: BaselineEvidence | None = None,
    snapshot_recovery: SnapshotRecoveryReport | None = None,
    snapshot_session_id: str | None = None,
) -> SafetyReport:
    """Summarize evidence for a human reviewer. Approval stays false."""

    missing: list[str] = []
    blocking: list[str] = []
    if not artifact_matches:
        blocking.append("The saved artifact does not match this request and snapshot.")
    risk_policy_blocked = assessment.policy_blocked or any(
        finding.disposition == "policy_blocked" for finding in assessment.findings
    )
    if risk_policy_blocked and not artifact.sandbox_only:
        blocking.append("A risk finding is policy_blocked.")
    if any(finding.data_check == "not_run" for finding in assessment.findings):
        blocking.append("A required live row check is not_run and is not treated as passed.")
    if rollback is None:
        missing.append("rollback result")
        rollback_status = "not_verified"
        limitations: list[str] = []
        sandbox = sandbox_run
        preexisting_sandbox_recovery = None
    else:
        downgrade_executed = rollback.downgrade_executed
        rollback_status = rollback.status if downgrade_executed else "not_verified"
        limitations = list(rollback.data_loss_limitations)
        sandbox = rollback.upgrade or sandbox_run
        snapshot_recovery = snapshot_recovery or rollback.snapshot_recovery
        preexisting_sandbox_recovery = rollback.preexisting_sandbox_recovery
    baseline = (rollback.baseline if rollback is not None else None) or baseline_evidence
    if rollback is None:
        downgrade_executed = False
    if sandbox is None:
        missing.append("sandbox upgrade")
    if baseline is None:
        missing.append("baseline evidence")
    if not downgrade_executed:
        missing.append("migration downgrade")
    if rollback is not None:
        if rollback.sandbox_database == "" or rollback.sandbox_user == "":
            missing.append("sandbox identity")
        if rollback.downgrade_executed and rollback.status == "not_verified":
            blocking.append(rollback.error or "Rollback was not verified.")
        elif rollback.downgrade_executed and rollback.status == "failed":
            blocking.append(rollback.error or "Rollback failed.")
    if snapshot_recovery is None or snapshot_recovery.backup_status != "verified":
        missing.append("verified sandbox checkpoint")
    elif (
        snapshot_recovery.restore_status != "restore_verified"
        or snapshot_recovery.schema_match is not True
        or snapshot_recovery.data_match is not True
    ):
        blocking.append(
            snapshot_recovery.error or "Sandbox checkpoint restoration was not verified."
        )
    if (
        preexisting_sandbox_recovery is not None
        and preexisting_sandbox_recovery.restore_status != "restore_verified"
    ):
        blocking.append(
            preexisting_sandbox_recovery.error
            or "Pre-existing sandbox state restoration was not verified."
        )
    if sandbox is not None and (
        sandbox.result != "passed"
        or sandbox.upgrade_applied is not True
        or sandbox.migration_id != artifact.migration_id
        or sandbox.artifact_checksum != artifact.checksum
        or (snapshot_session_id is not None and sandbox.snapshot_session_id != snapshot_session_id)
    ):
        blocking.append(
            "Sandbox validation evidence does not match the saved artifact and session."
        )
    if baseline is not None and baseline.schema_fingerprint != artifact.schema_fingerprint:
        blocking.append("Baseline evidence does not match the saved artifact schema.")
    fully_reversible = rollback_status == "exact_restoration"
    eligible = (
        artifact_matches
        and not blocking
        and not missing
        and rollback_status in {"exact_restoration", "partial_restoration"}
        and sandbox is not None
        and sandbox.result == "passed"
        and sandbox.upgrade_applied
        and sandbox.migration_id == artifact.migration_id
        and sandbox.artifact_checksum == artifact.checksum
        and downgrade_executed
        and baseline is not None
        and snapshot_recovery is not None
        and snapshot_recovery.restore_status == "restore_verified"
        and snapshot_recovery.schema_match is True
        and snapshot_recovery.data_match is True
    )
    return SafetyReport(
        request=proposal.request,
        interpreted_intent=proposal.summary,
        operations=list(proposal.operations),
        assumptions=list(proposal.assumptions),
        source_id=artifact.source_id,
        schema_fingerprint=artifact.schema_fingerprint,
        migration_id=artifact.migration_id,
        artifact_checksum=artifact.checksum,
        artifact_status=artifact.status,
        risk_findings=list(assessment.findings),
        sandbox=sandbox,
        baseline_evidence=(
            BaselineEvidenceSummary(
                schema_fingerprint=baseline.schema_fingerprint,
                tables=list(baseline.tables),
                row_counts=dict(baseline.row_counts),
            )
            if baseline is not None
            else None
        ),
        downgrade_executed=downgrade_executed,
        rollback_status=rollback_status,
        snapshot_recovery=snapshot_recovery,
        preexisting_sandbox_recovery=preexisting_sandbox_recovery,
        snapshot_session_id=(
            rollback.snapshot_session_id if rollback is not None else snapshot_session_id
        ),
        data_loss_limitations=limitations,
        missing_evidence=missing,
        blocking_reasons=blocking,
        eligible_for_review=eligible,
        approved=False,
        applied=False,
        fully_reversible=fully_reversible,
    )
