# SchemaPilot Implementation Plan

Use this as a living checklist. Update status only after implementation and verification.

## Phase 0 — Repository reconnaissance
- [ ] Inspect repository, existing code, runtime versions, and available scripts.
- [ ] Record architecture and gaps in `docs/architecture.md`.
- [ ] Confirm environment and baseline tests/lint/type checks.
- [ ] Add `.env.example`; verify secrets are ignored.

## Phase 1 — Skeleton and local developer experience
- [ ] Establish backend FastAPI app and health endpoint.
- [ ] Establish frontend React + TypeScript app.
- [ ] Add local PostgreSQL/Docker Compose for development and isolated test DB.
- [ ] Add formatting, lint, type-check, and test commands.
- [ ] Document clean setup and run commands.

## Phase 2 — Demo schema and schema inspection
- [ ] Create deterministic demo schema and seed fixtures.
- [ ] Implement SQLAlchemy metadata inspection.
- [ ] Normalize tables, columns, constraints, indexes, and foreign keys.
- [ ] Add schema fingerprint/snapshot.
- [ ] Test empty schema, unusual identifiers, and supported PostgreSQL types.

## Phase 3 — Request and structured planner
- [ ] Define Pydantic models for migration request, operation, plan, and assumptions.
- [ ] Implement provider abstraction and configured LLM adapter.
- [ ] Add bounded timeout/retry and safe error handling.
- [ ] Validate model output; reject unknown operations and nonexistent references.
- [ ] Add deterministic mock planner for tests/demo fallback.

## Phase 4 — Impact analysis and risk rules
- [ ] Implement DB dependency analysis.
- [ ] Define documented risk rules with stable rule IDs.
- [ ] Return findings with evidence and mitigation guidance.
- [ ] Test each risk category and unknown-operation fail-closed behavior.
- [ ] Show that LLM cannot override risk-engine output.

## Phase 5 — Migration generation
- [ ] Convert supported validated operations into migration artifacts.
- [ ] Generate SQL and/or Alembic upgrade/downgrade.
- [ ] Calculate artifact checksum.
- [ ] Flag destructive/irreversible operations.
- [ ] Add golden-file and downgrade tests.

## Phase 6 — Sandbox execution
- [ ] Provision disposable PostgreSQL sandbox.
- [ ] Verify sandbox/target isolation.
- [ ] Load demo schema or safe schema snapshot.
- [ ] Execute only validated migration artifact in sandbox.
- [ ] Add timeouts, cleanup, and failure capture.
- [ ] Test sandbox provisioning failure and cleanup.

## Phase 7 — Validation and rollback
- [ ] Verify expected schema state.
- [ ] Run relevant integrity checks and seeded fixture tests.
- [ ] Represent each check as PASS/FAIL/SKIPPED/NEEDS REVIEW.
- [ ] Run downgrade in sandbox where supported.
- [ ] Report irreversible data loss honestly.
- [ ] Prevent target apply when required checks fail.

## Phase 8 — Reports, approval, and history
- [ ] Build consolidated safety report.
- [ ] Implement lifecycle/state transition validation.
- [ ] Implement explicit approval bound to artifact checksum.
- [ ] Keep target apply disabled unless explicitly configured.
- [ ] Add idempotency protection and audit events.
- [ ] Test missing approval, stale approval/checksum, and blocked risk.

## Phase 9 — Frontend
- [ ] Dashboard and source selection.
- [ ] Schema explorer and relationship visualization.
- [ ] Natural-language request and plan review.
- [ ] Risk findings and migration diff.
- [ ] Sandbox progress and validation evidence.
- [ ] Rollback result and final safety report.
- [ ] History and settings.
- [ ] Accessible responsive layout and real error states.

## Phase 10 — Integration and final hardening
- [ ] Connect frontend to actual API contracts.
- [ ] End-to-end demo flow using demo source.
- [ ] SQL upload security tests.
- [ ] Secret redaction and logging review.
- [ ] Run full tests, lint, formatter, and type checker.
- [ ] Verify clean setup from fresh checkout.
- [ ] Prepare demo script, architecture diagram, limitations, and viva notes.

## Definition of done for every task
- [ ] Behavior implemented and reviewed.
- [ ] Tests added or updated.
- [ ] Relevant tests pass.
- [ ] Lint and type checks pass where configured.
- [ ] No secret or unsafe side effect introduced.
- [ ] Documentation updated if behavior/setup changed.
- [ ] Summary states files changed, commands run, results, and remaining issues.

## Priority rule
If time is limited, protect the complete safe demo journey: demo schema → inspect → plan → deterministic risk → migration preview → isolated sandbox → validation → rollback report → history. Keep target apply gated and optional rather than sacrificing sandbox safety.
