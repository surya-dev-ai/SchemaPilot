"""Persisted workflow and approval models. Target apply stays out of scope."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.report import SafetyReport
from app.schemas.rollback import RollbackStatus

WorkflowState = Literal[
    "report_ready",
    "approval_recorded",
    "blocked",
]
ApprovalDecision = Literal["recorded", "rejected"]


class WorkflowSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    source_id: str
    migration_id: str
    artifact_checksum: str
    schema_fingerprint: str
    state: WorkflowState
    eligible_for_review: bool
    report_stale: bool
    rollback_status: RollbackStatus
    created_at: str
    updated_at: str


class WorkflowListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflows: list[WorkflowSummary]


class ApprovalSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    migration_id: str
    artifact_checksum: str
    report_checksum: str
    target_identity: str
    decision: ApprovalDecision
    authentication_available: bool
    approver_identity: str | None
    limitation: str
    created_at: str


class AuditEventSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    event_type: str
    detail: dict[str, object]
    created_at: str


class WorkflowDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    source_id: str
    migration_id: str
    artifact_checksum: str
    artifact_status: str
    artifact_applied: Literal[False] = False
    schema_fingerprint: str
    state: WorkflowState
    report_checksum: str
    evidence_fingerprint: str
    report_stale: bool
    eligible_for_review: bool
    fully_reversible: bool
    rollback_status: RollbackStatus
    report: SafetyReport
    approvals: list[ApprovalSummary]
    audit_events: list[AuditEventSummary]
    created_at: str
    updated_at: str


class WorkflowPersistRequest(BaseModel):
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


class ApprovalCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_identity: str = Field(min_length=1, max_length=128)
    confirm: bool

    @field_validator("target_identity")
    @classmethod
    def target_identity_must_be_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("target_identity must not be blank")
        return stripped
