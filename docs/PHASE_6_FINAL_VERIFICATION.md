# SchemaPilot — Final Project Verification and Mentor Guide

**Prepared:** 3 November 2026  
**Scope:** Consolidated evidence from Phases 1–6, plus a mentor demonstration and viva guide.  
**Readiness conclusion:** Development-ready for a controlled local demonstration; not production-ready.

This report records the evidence available in the repository’s current TODO and project documentation, the phase reports in this conversation, and the Phase 6F read-only review. Test counts from different runs are kept separate; overlapping runs are not added together. A previous pass is not treated as a fresh Phase 6 result.

## A. Executive summary

SchemaPilot is a natural-language PostgreSQL migration planning workspace. It can turn a request into a structured plan, assess risk, produce a reviewable SQL/Alembic artifact, validate that artifact in a sandbox, record recovery and workflow evidence, and show workflow history. Optional Azure OpenAI assistance interprets requests; deterministic planning, policy checks and SQL validation remain authoritative.

Evidence includes a completed Phase 6C backend suite (**206 passed, 34 skipped, 0 failed, 0 deselected**), prior PostgreSQL integration runs, frontend unit/type/build checks, and a browser workflow that separately exercised downgrade and snapshot recovery, then refreshed and re-opened History. A specific process-crash recovery point was also tested. Target migration execution is deliberately unavailable.

The project is **development-ready for a controlled local demonstration, not production-ready**. Authentication is disabled in the current local configuration; the previously exposed Azure key has not been rotated; real multi-user approval has not been demonstrated; production TLS, secret injection, logging and network controls are not established; and sandbox checkpoints are not independent production backups.

## B. Phase-by-phase evidence

### Phase 1 — Backend baseline

- Recorded baseline: **188 passed, 1 skipped, 29 deselected**, with Ruff clean.
- Disposable PostgreSQL baseline: **29 passed, 189 deselected**.
- These are historical baseline results, not a replacement for the later Phase 6C full-suite result.
- The conventional `backend/.venv` was reported to point to an unavailable Microsoft Store Python installation.

### Phase 2 — Actual process-crash recovery

- A disposable worker was forcibly terminated immediately after the first committed database rename. A fresh API process discovered the interrupted session, resumed recovery, verified the restored schema/data, and safely rejected a repeated recovery request.
- The test also exercised rebuilding a missing staged clone from retained checkpoint evidence.
- Reported verification: rollback/snapshot integration **16 passed**; relevant unit checks **26 passed, 1 deselected, 2 warnings**; Ruff, Python compilation and diff check passed.
- This verifies the specified interruption point only. It does not prove every crash timing, host-loss recovery, or disaster recovery.
- Resources retained: `schemapilot-phase2-crash-20261103-pg` and its `schemapilot-phase2-crash-20261103-pgdata` volume. No cleanup is implied.

### Phase 3 — Snapshot and checkpoint reliability

- Four regression tests produced valid Red results for incomplete/mismatched evidence and invalid state transitions. The checkpoint store was then updated to bind checkpoint identity and fingerprints to a session and to reject completion without verified matching evidence.
- Reported verification: focused unit tests **45 passed, 2 deselected, 2 warnings**; disposable PostgreSQL rollback/checkpoint suite **17 passed**, including the Phase 2 crash test; Ruff, compilation and diff check passed.
- `restore_verified` is limited to the implemented Bookstore verification scope described in Section D. Checkpoint retention duration, quota and cleanup ownership remain undefined; automatic cleanup was not added.
- Resource retained: `schemapilot-phase3-checkpoint-20261103-pg` and its matching volume.

### Phase 4 — Security, permissions and approval boundaries

- A TDD regression fixed `/auth/me` reporting `authenticated=true` when OIDC was disabled and no identity existed. It now reports unauthenticated while preserving local-console access.
- Reported focused tests: **78 passed, 5 route tests deselected, 2 deprecation warnings**; Phase 12 target/approval acceptance tests **6 passed, 4 deselected, 2 warnings**.
- The route tests initially stalled in the restricted Windows Starlette TestClient runner before assertions. A later unrestricted run of `tests/test_acceptance_phase12.py` completed with **10 passed, 2 deprecation warnings**. This resolves that test-runner block for that file, not every HTTP route test in the project.
- Target execution remained unimplemented and approval remained fail-closed while authentication was unavailable. No real identity provider, role claims or human approval were configured.

### Phase 5 — End-to-end workflow reliability and acceptance

