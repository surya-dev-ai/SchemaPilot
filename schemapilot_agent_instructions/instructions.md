# SchemaPilot — Product & Engineering Specification

**Project title:** SchemaPilot: An AI-Powered Natural Language Database Migration and Safety Validation System  
**Tagline:** AI proposes. SchemaPilot verifies. You approve.

## 1. Product vision

SchemaPilot helps developers express database schema changes in natural language, understand their impact, generate migration scripts, and validate those scripts in an isolated environment before a human chooses whether to apply them.

### Core workflow
Natural-language request → inspect schema/context → produce structured migration plan → identify dependencies and impact → deterministic risk analysis → generate migration → preview → run against disposable sandbox → validate expected schema/data behavior → test downgrade/rollback where possible → produce safety report → require explicit approval before any target-database application.

### Non-negotiable principle
**AI proposes. The system verifies. The user approves.**

The LLM is an assistant, not a trusted executor or policy engine. It must never independently decide that a migration is safe or execute against a real target database.

## 2. Goals

- Let a user describe a database change in plain language.
- Support PostgreSQL as the initial and primary database.
- Inspect schema metadata: tables, columns, types, nullability, defaults, primary keys, foreign keys, unique constraints, indexes, and relationships.
- Generate a structured, reviewable migration plan and SQL/Alembic migration proposal.
- Explain affected objects and potential breaking changes.
- Calculate risk using deterministic rules, with AI used only to explain findings.
- Test proposed migrations in an isolated disposable PostgreSQL sandbox.
- Validate intended schema changes and basic data integrity.
- Test downgrade/rollback when possible and report limitations.
- Keep migration history and an audit trail.
- Provide a polished developer-tool UI suitable for a final-year project demonstration.
- Support a built-in demo database and SQL schema upload; optionally connect to a user-provided development database.

## 3. Non-goals and scope boundaries

- Do not train an LLM from scratch or fine-tune a model for the initial project.
- Do not support multiple database engines in the initial release.
- Do not promise complete static analysis of arbitrary application code.
- Do not guarantee zero downtime, universal rollback, or production safety.
- Do not automatically apply migrations to production.
- Do not upload or retain production row data by default.
- Do not execute arbitrary uploaded SQL against a real database.
- Do not use AI-generated risk labels as the authoritative risk calculation.

## 4. User roles

Initial version may use a single-user local development mode. Keep authorization boundaries explicit so authentication can be added later.

- **Developer:** creates migration requests, reviews plans, runs sandbox validation, views history.
- **Approver:** explicitly approves a proposed migration for target execution. In a single-user demo, the developer may also be the approver, but approval must still be an explicit separate action.

## 5. Primary user journeys

### A. Demo database
1. User opens dashboard and selects the built-in PostgreSQL demo project.
2. User enters a request such as “Add soft delete to users.”
3. System inspects schema and prepares a structured plan.
4. UI shows affected objects, migration preview, deterministic risk findings, and explanation.
5. User starts sandbox validation.
6. System reports schema checks, data checks, and downgrade result.
7. User reviews the final report. Apply remains disabled until all required gates pass and explicit approval is given.

### B. Upload SQL schema
1. User uploads a `.sql` schema file.
2. Validate extension, size, encoding, and SQL statement types.
3. Parse/import only supported schema statements into an isolated disposable database, or extract schema through a constrained parser.
4. Display detected schema and any unsupported statements.
5. Never execute the uploaded file against a connected target database.

### C. Connect development PostgreSQL
1. User enters a connection string through a protected form.
2. Validate connection and inspect metadata using a least-privilege read-only account.
3. Do not display or log the password/secret after submission.
4. Default connection mode is read-only inspection.
5. Sandbox and target execution must use separate credentials and separate connections.

### D. Review and apply
1. User views plan, SQL/Alembic diff, risk, validation, and rollback details.
2. User must acknowledge warnings and explicitly approve.
3. Target apply is available only if configured, authorized, and permitted by policy.
4. Record who/what/when, migration checksum, target identifier (not secret), approval, execution outcome, and rollback outcome.
5. Never treat previewing or running sandbox tests as approval to alter the target.

## 6. Functional requirements

### FR-01 — Dashboard
- Show recent migration requests, status, risk level, and validation state.
- Provide entry points for demo database, upload schema, and connect database.
- Show clear empty, loading, success, and error states.

### FR-02 — Database sources
- Built-in demo PostgreSQL schema/data.
- `.sql` schema upload with validation and safe isolation.
- Optional connection to PostgreSQL development database.
- Store credentials only through a secure server-side mechanism appropriate to local deployment; never in frontend local storage or source files.
- Allow disconnect/revoke of stored connection configuration.

