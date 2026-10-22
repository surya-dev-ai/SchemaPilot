"""Optional LLM-assisted planning that always finishes in the deterministic planner."""

from __future__ import annotations

from app.core.config import Settings
from app.schemas.domain import SchemaSnapshot
from app.schemas.interpretation import LlmSuggestionSummary
from app.schemas.planning import MigrationProposal, PlanValidationError
from app.services.llm.provider import (
    LlmProvider,
    LlmProviderError,
    build_provider,
)
from app.services.planner import propose_from_llm_payload, propose_migration


def create_proposal(
    settings: Settings,
    snapshot: SchemaSnapshot,
    request_text: str,
    *,
    use_llm: bool = False,
    provider: LlmProvider | None = None,
) -> MigrationProposal:
    """Plan a migration, optionally assisted by an LLM interpretation.

    The LLM never chooses risk, eligibility, or execution. Failures fall back to
    the deterministic planner when configured, otherwise return a rejected proposal
    with provider error metadata.
    """

    cleaned = request_text.strip()
    if not use_llm:
        return propose_migration(snapshot, cleaned)

    active = build_provider(settings, provider)
    if active is None:
        status = "disabled" if not settings.llm_enabled else "not_configured"
        if settings.llm_fallback_to_deterministic:
            base = propose_migration(snapshot, cleaned)
            return base.model_copy(
                update={
                    "interpretation_path": "deterministic_fallback",
                    "provider_status": status,
                    "provider_name": None,
                    "provider_error": (
                        "LLM assist was requested but no provider credentials are configured."
                    ),
                    "llm_suggestion": None,
                }
            )
        return _provider_failure_proposal(
            snapshot,
            cleaned,
            status=status,
            message="LLM assist was requested but no provider credentials are configured.",
        )

    try:
        result = active.interpret(cleaned, snapshot)
    except LlmProviderError as exc:
        if settings.llm_fallback_to_deterministic:
            base = propose_migration(snapshot, cleaned)
            return base.model_copy(
                update={
                    "interpretation_path": "deterministic_fallback",
                    "provider_status": exc.status,
                    "provider_name": getattr(active, "name", None),
                    "provider_error": exc.message,
                    "llm_suggestion": None,
                }
            )
        return _provider_failure_proposal(
            snapshot,
            cleaned,
            status=exc.status,
            message=exc.message,
            provider_name=getattr(active, "name", None),
        )

    suggestion = LlmSuggestionSummary(
        summary=result.payload.summary,
        assumptions=list(result.payload.assumptions),
        clarification_questions=list(result.payload.clarification_questions),
        operations=list(result.payload.operations),
        schema_fingerprint=result.payload.schema_fingerprint,
    )
    proposal = propose_from_llm_payload(snapshot, cleaned, result.payload)
    return proposal.model_copy(
        update={
            "interpretation_path": "llm_assisted",
            "provider_status": "ok",
            "provider_name": result.provider_name,
            "provider_error": None,
            "llm_suggestion": suggestion,
        }
    )


def _provider_failure_proposal(
    snapshot: SchemaSnapshot,
    request_text: str,
    *,
    status: str,
    message: str,
    provider_name: str | None = None,
) -> MigrationProposal:
    return MigrationProposal(
        source_id=snapshot.source_id,
        schema_name=snapshot.schema_name,
        schema_fingerprint=snapshot.fingerprint,
        request=request_text,
        status="rejected",
        summary=message,
        assumptions=[],
        clarification_questions=[],
        operations=[],
        validation_errors=[
            PlanValidationError(
                id="error-1",
                code="malformed_request",
                message=message,
                object_name=None,
            )
        ],
        destructive=False,
        requires_risk_assessment=False,
        interpretation_path="llm_assisted",
        provider_status=status,  # type: ignore[arg-type]
        provider_name=provider_name,
        provider_error=message,
        llm_suggestion=None,
    )
