# SchemaPilot Security & Safety Rules

## Threat model
Assume user prompts, uploaded SQL, schema comments, database identifiers, LLM output, and source code are untrusted. A user may accidentally or intentionally request destructive changes. The system must prevent unintended target-database modification.

## Mandatory controls
- Default to read-only inspection for connected databases.
- Never place secrets in frontend code, local storage, logs, prompts, screenshots, or committed files.
- Keep target and sandbox credentials separate.
- Use least-privilege database accounts.
- Sandbox must be disposable and isolated; fail closed if isolation is uncertain.
- Do not execute arbitrary user-uploaded SQL against a target.
- Do not execute raw LLM-generated SQL against a target.
- Parse and validate operations against the inspected schema and supported operation allowlist.
- Use deterministic risk rules and server-side policy gates.
- Require explicit approval bound to the exact artifact checksum before target apply.
- Reject stale approvals if the artifact or target changes.
- Require idempotency protection for apply requests.
- Apply timeouts and resource limits to model calls, uploads, SQL parsing, and sandbox runs.
- Redact credentials and sensitive values from errors and logs.
- Keep audit records for approvals and execution attempts without recording secrets.

## Safe defaults
- Target apply disabled unless explicitly enabled by configuration.
- No production row data sent to an LLM.
- SQL upload limited by size and supported statement types.
- Unknown operation or uncertain dependency means review/block, not automatic approval.
- Failed validation blocks target apply.
- High-risk changes require explicit acknowledgement and may remain blocked by policy.

## Incident-minded behavior
When an operation fails or isolation cannot be verified:
1. Stop the operation.
2. Preserve sanitized diagnostic evidence.
3. Mark the run failed or blocked.
4. Do not retry destructive work automatically.
5. Explain what happened and what manual review is needed.
