"""LLM provider abstraction. Credentials never leave the server process."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlparse

from pydantic import ValidationError

from app.core.config import Settings
from app.schemas.domain import SchemaSnapshot
from app.schemas.interpretation import LlmInterpretationPayload
from app.schemas.llm import ProviderStatus
from app.services.llm.schema_context import build_schema_context, system_prompt, user_prompt


class LlmProviderError(Exception):
    def __init__(self, status: ProviderStatus, message: str) -> None:
        self.status = status
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class LlmProviderResult:
    payload: LlmInterpretationPayload
    provider_name: str


class _StructuredOutputRejected(Exception):
    """The endpoint rejected the JSON Schema response format itself."""


class LlmProvider(Protocol):
    name: str

    def interpret(
        self,
        request_text: str,
        snapshot: SchemaSnapshot,
    ) -> LlmProviderResult: ...


def parse_provider_json(raw: str | bytes | dict[str, Any]) -> LlmInterpretationPayload:
    """Validate provider output. Malformed or SQL-bearing extras are rejected."""

    if isinstance(raw, (str, bytes)):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LlmProviderError("malformed", "Provider returned non-JSON content.") from exc
    else:
        data = raw
    if not isinstance(data, dict):
        raise LlmProviderError("malformed", "Provider JSON must be an object.")
    # Explicitly refuse common dangerous keys even before pydantic extra=forbid.
    forbidden = {
        "sql",
        "upgrade_sql",
        "downgrade_sql",
        "connection_string",
        "database_url",
        "target_identity",
        "api_key",
        "password",
        "executable",
    }
    present = forbidden.intersection(data)
    if present:
        raise LlmProviderError(
            "malformed",
            f"Provider response included forbidden fields: {sorted(present)}.",
        )
    try:
        return LlmInterpretationPayload.model_validate(data)
    except ValidationError as exc:
        reason = _validation_error_summary(exc)
        raise LlmProviderError(
            "malformed",
            f"Provider response failed schema validation: {reason}.",
        ) from exc


def _validation_error_summary(error: ValidationError) -> str:
    """Summarize structural issues without exposing provider values or raw output."""

    safe_fields = {
        "schema_fingerprint",
        "summary",
        "assumptions",
        "clarification_questions",
        "operations",
        "topic",
        "text",
        "kind",
        "table",
        "column",
        "data_type",
        "nullable",
        "default",
        "new_name",
        "index_columns",
        "constraint_kind",
        "check_expression",
        "destructive",
    }
    summaries: list[str] = []
    for item in error.errors()[:3]:
        path = ".".join(
            str(part)
            for part in item.get("loc", ())
            if isinstance(part, str) and part in safe_fields
        )
        error_type = item.get("type")
        if error_type == "missing":
            detail = f"missing required field {path}" if path else "missing required field"
        elif error_type == "extra_forbidden":
            detail = "contains an unexpected field"
        else:
            detail = f"invalid value for {path}" if path else "invalid field value"
        if detail not in summaries:
            summaries.append(detail)
    return "; ".join(summaries) or "the response shape was invalid"


class OpenAICompatibleProvider:
    """HTTP chat completions provider. Uses stdlib urllib; no secret logging."""

    name = "openai_compatible"
    api_key_header = "Authorization"
    api_key_prefix = "Bearer "

    def __init__(self, settings: Settings) -> None:
        self._api_key = (settings.llm_api_key or "").strip()
        self._base = settings.llm_api_base.rstrip("/")
        self._model = settings.llm_model
        self._timeout = float(settings.llm_timeout_seconds)

    def interpret(
        self,
        request_text: str,
        snapshot: SchemaSnapshot,
    ) -> LlmProviderResult:
        if not self._api_key:
            raise LlmProviderError("not_configured", "LLM API key is not configured.")
        context = build_schema_context(snapshot)
        body = {
            "model": self._model,
            "temperature": 0,
            "response_format": _structured_response_format(),
            "messages": [
                {"role": "system", "content": system_prompt()},
                {"role": "user", "content": user_prompt(request_text, context)},
            ],
        }
        try:
            raw = self._post_completion(body)
        except _StructuredOutputRejected:
            # Some OpenAI-compatible deployments support JSON mode but not strict
            # structured outputs. Keep the server-side Pydantic validation either way.
            body["response_format"] = {"type": "json_object"}
            raw = self._post_completion(body)
        try:
            envelope = json.loads(raw)
            content = envelope["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise LlmProviderError("malformed", "Provider envelope was malformed.") from exc
        return LlmProviderResult(payload=parse_provider_json(content), provider_name=self.name)

    def _post_completion(self, body: dict[str, Any]) -> str:
        payload = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            f"{self._base}/chat/completions",
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                self.api_key_header: f"{self.api_key_prefix}{self._api_key}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                raw = response.read().decode("utf-8")
        except TimeoutError as exc:
            raise LlmProviderError("timeout", "LLM provider timed out.") from exc
        except urllib.error.HTTPError as exc:
            if (
                exc.code == 400
                and body.get("response_format", {}).get("type") == "json_schema"
                and _response_format_rejected(exc)
            ):
                raise _StructuredOutputRejected from None
            if exc.code == 429:
                raise LlmProviderError(
                    "rate_limited",
                    "LLM provider rate-limited the request.",
                ) from exc
            raise LlmProviderError("error", f"LLM provider HTTP error {exc.code}.") from exc
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", None)
            if isinstance(reason, TimeoutError):
                raise LlmProviderError("timeout", "LLM provider timed out.") from exc
            raise LlmProviderError("error", "LLM provider request failed.") from exc
        return raw


class AzureOpenAIProvider(OpenAICompatibleProvider):
    """Azure OpenAI v1 chat completions using an Azure resource API key."""

    name = "azure_openai"
    api_key_header = "api-key"
    api_key_prefix = ""

    def __init__(self, settings: Settings) -> None:
        base = urlparse(settings.llm_api_base)
        host = (base.hostname or "").casefold()
        azure_host = host.endswith(".openai.azure.com") or host.endswith(".services.ai.azure.com")
        if (
            base.scheme != "https"
            or not azure_host
            or not base.path.rstrip("/").endswith("/openai/v1")
            or base.query
            or base.fragment
        ):
            raise LlmProviderError(
                "not_configured",
                "Azure OpenAI requires an HTTPS Azure v1 endpoint ending in /openai/v1.",
            )
        super().__init__(settings)


def _response_format_rejected(error: urllib.error.HTTPError) -> bool:
    """Recognize format-related 400s without logging or exposing provider details."""

    try:
        error_body = json.loads(error.read().decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, OSError):
        return False
    detail = error_body.get("error", {}) if isinstance(error_body, dict) else {}
    if not isinstance(detail, dict):
        return False
    parameter = str(detail.get("param", "")).casefold()
    code = str(detail.get("code", "")).casefold()
    message = str(detail.get("message", "")).casefold()
    return (
        parameter.startswith("response_format")
        or "response_format" in message
        or "json_schema" in code
    )


def _structured_response_format() -> dict[str, Any]:
    """Ask supported OpenAI-compatible models to follow our exact output contract."""

    schema = LlmInterpretationPayload.model_json_schema()
    definitions = schema.pop("$defs", {})

    def normalize(node: Any) -> Any:
        if isinstance(node, list):
            return [normalize(item) for item in node]
        if not isinstance(node, dict):
            return node
        reference = node.get("$ref")
        if isinstance(reference, str) and reference.startswith("#/$defs/"):
            definition_name = reference.rsplit("/", 1)[-1]
            expanded = deepcopy(definitions[definition_name])
            expanded.update({key: value for key, value in node.items() if key != "$ref"})
            return normalize(expanded)

        result = {
            key: normalize(value)
            for key, value in node.items()
            if key
            not in {
                "title",
                "description",
                "default",
                # Azure structured outputs reject these JSON Schema keywords;
                # Pydantic still enforces them after parsing the model response.
                "minLength",
                "maxLength",
                "maxItems",
            }
        }
        if node.get("type") == "object":
            properties = node.get("properties", {})
            result["required"] = list(properties)
            result["additionalProperties"] = False
        return result

    return {
        "type": "json_schema",
        "json_schema": {
            "name": "migration_interpretation",
            "strict": True,
            "schema": normalize(schema),
        },
    }


class CallableProvider:
    """Test double that wraps a callable returning payload dict or JSON text."""

    name = "mock"

    def __init__(self, handler: Any, *, name: str = "mock") -> None:
        self._handler = handler
        self.name = name

    def interpret(
        self,
        request_text: str,
        snapshot: SchemaSnapshot,
    ) -> LlmProviderResult:
        raw = self._handler(request_text, snapshot, build_schema_context(snapshot))
        if isinstance(raw, LlmInterpretationPayload):
            return LlmProviderResult(payload=raw, provider_name=self.name)
        return LlmProviderResult(payload=parse_provider_json(raw), provider_name=self.name)


def build_provider(settings: Settings, override: LlmProvider | None = None) -> LlmProvider | None:
    if override is not None:
        return override
    if not settings.llm_enabled:
        return None
    if not settings.llm_configured():
        return None
    provider_name = (settings.llm_provider or "openai_compatible").strip().lower()
    if provider_name in {"openai", "openai_compatible"}:
        return OpenAICompatibleProvider(settings)
    if provider_name == "azure_openai":
        return AzureOpenAIProvider(settings)
    raise LlmProviderError("error", f"Unsupported LLM provider '{provider_name}'.")