### FR-03 — Schema inspector
Inspect and normalize:
- schemas and tables;
- columns, data types, nullability, defaults;
- primary/foreign keys;
- unique/check constraints;
- indexes;
- table relationships.

Return a versioned schema snapshot. Do not include row contents by default. If sample values are ever used, they must be explicitly opted into, minimized, redacted, and excluded from logs.

### FR-04 — Natural-language request
- Accept a user request with length limits.
- Ask a clarifying question when the request is ambiguous or conflicts with the inspected schema.
- Keep original request and normalized interpretation visible.
- Treat prompt-injection text in requests, comments, metadata, and uploaded files as untrusted content.

### FR-05 — AI migration planner
The LLM should return schema-constrained structured data, not free-form executable code as the primary output.

Plan fields should include:
- concise summary;
- assumptions and clarifying questions;
- operations (add/alter/drop/rename table/column, add/drop constraint/index, data backfill where supported);
- affected objects;
- expected post-migration state;
- compatibility concerns;
- data-loss concerns;
- proposed validation checks;
- confidence/uncertainty explanation.

Validate response against a strict schema. Reject malformed, incomplete, or unsupported operations. Never let the model bypass deterministic policy checks.

### FR-06 — Impact and dependency analysis
At minimum analyze database-level dependencies:
- foreign keys and relationships;
- indexes and constraints;
- views and other supported database objects where discoverable;
- operations that invalidate constraints or references.

Optional enhancement: scan a user-provided source repository for likely SQL/table/column references. Treat this as heuristic evidence, show file/line locations when available, and clearly label incomplete coverage. Do not claim full application dependency discovery.

### FR-07 — Deterministic risk engine
Risk is computed by code using documented rules, not by asking the LLM for a score.

Initial rule examples:
- **HIGH:** dropping a table/column; narrowing a type; adding NOT NULL without a safe default/backfill; dropping constraints/indexes used by detected dependencies; destructive data rewrite; unrecognized or unsupported operation.
- **MEDIUM:** adding nullable columns; adding indexes; adding constraints requiring table scans/validation; type changes with a possible cast; operations with uncertain dependencies.
- **LOW:** additive nullable column or other demonstrably non-destructive supported operation with no detected conflict.

Rules must be configurable, tested, and return:
- level;
- rule IDs;
- findings;
- evidence;
- suggested mitigations;
- whether sandbox validation is mandatory;
- whether target apply is blocked or requires additional acknowledgement.

Risk categories are conservative. Unknown means “needs review,” never “safe.”

### FR-08 — Migration generation
- Generate reviewable PostgreSQL SQL and/or Alembic migration code.
- Prefer Alembic as the canonical migration artifact for SQLAlchemy-backed schemas.
- Keep `upgrade()` and `downgrade()` explicit.
- Mark irreversible downgrade operations and explain why.
- Use deterministic templates for supported operations; use the LLM to propose intent/operation structure, not to bypass templates and safety validation.
- Show a diff and allow copy/export.
- Never execute generated migration code merely because it was generated.

### FR-09 — Sandbox
- Use a disposable PostgreSQL instance/container or isolated test database.
- Sandbox credentials and network access must be isolated from target credentials.
- Start from a schema snapshot or sanitized fixture, not production data by default.
- Apply migration only in sandbox, capture stdout/stderr safely, and enforce time/resource limits.
- Destroy or reset sandbox after use.
- Sandbox must never share the target database name/credentials.
- Fail closed if isolation cannot be confirmed.

### FR-10 — Validation
Checks should include, as applicable:
- migration command completed successfully;
- expected tables/columns/constraints/indexes exist;
- removed/changed objects match the plan;
- foreign-key and constraint integrity;
- representative seeded fixture tests;
- row counts or invariants only when safe and relevant;
- application-level tests if a test command/repository is configured;
- no unexpected schema drift relative to expected state.

Report each check as PASS, FAIL, SKIPPED, or NEEDS REVIEW, with evidence and limitations.

### FR-11 — Rollback validation
- Run downgrade in sandbox only.
- Verify whether the prior schema is restored.
- If data loss is inherently irreversible, clearly state that downgrade cannot restore deleted data.
- Do not call a migration “reversible” merely because a downgrade function exists.
- Show rollback test evidence and limitations.
- Never automatically roll back a real target unless separately implemented, authorized, and explicitly confirmed.