- Full backend run: **226 passed, 1 skipped**, with two Authlib/Starlette deprecation warnings. A test-only deterministic checksum collision was fixed using a unique checksum; the focused test then passed. Do not combine this count with other suite runs.
- Separate disposable PostgreSQL results recorded: rollback/snapshot/crash recovery **17 passed**; workflow persistence **1 passed**; demo bookstore **5 passed**; schema inspection **2 passed**; sandbox validation **8 passed**. Later Phase 5 remediation recorded a rollback/snapshot/crash run of **18 passed** and workflow persistence **1 passed**. These are distinct runs and should not be summed.
- Frontend run: **11 passed across 2 files**; TypeScript check, production build, Ruff, Python compilation and `git diff --check` passed. The diff check emitted existing line-ending warnings.
- The first Phase 5 browser acceptance run demonstrated checkpoint discovery after refresh, snapshot recovery with schema/data fingerprints matching, and history readback. It also exposed a gap: the safety report/history did not yet retain successful validation evidence and the UI rollback action was snapshot recovery rather than migration downgrade.
- Remediation added persisted validation evidence and a separate downgrade action. TDD Red tests reached the missing contracts; focused backend checks reported **39 passed, 1 deselected** and workflow-store tests **15 passed, 1 deselected**. The disposable PostgreSQL rollback/snapshot/crash suite reported **18 passed**.
- The later browser workflow used only the approved Phase 5 disposable container and its volume. It showed validation evidence, separately ran migration downgrade and checkpoint restoration, refreshed the browser, and read the workflow from History. Downgrade reported `partial_restoration` with former-column values explicitly not restored; snapshot restoration reported `restore_verified`, with schema/data matches and checkpoint retained. The safety report reported eligible for review, not approved and not applied. A separate pre-existing-sandbox preservation event was not recorded; the UI accurately left that evidence absent.
- Latest browser workflow ID recorded in the TODO: `fb6d4915-cfaf-43a0-a571-bd98bfd4f869`. Disposable resource: `schemapilot-phase5-e2e-20261103-pg`, Docker ID `ae903b3559399733d3823898ebbb4b92994ae7e8f5b725387ddddecab2419973`, volume `schemapilot-phase5-e2e-20261103-pgdata`, loopback port `127.0.0.1:58862`.

### Phase 6 — Final quality, environment and release-readiness verification

#### 6A — Repository and environment inventory

- Read-only inventory identified branch `main` and extensive existing uncommitted work across backend, frontend, tests, docs, Docker configuration, generated evidence and temporary test files. This report preserves that work; see the current `git status` evidence below.
- Python 3.13.17 was available at `backend/.test-runtime`. The broken conventional `backend/.venv` was preserved during environment replacement.
- Docker 29.8.2 and Compose v5.6.0 were reported available. No container or database operation was performed in 6A.

#### 6B — Python environment reproducibility

- A separate `backend/.venv-phase6` was prepared from the available Python 3.13.17 runtime using `backend/pyproject.toml` as the dependency source. The broken `.venv` and `.test-runtime` were preserved.
- Phase 6C then successfully used `.venv-phase6`. Exact 6B command transcript and dependency-resolution summary were not present in the repository TODO inspected for this report; no additional 6B command is asserted here.

#### 6C — Complete backend suite

- Exact accepted result: **206 passed, 34 skipped, 0 failed, 0 deselected**. This is the completed Phase 6C suite result supplied after the run.
- The exact command, warning count, elapsed time and per-skip reasons were not present in the current TODO/documentation evidence inspected for this report. They are therefore not invented here. The 34 skips are not counted as passes.
- No production defect or code change is attributed to Phase 6C in the available evidence.

#### 6D — Frontend and static checks

- Phase 6D was authorized to run frontend tests, TypeScript, build, lint, Ruff, Python compilation and Phase 6C regressions, with no Docker/database access.
- The current TODO contains the earlier Phase 5 evidence (**11 frontend tests passed; TypeScript and build passed; Ruff and compilation passed**), but does not contain a separate exact Phase 6D result block. This report does not relabel Phase 5 outputs as fresh Phase 6D results. Treat exact Phase 6D counts/commands as not independently recoverable from the inspected repository evidence.

#### 6E — Docker Compose and database isolation

