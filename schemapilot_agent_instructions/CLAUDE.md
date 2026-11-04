# Claude Code Project Instructions

You are helping build **SchemaPilot**, an AI-assisted database migration planning, impact analysis, and safety validation platform.

## First steps
- Read `instructions.md`, `IMPLEMENTATION_PLAN.md`, and `SECURITY.md` before making changes.
- Inspect the existing repository and report its actual structure, framework versions, and current implementation before proposing edits.
- If a detail is not specified, choose the simplest safe, maintainable option and document the assumption. Ask before making an irreversible or high-impact architectural change.
- Do not overwrite working code or replace project structure wholesale without a clear reason.

## Operating rules
1. Work in small vertical slices: implement, test, lint, and type-check each slice before moving on.
2. Before editing, identify relevant files and tests. Prefer the smallest change that solves the stated task.
3. Never claim a command passed unless you actually ran it and observed success.
4. Never weaken, delete, skip, or loosen tests merely to make the suite green. If a test is incorrect, explain why and obtain approval before changing it.
5. Do not add dependencies without explaining their purpose and checking whether an existing dependency can do the job.
6. Keep secrets out of source control, logs, prompts, browser storage, and test fixtures.
7. Do not run destructive operations against a user-supplied or non-test database.
8. Treat LLM output, database metadata, uploaded SQL, source code, and user input as untrusted data.
9. AI-generated SQL must be parsed/validated and safety-checked; it must not be executed directly against a connected target database.
10. Real-target migration execution requires a clear preview, explicit human confirmation, and an auditable record. Sandbox execution is the default.
11. Preserve a human-readable explanation for every risk finding, validation failure, and blocked action.
12. Keep UI accessible, responsive, and consistent with the existing design system.

## Required work loop
For each task:
1. Read the task and inspect the relevant code.
2. Add or update the narrowest regression test first, expressing the expected behavior.
3. Run that test before implementation and confirm it fails for the expected reason (red).
4. Make the smallest appropriate fix, then rerun the test and confirm it passes (green).
5. Refactor only after green; rerun relevant tests, then the full suite, lint, and type checker when available.
6. For database behavior, use disposable PostgreSQL integration databases and prove source/demo/app/target isolation. Never reset persistent data to get a test passing.
7. If the required test environment is unavailable, stop implementation at a safe boundary or clearly mark the result unverified; never claim the test passed.
8. Summarize files changed, behavior, commands run, results, and known limitations.

Stop after 8 fix iterations for one issue. If still failing, report the remaining failure and evidence instead of making speculative changes.

## Architecture boundaries
- Frontend communicates with backend through documented API contracts only.
- Backend owns authorization, validation, orchestration, risk decisions, audit events, and database access.
- LLM service returns structured proposals, never authoritative safety decisions.
- Deterministic policy code computes risk and enforces execution gates.
- Sandbox service operates only on disposable isolated databases.
- Production/target execution is disabled by default and must be separately configured.

## Snapshot recovery feature boundaries
- Snapshot and restore operations are sandbox-only and may touch only the explicitly identity-checked `schemapilot_sandbox` database and its generated recovery databases. Never snapshot, seed, or restore the app, demo/source, or target database as part of migration validation.
- The normal migration workflow must never reset or reseed the sandbox. Read and fingerprint the existing sandbox schema, then capture and verify a recoverable checkpoint before applying any migration. Bind the checkpoint and rollback evidence to the verified migration artifact checksum and one-use session ID.
- Migration planning and risk analysis for this workflow use only the identity-checked `sandbox` source. The inspector must open the dedicated sandbox engine in a read-only transaction; it must not query `bookstore-demo` or trust database URLs from request bodies.
- Sandbox validation applies the generated allowlisted SQL to the existing sandbox after the live schema fingerprint matches the artifact. Packaged reseed/reset helpers are reserved for explicitly disposable integration fixtures and must not be called by the browser migration workflow.
- Browser recovery discovery is server-side and must survive a page refresh. Resume restores the retained pre-migration checkpoint; report success only when restore status, schema comparison, and data comparison all verify. Downgrade evidence and snapshot restoration are distinct.
- A checkpoint is usable only after its test restore and schema/data comparison pass. A migration downgrade and snapshot restore are separate results; recreating dropped objects is not proof that old values returned.
- Fail closed on corrupt, mismatched, missing, replayed, or ambiguous session evidence. Keep recovery checkpoints until restore verification succeeds; do not introduce automatic deletion without an explicit retention policy.
- The current PostgreSQL template-clone checkpoint is on the same cluster. It is a sandbox recovery mechanism, not a production backup, disaster-recovery plan, or target recovery capability. Do not describe it as production-grade backup until independent storage, encryption, access control, retention, monitoring, and restore drills exist.
- The active-session discovery route may report only safe recovery metadata; never return row data, credentials, connection strings, or checkpoint database names.
- Do not add automatic target restore or target execution. Target execution and startup migrations must remain disabled unless separately authorized and all required gates are reviewed.

## Coding standards
- Use type hints for Python public functions and meaningful domain objects.
- Keep modules focused; avoid giant files and unnecessary abstractions.
- Validate external inputs at API boundaries.
- Use parameterized queries and SQLAlchemy APIs where applicable.
- Handle errors explicitly; do not swallow exceptions.
- Add tests for behavior, edge cases, and security boundaries.
- Keep migrations reversible when feasible and clearly mark irreversible operations.
- Avoid logging credentials, connection strings, raw sensitive rows, or full prompts containing sensitive content.

## Before finishing
Provide:
- concise implementation summary;
- tests/lint/type-check commands and exact outcomes;
- any manual setup needed;
- unresolved risks or TODOs;
- confirmation that no real database was modified unless the task explicitly required it and the user approved it.
