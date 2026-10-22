"""LLM interpretation contracts. Untrusted structured data only; never SQL or secrets."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.operation_kinds import (
    ClarificationTopic,
    ConstraintRequestKind,
    OperationKind,
)

InterpretationPath = Literal["deterministic", "llm_assisted", "deterministic_fallback"]
ProviderStatus = Literal[
    "not_used",
    "not_configured",
    "disabled",
    "ok",
    "error",
    "timeout",
    "rate_limited",
    "malformed",
]


class LlmClarificationDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: ClarificationTopic
    text: str = Field(min_length=1, max_length=500)


class LlmOperationDraft(BaseModel):
    """Structured operation draft. Extra fields such as sql are rejected."""

    model_config = ConfigDict(extra="forbid")

    kind: OperationKind
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

    @field_validator("table", "column", "new_name", "data_type", "default", "check_expression")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class LlmInterpretationPayload(BaseModel):
    """Provider JSON contract. Connection strings and SQL are forbidden extras."""

    model_config = ConfigDict(extra="forbid")

    schema_fingerprint: str = Field(min_length=1, max_length=128)
    summary: str = Field(min_length=1, max_length=500)
    assumptions: list[str] = Field(default_factory=list, max_length=20)
    clarification_questions: list[LlmClarificationDraft] = Field(
        default_factory=list,
        max_length=20,
    )
    operations: list[LlmOperationDraft] = Field(default_factory=list, max_length=20)

    @field_validator("assumptions")
    @classmethod
    def assumptions_must_be_text(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for item in values:
            text = item.strip()
            if text:
                cleaned.append(text[:500])
        return cleaned


class LlmSuggestionSummary(BaseModel):
    """Safe suggestion metadata returned to clients. No credentials or SQL."""

    model_config = ConfigDict(extra="forbid")

    summary: str
    assumptions: list[str]
    clarification_questions: list[LlmClarificationDraft]
    operations: list[LlmOperationDraft]
    schema_fingerprint: str
