"""Structured migration proposals. These models do not contain executable SQL."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

OperationKind = Literal[
    "add_column",
    "add_index",
    "rename_column",
    "rename_table",
    "add_constraint",
    "destructive",
]
ConstraintRequestKind = Literal["unique", "not_null", "check"]
PlanStatus = Literal["proposed", "needs_clarification", "rejected"]
ClarificationTopic = Literal["table", "column", "data_type", "behavior", "constraint", "index"]
ValidationCode = Literal[
    "unknown_table",
    "unknown_column",
    "column_exists",
    "table_exists",
    "index_exists",
    "constraint_exists",
    "invalid_identifier",
    "unsupported_operation",
    "malformed_request",
]

# Imported after local Literals so interpretation can reuse OperationKind safely.
from app.schemas.interpretation import (  # noqa: E402
    InterpretationPath,
    LlmSuggestionSummary,
    ProviderStatus,
)


class PlanCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request: str = Field(min_length=1, max_length=2000)
    use_llm: bool = False

    @field_validator("request")
    @classmethod
    def request_must_contain_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("request must not be blank")
        return stripped


class Assumption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    text: str


class ClarificationQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    topic: ClarificationTopic
    text: str


class PlanValidationError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    code: ValidationCode
    message: str
    object_name: str | None = None


class PlanOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: OperationKind
    summary: str
    table: str | None = None
    column: str | None = None
    data_type: str | None = None
    nullable: bool | None = None
    default: str | None = None
    new_name: str | None = None
    index_columns: list[str] = Field(default_factory=list)
    constraint_kind: ConstraintRequestKind | None = None
    check_expression: str | None = None
    destructive: bool = False


class MigrationProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    schema_name: str
    schema_fingerprint: str
    request: str
    status: PlanStatus
    summary: str
    assumptions: list[Assumption]
    clarification_questions: list[ClarificationQuestion]
    operations: list[PlanOperation]
    validation_errors: list[PlanValidationError]
    destructive: bool
    requires_risk_assessment: bool
    interpretation_path: InterpretationPath = "deterministic"
    provider_status: ProviderStatus = "not_used"
    provider_name: str | None = None
    provider_error: str | None = None
    llm_suggestion: LlmSuggestionSummary | None = None