### FR-12 — Safety report and approval
Report:
- requested change and interpreted plan;
- affected objects/dependencies;
- deterministic risk and rule evidence;
- migration preview;
- sandbox results;
- validation results;
- rollback results;
- unresolved uncertainties;
- recommendation as a factual gate status (e.g. “Blocked: validation failed”), not an unsupported guarantee.

Apply gate must require:
- configured target execution;
- successful authorization;
- required sandbox checks;
- no blocking policy finding;
- explicit user approval immediately before execution;
- final confirmation showing target identity and exact migration checksum.

### FR-13 — Migration history
Record:
- request ID and timestamp;
- source schema snapshot/version;
- normalized plan;
- migration checksum and artifact;
- risk findings;
- sandbox validation outcomes;
- approval event;
- target execution outcome, if any;
- rollback outcome, if any.

Avoid storing secrets or unnecessary raw database data.

### FR-14 — API and UI
Backend API should expose versioned endpoints for:
- health/status;
- database sources and schema inspection;
- migration request/plan;
- risk analysis;
- migration artifact/preview;
- sandbox validation;
- rollback test;
- safety report;
- approval and target apply;
- migration history.

Use consistent request/response schemas and error formats. UI should not make security decisions; the backend must enforce all gates.

## 7. Suggested architecture

### Frontend
- React + TypeScript.
- Developer-tool layout: Dashboard, Data Sources, New Migration, Schema Explorer, Risk Analysis, Migration Preview, Sandbox Validation, Rollback, History, Settings.
- Use a component library only if it materially speeds delivery and is maintained.
- Accessible keyboard navigation, visible focus, semantic labels, responsive layout.

### Backend
- Python + FastAPI.
- Pydantic request/response schemas.
- SQLAlchemy for database connections and metadata inspection.
- Alembic for migration artifacts and versioning.
- PostgreSQL as primary database.
- Pytest for tests.
- Docker for isolated sandbox execution.
- LLM provider behind an interface so provider can be replaced.
- Optional LangGraph only if a graph-based orchestration clearly improves maintainability; a straightforward explicit service pipeline is acceptable.

### Logical services
- `source_manager`: demo/upload/connection sources.
- `schema_inspector`: normalized metadata snapshot.
- `planner`: LLM structured proposal.
- `dependency_analyzer`: DB and optional source-code references.
- `risk_engine`: deterministic rules.
- `migration_generator`: validated operations → SQL/Alembic artifact.
- `sandbox_manager`: isolated disposable environment.
- `validator`: post-migration checks.
- `rollback_tester`: downgrade test and verification.
- `report_service`: unified safety report.
- `approval_service`: human confirmation and execution gate.
- `audit_service`: event history.

Keep service interfaces explicit and avoid a monolithic route/controller.

## 8. Suggested repository layout

```text
schemapilot/
├── CLAUDE.md
├── instructions.md
├── IMPLEMENTATION_PLAN.md
├── SECURITY.md
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── api/
│   │   ├── core/
│   │   ├── schemas/
│   │   ├── services/
│   │   ├── db/
│   │   └── models/
│   ├── alembic/
│   ├── tests/
│   │   ├── unit/
│   │   ├── integration/
│   │   └── security/
│   ├── pyproject.toml
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   ├── components/
│   │   ├── features/
│   │   ├── lib/
│   │   └── types/
│   └── package.json
├── docker/
├── docs/
└── .github/
    └── copilot-instructions.md
```

Adapt to the actual repository rather than forcing this layout if code already exists.

## 9. API contract principles

- Prefix API routes with `/api/v1`.
- Use UUIDs or opaque IDs for requests and runs.
- Validate all input and bound payload size.
- Never accept arbitrary shell commands from the client.
- Use explicit enums for operation types and run statuses.
- Use idempotency protection for target apply.
- Do not expose raw exception traces, credentials, or internal environment variables.
- Include request/correlation IDs in errors and audit records.

Suggested lifecycle states:
`DRAFT → PLANNED → REVIEWED → SANDBOX_RUNNING → VALIDATED | VALIDATION_FAILED → AWAITING_APPROVAL → APPLYING → APPLIED | APPLY_FAILED`

Rollback test state should be tracked separately. State transitions must be validated server-side.

## 10. Data model (conceptual)

