# GitHub Copilot Instructions — SchemaPilot

Read `instructions.md`, `IMPLEMENTATION_PLAN.md`, and `SECURITY.md` before implementing features.

## Project purpose
SchemaPilot plans and validates PostgreSQL migrations from natural-language requests. Its principle is: **AI proposes; deterministic code verifies; a human approves.**

## Rules
- Inspect existing code before editing; preserve established patterns unless there is a reason to change them.
- Make small, testable changes. Avoid generating the entire application at once.
- Add/update tests for every behavior change.
- Never weaken tests to obtain a green run.
- Never claim tests, lint, or type checks passed unless actually run.
- Keep LLM output untrusted and validate it with strict schemas.
- Risk classification must be deterministic; the LLM may explain findings but cannot override them.
- Never execute model-generated or uploaded SQL directly against a target database.
- Sandbox execution is the default. Target apply must be disabled by default and require server-side policy checks plus explicit approval bound to the artifact checksum.
- Do not log or expose secrets, connection strings, or unnecessary row data.
- Use type hints, clear names, focused modules, and explicit error handling.
- Follow API contracts and keep backend security enforcement authoritative.
- Include accessible UI states and honest evidence; never fabricate validation success.
- Before finishing, report changed files, commands actually run, results, and remaining limitations.