- Read-only inventory recorded the Phase 2, Phase 3 and Phase 5 disposable resources and the protected app, demo and persistent sandbox services/volumes. The Phase 2/3/5 containers were present; the protected app/demo/persistent-sandbox containers were stopped at the time of that inventory. Phase 1 temporary exited containers and anonymous volumes were also retained.
- Reported Compose inspection: three PostgreSQL services, named volumes, health checks, and no backend/frontend services. The 6E inventory reported host port bindings as loopback-only (app 5435, demo 5434, sandbox 5433). No service was started or stopped and no database connection was made.
- Current `README.md` contains an older, conflicting statement that the sandbox port retains Docker’s default host binding after a Windows loopback bind failure. Reconcile that documentation with the 6E inventory before relying on the README as current exposure evidence. This report does not make a new Docker inspection.

#### 6F — Security and deployment-readiness review

- Read-only implementation/configuration review covered auth, role checks, approval, CSRF, secrets, database selection, CORS, SQL generation/execution, sandbox/checkpoint paths, error handling, Docker configuration and logging.
- No source, environment or Docker configuration was changed. No database, provider or Docker resource was contacted.
- `npm ls vite --depth=0` reported Vite 6.4.4. The 6F `npm audit --json` retry was blocked because DNS could not resolve `registry.npmjs.org`. A prior audit attempt in this review reported one moderate direct Vite vulnerability, but the advisory could not be revalidated in the later network-blocked retry. `pip_audit` was unavailable; `pip check` is not a CVE scan.
- Full classification and risk assessment are in Sections E and F.

## C. Consolidated test evidence

Counts below are from distinct runs. They overlap in scope, so they are not added into a grand total.

| Run | Evidence | Result | Status/notes |
|---|---|---:|---|
| Phase 1 backend baseline | Historical backend suite | 188 passed, 1 skipped, 29 deselected | Passed at that checkpoint; not current full-suite evidence. |
| Phase 1 disposable PostgreSQL | Historical integrations | 29 passed, 189 deselected | Passed at that checkpoint. |
| Phase 2 recovery | Crash/rollback integrations | 16 passed | Specific rename interruption covered. |
| Phase 2 unit subset | Relevant unit tests | 26 passed, 1 deselected, 2 warnings | Passed. |
| Phase 3 unit subset | Checkpoint reliability | 45 passed, 2 deselected, 2 warnings | Passed. |
| Phase 3 PostgreSQL | Rollback/checkpoint/crash | 17 passed | Passed on disposable resources. |
| Phase 4 focused | Auth/config/SQL/planner/risk/workflow | 78 passed, 5 deselected, 2 warnings | Passed; route tests were initially blocked in restricted runner. |
| Phase 4 acceptance | Target/approval acceptance | 6 passed, 4 deselected, 2 warnings | Passed. |
| Phase 4 HTTP route file | `tests/test_acceptance_phase12.py` | 10 passed, 2 warnings | Later unrestricted process; no test semantics changed. |
| Phase 5 full backend | Full backend run | 226 passed, 1 skipped, 2 warnings | Passed in that run. |
| Phase 5 PostgreSQL runs | Rollback/snapshot 17; workflow 1; demo 5; schema 2; sandbox 8 | All reported passed | Separate disposable-resource runs. A later remediation rollback suite reported 18 passed. |
| Phase 5 frontend/static | Frontend and static checks | 11 frontend tests; TypeScript/build/Ruff/compile passed | Exact command transcript not reproduced here. |
| Phase 5 browser acceptance | Browser plus disposable PostgreSQL | Plan, risk, artifact, validation, downgrade, recovery, refresh and history observed | Downgrade and snapshot recovery reported separately; no approval or target apply. |
| Phase 6C full backend | Full suite using `.venv-phase6` | 206 passed, 34 skipped, 0 failed, 0 deselected | Passed; skip reasons, warnings, duration and exact command were not in the inspected TODO. |
| Phase 6D frontend/static | Requested phase checks | No separate result block in inspected TODO | Not independently verifiable from the repository evidence inspected for this report. |
| Phase 6F dependency audit | `npm audit --json` | Blocked by registry DNS; prior result: 1 moderate Vite issue | Current advisory status unverified. |

No tests were run for this Phase 6G documentation task. No test is represented as newly passed here.

## D. Database safety

### Resources and isolation evidence