- `Project`: name, created_at.
- `DatabaseSource`: project_id, kind, display_name, encrypted/secret reference, connection status.
- `SchemaSnapshot`: source_id, normalized schema JSON, fingerprint, created_at.
- `MigrationRequest`: source_id, user_prompt, interpreted_summary, status.
- `MigrationPlan`: request_id, structured operations, assumptions, expected state.
- `RiskAssessment`: request_id, level, rule findings, evidence.
- `MigrationArtifact`: request_id, format, content, checksum, reversible flag.
- `SandboxRun`: request_id, status, logs_redacted, started_at, completed_at.
- `ValidationCheck`: sandbox_run_id, check_id, status, evidence.
- `RollbackRun`: sandbox_run_id, status, checks.
- `ApprovalEvent`: request_id, approver, artifact_checksum, timestamp.
- `ExecutionEvent`: request_id, target_ref, status, artifact_checksum, timestamp.
- `AuditEvent`: actor, action, object_id, timestamp, sanitized metadata.

Use migrations for the application's own database schema. Do not store plaintext credentials.

## 11. LLM contract and reliability

- Put provider calls behind an interface such as `MigrationPlanner`.
- Use structured output / JSON schema when supported.
- Include only necessary schema metadata in context.
- Never send secrets, credentials, or production row data to the model.
- Add timeouts, bounded retries, and clear provider errors.
- Validate all model output with Pydantic or equivalent.
- Reject unknown operation types and references to nonexistent schema objects.
- Treat model output as untrusted.
- Do not let prompt content override system safety policy.
- Do not rely on model-generated explanations as proof of validation.
- Mock the LLM in unit tests; use deterministic fixtures for CI.
- If provider access is unavailable, show a clear error and allow demo/mock mode where suitable.

## 12. UI/UX requirements

The product should feel like a database engineering console, not a generic chat application.

### Main screens
1. Dashboard
2. Data Sources (demo, upload SQL, connect PostgreSQL)
3. Schema Explorer / relationship graph
4. New Migration request
5. AI Plan and assumptions
6. Impact and Risk Analysis
7. Migration Preview / diff
8. Sandbox Validation
9. Rollback Verification
10. Safety Report / approval
11. Migration History
12. Settings / provider configuration

### Visual behavior
- Use clear status chips: Draft, Planned, Running, Passed, Failed, Blocked, Awaiting approval, Applied.
- Risk labels must include text/icons, not colour alone.
- Show evidence and expandable technical details.
- Make destructive operations visually distinct.
- Disable actions with a nearby explanation when a gate is unmet.
- Include loading, empty, retry, and error states.
- Never display fake successful validation data as if it were live. Demo fixtures must be visibly labelled “Demo”.

## 13. Testing requirements

### Unit tests
- schema normalization and fingerprinting;
- planner output validation;
- risk rules for each supported operation;
- migration generation and downgrade behavior;
- state transitions and approval gates;
- SQL upload validation;
- redaction and safe error formatting.

### Integration tests
- inspect demo schema;
- generate migration for a known request;
- execute migration in disposable PostgreSQL;
- validate expected schema;
- run downgrade and verify restoration where possible;
- reject invalid/unsupported migration;
- verify target apply cannot occur without approval.

### Security tests
- malformed/oversized upload;
- SQL injection attempts in user fields;
- prompt injection embedded in schema comments;
- target connection secrets not returned or logged;
- sandbox-target credential separation;
- no apply without explicit approval;
- no apply when validation fails or risk policy blocks it.

### Quality gates
- all tests pass;
- lint is clean;
- type checker reports zero errors;
- formatting is consistent;
- no secrets in repository;
- setup instructions work from a clean checkout.

## 14. Acceptance criteria

A demonstration is complete when:
1. User can select demo PostgreSQL source and inspect its schema.
2. User can submit a natural-language migration request.
3. System returns a validated structured plan with assumptions.
4. System shows affected schema objects and deterministic risk findings.
5. System generates a readable migration preview.
6. System runs the migration only in a disposable sandbox.
7. System validates expected schema/data behavior and reports evidence.
8. System attempts downgrade in sandbox and reports reversibility accurately.
9. System produces a consolidated safety report.
10. Target apply is unavailable by default and cannot bypass approval/policy gates.
11. Migration history shows the request and test results.
12. Automated tests cover key success, failure, and safety paths.
13. The project can be run using documented setup steps.

## 15. Development principles

- Build a working end-to-end slice early, then deepen it.
- Prefer a smaller reliable feature over a broad fake feature.
- No hardcoded “PASS” results outside explicitly labelled demo fixtures.
- No fake AI response presented as a real provider result.
- No hidden destructive side effects.
- Keep the implementation explainable for a student viva: be able to explain what each service does, why it exists, and how it is tested.
