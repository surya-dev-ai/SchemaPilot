# Optional LLM-assisted interpretation

Phase 11 adds an optional server-side LLM provider that turns natural-language intent into a strict structured draft. Every draft is validated against the inspected schema fingerprint and then scored by the same deterministic planner, risk engine, and artifact generator used for ordinary requests.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `SCHEMAPILOT_LLM_ENABLED` | `false` | Master switch |
| `SCHEMAPILOT_LLM_API_KEY` | empty | Server-side credential |
| `SCHEMAPILOT_LLM_API_BASE` | `https://api.openai.com/v1` | OpenAI-compatible base URL (Azure: `https://<resource>.services.ai.azure.com/openai/v1`) |
| `SCHEMAPILOT_LLM_MODEL` | `gpt-4o-mini` | Model or Azure deployment name (never a secret) |
| `SCHEMAPILOT_LLM_TIMEOUT_SECONDS` | `20` | Provider timeout |
| `SCHEMAPILOT_LLM_FALLBACK_TO_DETERMINISTIC` | `true` | Fall back when the provider fails |
| `SCHEMAPILOT_LLM_PROVIDER` | `openai_compatible` | Provider adapter name |

The application works without an API key. Credentials are never returned by `/api/v1/health` or stored in workflow JSON.

## Request flag

Existing plan/risk/artifact/report/persist bodies accept optional `use_llm` (default `false`):

```json
{ "request": "Add a nickname on users", "use_llm": true }
```

Responses include:

- `interpretation_path`: `deterministic` | `llm_assisted` | `deterministic_fallback`
- `provider_status`: `not_used` | `not_configured` | `disabled` | `ok` | `error` | `timeout` | `rate_limited` | `malformed`
- `provider_name`, `provider_error`, `llm_suggestion`

## Safety boundaries

- Schema comments are labeled `comment_untrusted` and must not be followed.
- Provider JSON forbids `sql`, connection strings, credentials, and target identities.
- Unsupported operations and unknown objects are rejected by deterministic validation.
- Risk findings and `not_run` checks cannot be overridden by the model.
- Model output never executes against any database.
- LLM success alone never makes a migration eligible for approval.
- Target execution remains disabled.
- Phase 12 acceptance review of this boundary is recorded in `docs/acceptance.md`.

## Tests

Unit tests mock providers. Live provider tests stay skipped by default.
