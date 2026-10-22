"""Risk findings. These models do not contain executable SQL."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.schemas.planning import PlanStatus

RiskSeverity = Literal["low", "medium", "high"]
RiskDisposition = Literal["info", "warning", "high_risk", "policy_blocked"]
Reversibility = Literal["reversible", "irreversible", "unknown"]
DataCheck = Literal["not_required", "not_run"]
EligibilityReason = Literal[
    "eligible",
    "plan_not_proposed",
    "policy_blocked",
    "data_check_not_run",
    "no_operations",
]


class RiskFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    rule_id: str
    severity: RiskSeverity
    disposition: RiskDisposition
    operation_id: str | None = None
    affected_objects: list[str]
    evidence: list[str]
    explanation: str
    mitigation: str
    reversibility: Reversibility
    data_check: DataCheck


class RiskAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    schema_name: str
    schema_fingerprint: str
    plan_status: PlanStatus
    findings: list[RiskFinding]
    policy_blocked: bool
    artifact_eligible: bool
    eligibility_reason: EligibilityReason