- **Protected:** `app-db`, `demo-db`, and persistent `sandbox-db` containers/volumes; treat all as user data. Phase reports state they were not used for destructive test runs.
- **Retained disposable resources:** Phase 2 `schemapilot-phase2-crash-20261103-pg`; Phase 3 `schemapilot-phase3-checkpoint-20261103-pg`; Phase 5 `schemapilot-phase5-e2e-20261103-pg` and its named volume. Phase 5 browser/integration evidence used only its approved disposable container/volume. These resources were not touched during 6F or 6G.
- **Phase 6C:** completed tests had 34 skips. Per the strict Phase 6C rule, any tests needing new PostgreSQL infrastructure required separate approval. The inspected evidence does not provide a resource list for Phase 6C; this report does not claim it used a particular database.
- **Phase 6E:** Docker inventory was read-only. No container was started/stopped and no database connection or migration occurred.

### Execution and startup controls

The last verified local safety configuration recorded `SCHEMAPILOT_TARGET_EXECUTION_ENABLED=false` and `SCHEMAPILOT_ALLOW_APP_MIGRATIONS=false`; target URL was not configured. Target apply has no API route and its preflight always rejects. Application startup does not run Alembic. These flags must remain off.

### Snapshot scope and limitations

Sandbox checkpoint clones are on the same PostgreSQL cluster and support sandbox recovery. Verified scope includes inspected Bookstore tables, columns/types/nullability, constraints, indexes, foreign keys, base-table row contents and sequence state. It excludes views, triggers, routines, extensions, roles/grants/ownership, cluster/database settings, large objects and external dependencies. It is not an encrypted off-host backup or production disaster-recovery mechanism. Automatic checkpoint cleanup is absent; retention period, quota and cleanup ownership remain unresolved.

## E. Security assessment

| Security area | Classification | Evidence and limitation |
|---|---|---|
| Local authentication | **Not implemented in current configuration** | OIDC is off; API local-console access is unauthenticated. `/auth/me` now reports unauthenticated. |
| OIDC/session/role code | **Implemented but not fully verified** | Code supports OIDC, role/group claims, signed sessions and CSRF checks when configured. No real Entra provider or user accounts were used. |
| Human multi-user approval | **Simulated or demonstration-only / incomplete** | Authenticated approval recording code exists and fails closed when auth is unavailable. No real proposer/approver journey was demonstrated. Approval is not target execution. |
| Approval freshness | **Implemented but not fully verified** | Persisted checks exist; a fresh schema-evidence check at approval time remains open. |
| CSRF | **Implemented but not fully verified** | Enforced for authenticated mutations; no real OIDC session test in this phase. |
| Secret handling | **Implemented locally; production controls require infrastructure** | `.env` is ignored and example values are placeholders. The prior Azure key exposure remains unrotated. Production secret-manager injection/rotation is not in place. |
| Database URL selection | **Implemented but not fully verified** | Server-owned URLs and identity checks prevent frontend destination selection. Cluster/host identity and network isolation remain deployment responsibilities. |
| SQL generation | **Implemented and partly verified** | Structured operation allowlists, identifier validation, risk gates and generated-SQL parsing constrain SQL. No target execution exists. |
| Sandbox boundary | **Implemented but not fully verified** | Sandbox configuration and identity checks exist; destructive migration tests used disposable resources in recorded phases. No live connection was made in 6F/6G. |
| Target apply | **Not implemented** | No apply route; target preflight always rejects. This is a safety limitation by design. |
| CORS/API exposure | **Implemented for local development; production controls require infrastructure** | Local Vite origins are configured. TLS, production host policy, rate limiting, reverse-proxy/access controls were not verified. Auth-off deployment would be unsafe. |
| Error handling/logging | **Implemented but not fully verified** | Several responses are sanitized; a complete production traceback/log pipeline review was not performed. SQLAlchemy parameter hiding and log collection need deployment review. |
| Docker security | **Requires production infrastructure/operational controls** | Compose is a local three-PostgreSQL setup with volumes/health checks. Passwords are environment variables, not Docker secrets; production network isolation/resource controls are unverified. |
| Dependency vulnerabilities | **Unverified / audit blocked** | npm registry DNS blocked the latest audit; earlier result reported one moderate Vite finding. `pip_audit` unavailable. |
| Snapshot disaster recovery | **Simulated or demonstration-only** | Same-cluster sandbox restore only; not independent backup or host-loss recovery. |
| Checkpoint retention | **Not implemented** | No automatic cleanup; policy decision and lifecycle controls remain open. |

## F. Implemented versus simulated versus incomplete

### Implemented and verified in recorded tests/workflows

- Structured natural-language planning, deterministic fallback and risk assessment.
- Review-only SQL/Alembic artifact generation that remains unapplied.
- Sandbox validation and bounded PostgreSQL snapshot restoration for the tested Bookstore scope.
- Separate migration-downgrade and snapshot-recovery actions in the later Phase 5 browser flow.
- Workflow persistence/history and browser refresh readback for the documented Phase 5 scenarios.
- A process crash at one specific database rename point and safe resume from retained evidence.
- Server-side target execution refusal and startup-migration opt-in boundary.

