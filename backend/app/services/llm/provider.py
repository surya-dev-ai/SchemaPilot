"""LLM provider abstraction. Credentials never leave the server process."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

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


class LlmProvider(Protocol):
    name: str

    def interpret(
        self,
        request_text: str,
        snapshot: SchemaSnapshot,
    ) -> LlmProviderResult: ...


_FORBIDDEN_TOP_LEVEL = frozenset(
    {
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
)
_OPERATION_ALIASES = {
    "action": "kind",
    "operation": "kind",
    "operation_kind": "kind",
    "table_name": "table",
    "column_name": "column",
    "new_table_name": "new_name",
    "new_column_name": "new_name",
    "type": "data_type",
    "datatype": "data_type",
}


def normalize_provider_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Map common provider aliases onto the strict SchemaPilot draft schema."""

    normalized: dict[str, Any] = dict(data)
    questions = normalized.get("clarification_questions")
    if isinstance(questions, list):
        fixed: list[Any] = []
        for item in questions:
            if isinstance(item, str):
                text = item.strip()
                if text:
                    fixed.append({"topic": "behavior", "text": text})
            elif isinstance(item, dict):
                fixed.append(item)
        normalized["clarification_questions"] = fixed
    operations = normalized.get("operations")
    if isinstance(operations, list):
        fixed_ops: list[Any] = []
        for item in operations:
            if not isinstance(item, dict):
                fixed_ops.append(item)
                continue
            op = dict(item)
            for alias, canonical in _OPERATION_ALIASES.items():
                if alias in op and canonical not in op:
                    op[canonical] = op.pop(alias)
                elif alias in op:
                    op.pop(alias)
            if op.get("index_columns") is None:
                op["index_columns"] = []
            fixed_ops.append(op)
        normalized["operations"] = fixed_ops
    if normalized.get("assumptions") is None:
        normalized["assumptions"] = []
    if normalized.get("clarification_questions") is None:
        normalized["clarification_questions"] = []
    if normalized.get("operations") is None:
        normalized["operations"] = []
    return normalized


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
    present = _FORBIDDEN_TOP_LEVEL.intersection(data)
    if present:
        raise LlmProviderError(
            "malformed",
            f"Provider response included forbidden fields: {sorted(present)}.",
        )
    normalized = normalize_provider_dict(data)
    try:
        return LlmInterpretationPayload.model_validate(normalized)
    except ValidationError as exc:
        raise LlmProviderError("malformed", "Provider response failed schema validation.") from exc


class OpenAICompatibleProvider:
    """HTTP chat completions provider. Uses stdlib urllib; no secret logging."""

    name = "openai_compatible"

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
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt()},
                {"role": "user", "content": user_prompt(request_text, context)},
            ],
        }
        payload = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            f"{self._base}/chat/completions",
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                raw = response.read().decode("utf-8")
        except TimeoutError as exc:
            raise LlmProviderError("timeout", "LLM provider timed out.") from exc
        except urllib.error.HTTPError as exc:
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
        try:
            envelope = json.loads(raw)
            content = envelope["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise LlmProviderError("malformed", "Provider envelope was malformed.") from exc
        return LlmProviderResult(payload=parse_provider_json(content), provider_name=self.name)


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
    raise LlmProviderError("error", f"Unsupported LLM provider '{provider_name}'.")
