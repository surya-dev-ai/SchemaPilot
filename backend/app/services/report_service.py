"""Build a safety report from plan, risk, artifact, and sandbox evidence.

This module does not connect to a database and does not approve a migration.
"""

from app.schemas.artifacts import MigrationArtifact
from app.schemas.planning import MigrationProposal
from app.schemas.report import SafetyReport
from app.schemas.risk import RiskAssessment
from app.schemas.rollback import RollbackReport


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
) -> SafetyReport:
    """Summarize evidence for a human reviewer. Approval stays false."""

    missing: list[str] = []
    blocking: list[str] = []
    if not artifact_matches:
        blocking.append("The saved artifact does not match this request and snapshot.")
    if assessment.policy_blocked or any(
        finding.disposition == "policy_blocked" for finding in assessment.findings
    ):
        blocking.append("A risk finding is policy_blocked.")
    if any(finding.data_check == "not_run" for finding in assessment.findings):
        blocking.append("A required live row check is not_run and is not treated as passed.")
    if rollback is None:
        missing.append("sandbox upgrade")
        missing.append("rollback result")
        rollback_status = "not_verified"
        limitations: list[str] = []
        sandbox = None
    else:
        rollback_status = rollback.status
        limitations = list(rollback.data_loss_limitations)
        sandbox = rollback.upgrade
        if rollback.upgrade is None:
            missing.append("sandbox upgrade")
        if rollback.baseline is None:
            missing.append("baseline evidence")
        if rollback.sandbox_database == "" or rollback.sandbox_user == "":
            missing.append("sandbox identity")
        if rollback.status == "not_verified":
            blocking.append(rollback.error or "Rollback was not verified.")
        elif rollback.status == "failed":
            blocking.append(rollback.error or "Rollback failed.")
    fully_reversible = rollback_status == "exact_restoration"
    eligible = (
        artifact_matches
        and not blocking
        and not missing
        and rollback_status in {"exact_restoration", "partial_restoration"}
        and sandbox is not None
        and sandbox.result == "passed"
        and sandbox.upgrade_applied
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
        rollback_status=rollback_status,
        data_loss_limitations=limitations,
        missing_evidence=missing,
        blocking_reasons=blocking,
        eligible_for_review=eligible,
        approved=False,
        applied=False,
        fully_reversible=fully_reversible,
    )