### Implemented but not fully verified

- OIDC authentication, role/group mapping, authorization and CSRF: mock/unit coverage exists, but no real provider or accounts were configured.
- Full PostgreSQL object integrity beyond the documented snapshot fingerprint scope.
- Production logging, network policy, TLS, secret injection and vulnerability audit.
- Approval-time freshness checks and multi-user identity separation.

### Simulated or demonstration-only

- Approval is a persisted review record when configured; no real human multi-user approval was demonstrated.
- Snapshot restore is a sandbox recovery demonstration, not target recovery or production backup.
- Risk analysis is policy-engine output; a risk score is not a complete live row-impact estimate. Checks marked `not_run` remain unverified.

### Not implemented or unresolved

- Target database migration/apply endpoint.
- Authentication in the current local configuration and real Entra setup/testing.
- Automated checkpoint retention/cleanup policy.
- Host-loss/independent disaster recovery.
- Current online npm/Python vulnerability status.
- A separate Phase 6D exact result block in the inspected repository evidence.

## G. Production-readiness assessment

**Development-ready for a controlled local demonstration; not production-ready.**

The project has credible evidence for planning, risk analysis, artifact generation, sandbox validation, checkpoint recovery and workflow history. The safety design intentionally prevents target apply. However, the local app is unauthenticated, real multi-user approval is unproven, the previously exposed Azure key has not been rotated, and production TLS, secrets, network boundaries, logging/monitoring and independent recovery are not established. The dependency audit is also currently blocked by registry access. Do not expose this development configuration to a shared or public network and do not enable target execution.

## H. Mentor demonstration checklist

Use only a controlled local setup and isolated disposable sandbox data. Before the presentation, confirm the actual ports and database identities from the local environment. Do not use a production or teacher-owned database.

1. **Natural-language request** — Enter a supported request such as adding a nullable text column to an existing table. Expected: the UI submits the request and shows loading/error states. Avoid claiming every natural-language phrasing is supported; ambiguous requests can ask for clarification or fall back deterministically.
2. **Migration plan** — Review the structured operation, affected table/column and interpretation path. Expected: `proposed` for a supported request or explicit clarification/rejection. LLM output is not executable SQL.
3. **Risk analysis** — Show the severity and reasons. Compare a nullable addition with a required/no-default or destructive change. Expected: policy may block artifact generation for unsafe changes; `not_run` data checks mean row-level impact was not measured.
4. **SQL artifact** — Generate and inspect the upgrade/downgrade artifact. Expected: artifact ID is shown and `applied=false`. Generation is not execution.
5. **Sandbox validation** — Run validation against the configured sandbox only. Expected: validation result and individual checks appear. Some checks, including target-related checks, remain `not_run`; no target DB is touched.
6. **Validation evidence** — Open Workflow Details and show the persisted artifact/session association, passed checks, warnings and skipped checks. Expected: saved evidence remains associated with the workflow after refresh. Do not imply omitted evidence was inferred.
7. **Migration downgrade** — Use the distinct downgrade action. Expected: downgrade SQL executes only in the sandbox and reports schema result. For dropped-column data, a recreated column cannot restore its old values; `partial_restoration` is not full data recovery.
8. **Snapshot recovery** — Separately restore from the pre-migration checkpoint. Expected: `restore_verified` only when schema and data fingerprints match within supported scope; checkpoint remains retained. This is not production backup/DR.
9. **History and refresh** — Refresh the browser, reopen Migration/History, and show the same workflow/session evidence. Expected: recorded workflow state persists; this does not establish OIDC multi-user access.
10. **Safety report** — Show eligibility, blockers, missing evidence and state. Expected: it distinguishes review eligibility from approval and application. No human approval should be claimed without a separate authenticated approver record.
11. **Target boundary** — State and show that target execution is disabled and no apply endpoint exists. Expected: artifact generation, validation, downgrade and snapshot restore are sandbox/review operations only.

## I. Outstanding work, prioritised

### Critical before any shared or production deployment

- Rotate the previously exposed Azure API key with an Azure account owner; replace it privately and verify the replacement. Until then, restrict it to approved local testing.
- Keep target execution and startup migrations disabled.
- Do not expose the current unauthenticated local console to a shared network.

### High

