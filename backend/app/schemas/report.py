"""Safety reports. Review eligibility is not approval or target application."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.planning import Assumption, PlanOperation
from app.schemas.risk import RiskFinding
from app.schemas.rollback import RollbackStatus
from app.schemas.sandbox import SandboxRun


class SafetyReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request: str = Field(min_length=1, max_length=2000)
    confirm: bool
    use_llm: bool = False

    @field_validator("request")
    @classmethod
    def request_must_contain_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("request must not be blank")
        return stripped


class SafetyReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request: str
    interpreted_intent: str
    operations: list[PlanOperation]
    assumptions: list[Assumption]
    source_id: str
    schema_fingerprint: str
    migration_id: str
    artifact_checksum: str
    artifact_status: str
    risk_findings: list[RiskFinding]
    sandbox: SandboxRun | None = None
    rollback_status: RollbackStatus
    data_loss_limitations: list[str]
    missing_evidence: list[str]
    blocking_reasons: list[str]
    eligible_for_review: bool
    approved: Literal[False] = False
    applied: Literal[False] = False
    fully_reversible: bool
