# Optional LLM-assisted interpretation

Phase 11 adds an optional server-side LLM provider that turns natural-language intent into a strict structured draft. Every draft is validated against the inspected schema fingerprint and then scored by the same deterministic planner, risk engine, and artifact generator used for ordinary requests.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `SCHEMAPILOT_LLM_ENABLED` | `false` | Master switch |
| `SCHEMAPILOT_LLM_API_KEY` | empty | Server-side credential |
| `SCHEMAPILOT_LLM_API_BASE` | `https://api.openai.com/v1` | OpenAI-compatible base URL |
| `SCHEMAPILOT_LLM_MODEL` | `gpt-4o-mini` | Model name (never a secret) |
| `SCHEMAPILOT_LLM_TIMEOUT_SECONDS` | `20` | Provider timeout |
| `SCHEMAPILOT_LLM_FALLBACK_TO_DETERMINISTIC` | `true` | Fall back when the provider fails |
| `SCHEMAPILOT_LLM_PROVIDER` | `openai_compatible` | `openai_compatible` or `azure_openai` |

For Azure OpenAI v1, set `SCHEMAPILOT_LLM_PROVIDER=azure_openai`, use an HTTPS Azure resource endpoint ending in `/openai/v1`, and set `SCHEMAPILOT_LLM_MODEL` to the Azure deployment name. The Azure adapter sends the resource key in the `api-key` header and calls `/chat/completions`. It does not support the legacy deployment URL with `api-version`; use the v1 endpoint. Do not enable live requests with a key that has been exposed. Rotate it with Azure first, replace the value privately in `backend/.env`, then enable LLM requests.

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
