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
2. Run the narrowest relevant tests first; read every failure.
3. Select the highest-impact root cause.
4. Make the smallest appropriate fix.
5. Re-run relevant tests, then the full test suite, lint, and type checker when available.
6. Summarize files changed, behavior, commands run, results, and known limitations.

Stop after 8 fix iterations for one issue. If still failing, report the remaining failure and evidence instead of making speculative changes.

## Architecture boundaries
- Frontend communicates with backend through documented API contracts only.
- Backend owns authorization, validation, orchestration, risk decisions, audit events, and database access.
- LLM service returns structured proposals, never authoritative safety decisions.
- Deterministic policy code computes risk and enforces execution gates.
- Sandbox service operates only on disposable isolated databases.
- Production/target execution is disabled by default and must be separately configured.

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