- Configure Microsoft Entra and verify real role/group claims with separate test accounts.
- Verify an Engineer-to-Approver workflow with distinct identities, including approval-time fresh schema evidence and audit attribution.
- Establish production TLS, strict host/CORS policy, network segmentation, secret-manager injection, log redaction/retention, monitoring and operational access controls.
- Reconcile the README sandbox port-binding statement with the Phase 6E inventory before relying on the documentation for network exposure.
- Establish independent encrypted backup and regularly exercised recovery if production data is ever in scope.

### Medium

- Resolve checkpoint retention duration, quota, cleanup ownership and audit policy without deleting active/only recovery evidence.
- Extend recovery testing to additional interruption points and define unsupported snapshot object types.
- Rerun dependency audits with network access; review the previously reported moderate Vite advisory and run a Python vulnerability scanner through an approved dependency workflow.
- Preserve exact Phase 6B/6D command transcripts, warning/skip reasons and durations in the project evidence so future reports do not rely on conversation history.

### Low

- Improve classroom documentation and demo scripts to explain `not_run`, partial downgrade, snapshot scope and the difference between review, approval and execution.
- Keep the TODO current after each verified test run; do not count skipped/deselected tests as passes.

## J. Final viva preparation

**What does SchemaPilot do?**  
It turns natural-language schema requests into structured migration plans, assesses policy risk, generates review artifacts and validates them in an isolated PostgreSQL sandbox. It records workflow evidence. It does not apply migrations to a target database.

**Why use Docker and PostgreSQL?**  
Docker provides separate local PostgreSQL services/volumes for app metadata, demo source data and sandbox validation. The separation reduces accidental cross-database effects, but deployment network and credential controls still matter.

**What is Alembic used for?**  
Alembic represents schema changes as versioned upgrade/downgrade migration modules. SchemaPilot generates reviewable artifacts; application startup does not automatically apply them.

**What is the difference between downgrade and snapshot recovery?**  
Downgrade runs the migration’s reverse operation. Recreating a dropped column does not recover its former values. Snapshot recovery replaces the sandbox from a retained pre-migration clone and verifies schema/data fingerprints within the supported scope. The two results are recorded separately.

**Does a successful sandbox test prove the target migration is safe?**  
No. It is evidence from an isolated sandbox, and some checks can remain `not_run`. Target execution is disabled and no apply route exists.

**What happens if Azure fails or returns unusable output?**  
SchemaPilot can use deterministic fallback for supported requests or ask for clarification/reject invalid requests. Fallback output still goes through schema, risk and SQL validation. A provider configured in `.env` is not proof of successful inference; live AI success was separately recorded in earlier workflow evidence.

**Does the system use AI to execute SQL?**  
No. AI may help interpret a request. The server validates structured operations, risk and generated SQL before sandbox validation; target execution is not implemented.

**Is there human approval?**  
There is an approval-recording code path designed for an authenticated Approver and fail-closed when authentication is unavailable. Real Entra accounts and a separate proposer/approver journey were not verified. A UI confirmation is not human approval.

**Why is target execution disabled?**  
The project has not established production identity, approval, operational safeguards and recovery controls. Keeping apply unavailable prevents a planning/demo tool from modifying real target data.

**Is snapshot recovery a production backup?**  
No. The tested checkpoint is a same-cluster sandbox clone with a defined but limited fingerprint scope. It does not protect against cluster/host loss and does not verify all PostgreSQL objects.

**What does `not_run` mean in a report?**  
That check did not execute and provides no evidence. It must not be presented as a pass or as proof of no impact.

**Is SchemaPilot production-ready?**  
No. It is development-ready for a controlled local demonstration. Authentication is off, real human approval is unproven, the exposed Azure key needs owner rotation, and production infrastructure/security/recovery controls remain outstanding.

## Evidence and repository state notes

- At report preparation, the current branch was `main`. `git status --short` showed extensive pre-existing modified and untracked files across application code, tests, docs, Docker configuration, local test runtimes, generated artifacts and temporary pytest data. They were not reset or cleaned. This Phase 6G task adds only this report.
- The exact report path was checked and did not exist before creation.
- Phase evidence that existed only in conversation (including the Phase 6C summary) is labelled as reported evidence. Where the inspected TODO did not retain the exact command, warning count, duration or skip reasons, this report says so rather than reconstructing them.
- Phase 6F’s latest `npm audit` could not reach the registry due DNS. No dependency changes were made.
- This report itself did not run tests, inspect live database contents, start services, or verify current Docker state.
