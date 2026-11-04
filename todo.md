# SchemaPilot TODO

## Phase 5 browser acceptance and Phase 4 route-test refresh — 3 November 2026

This newest status supersedes the browser-pending and route-runner-blocked
items in the previous Phase 5 refresh. No production implementation code
changed in this continuation.

- [x] Reconfirmed the approved disposable PostgreSQL container was healthy,
  used its existing `schemapilot-phase5-e2e-20261103-pgdata` volume, and was
  bound only to `127.0.0.1:58862`. Actual Docker ID:
  `ae903b3559399733d3823898ebbb4b92994ae7e8f5b725387ddddecab2419973`.
- [x] Opened the Migration screen in Chrome at `http://127.0.0.1:5175/#migration`.
  The isolated backend ran on 8010 from a fresh temporary copy of app code;
  its health reported target execution false, startup migrations false, and
  target database unconfigured.
- [x] Generated unapplied artifact `sp35e72fa557d8` for nullable text column
  `users.phase5_browser_evidence`; the UI showed `applied: false`. Risk was
  `SP-R005 low/info` and artifact eligible.
- [x] Browser sandbox validation passed. The UI and persisted Workflow Details
  show **11 passed** checks and two `not_run` checks (`risk_row_checks` and
  `target_database`); the column check and nine table row-count checks passed.
- [x] Ran the distinct **Test migration downgrade** action. Persisted evidence
  records `downgrade_executed=true`, `schema_matches_baseline=true`, and
  `partial_restoration`; downgrade, schema fingerprint, and baseline row
  checks passed, while `former_column_values` is explicitly failed because a
  downgrade cannot claim to restore values in a removed column.
- [x] Ran the distinct **Restore sandbox from the saved checkpoint** action.
  The browser showed `restore_verified`, schema match true, data match true,
  and checkpoint retained true. All four checkpoint/sandbox schema and data
  verification checks passed. A separate read-only schema API check returned
  HTTP 200, found nine tables, and confirmed the test column was absent.
- [x] Generated the safety report: `eligible_for_review=true`,
  `approved=false`, `applied=false`, with no blockers or missing evidence.
  The report also states that separate pre-existing-sandbox preservation
  evidence is not recorded; that evidence was not inferred or fabricated.
- [x] Saved workflow `fb6d4915-cfaf-43a0-a571-bd98bfd4f869` to the disposable
  app metadata database. Refreshed Chrome, reopened History, and opened
  Workflow Details. The record remained `report_ready`, eligible, current,
  and showed the same validation, downgrade, and snapshot outcomes plus the
  `workflow_persisted` audit event.
- [x] Phase 4 route-test diagnosis: faulthandler localized the hang to AnyIO's
  Starlette TestClient portal startup, where the Windows asyncio loop blocks
  in `_fallback_socketpair()` / `_make_self_pipe()` before the first route
  assertion. Running the complete `tests/test_acceptance_phase12.py` outside
  the restricted socket sandbox produced **10 passed, 2 deprecation warnings**.
  No tests were changed or weakened.
- [x] Persistent app-db, demo-db, sandbox-db, Phase 2/3 resources and target
  were not accessed by this browser run. The app/history and sandbox logical
  databases used by the workflow were in the approved disposable container.
  Target execution and startup migrations remained disabled. No human approval
  was recorded; authentication remains unavailable.
- [ ] A separate pre-existing-sandbox preservation event is not demonstrated
  by this direct, in-place browser workflow; Workflow Details correctly says
  that evidence was not recorded. This is distinct from the verified
  pre-migration checkpoint and its restored schema/data fingerprints.
- [x] Phase 6 was not started.

## Phase 5 remediation refresh — 3 November 2026

This section supersedes the earlier Phase 5 acceptance-gap status below. It
records work on validation-evidence propagation and on separating migration
downgrade from snapshot recovery. It does not claim the browser acceptance
journey is complete.

- [x] Persist the real sandbox validation result and a sanitized baseline
  summary in the checkpoint session, bound to the artifact ID/checksum and
  snapshot session ID. Missing or mismatched evidence fails closed.
- [x] Feed the same persisted validation, baseline, downgrade, and snapshot
  evidence to safety reports and workflow history. Baseline summaries omit
  row values and sensitive connection data.
- [x] Add a separate sandbox-only migration-downgrade API action. Downgrade
  execution/result is recorded independently; snapshot recovery does not imply
  a downgrade, and a downgrade does not claim lost values were restored.
- [x] Add separate Migration-screen actions and outcome labels for migration
  downgrade and checkpoint restoration; display saved validation evidence
  after session discovery.
- [x] TDD Red evidence: session evidence tests first failed because checkpoint
  status had no validation-run field; the downgrade route test failed because
  that route did not exist; the UI contract test failed because the downgrade
  action label was absent. The failures reached the intended contracts.
- [x] Green focused backend checks: sandbox-workflow and rollback tests
  **39 passed, 1 deselected**; workflow-store tests **15 passed, 1 deselected**.
- [x] Disposable PostgreSQL rollback/snapshot/crash-recovery suite:
  **18 passed** on `schemapilot-phase5-e2e-20261103-pg`; app workflow
  persistence integration: **1 passed**. The approved name and volume matched;
  Docker reported actual container ID
  `ae903b3559399733d3823898ebbb4b92994ae7e8f5b725387ddddecab2419973` (the ID
  previously transcribed in the prompt omitted `387`).
- [ ] Browser acceptance remains pending. The isolated backend on port 8010
  returned health HTTP 200 with target execution, startup migrations, and LLM
  disabled. The first temporary Vite server timed out; after restarting it
  with the authorized local network context, the Vite root returned HTTP 200.
  Browser navigation was attempted, but Computer Use stopped before it could
  inspect the destination because it could not determine the current browser
  URL with sufficient confidence. No UI workflow result is claimed. The
  temporary Vite config was removed and both test servers were stopped.
- [ ] Phase 4 acceptance route tests were attempted but the Windows Starlette
  TestClient runner stalled before producing a summary; the run was stopped
  and is not counted as passed.
- [x] Ruff, Python compilation, and `git diff --check` passed after the
  implementation/test changes (Git emitted only existing LF/CRLF warnings).
- [x] Target execution and startup migrations remained disabled for the test
  backend; no target URL was configured. No persistent app-db, demo-db,
  sandbox-db, Phase 2, or Phase 3 resource was accessed by the Phase 5 tests.

Remaining in Phase 5: complete the browser journey (validation evidence after
refresh, separate downgrade, separate snapshot restore, report/history
readback) when the isolated Vite endpoint is reachable. Phase 6 has not
started.

## Phase 4 — Security, permissions and approval boundaries — 3 November 2026

This phase reviewed the implemented security boundaries and corrected one
misleading authentication-status response. It did not enable authentication,
target execution, startup migrations, or change database behavior.

- [x] Map API routes to authorization dependencies and services. Health/auth
  routes are public; source, plan, risk, artifact, sandbox, safety and workflow
  APIs are protected when OIDC is enabled. Engineer/Approver role checks are
  server-side; CSRF is required on authenticated mutations.
- [x] Confirm target execution is not implemented: no apply route or background
  target executor exists, and the target preflight always rejects. Planning and
  artifact generation do not execute SQL; sandbox execution accepts only the
  server-configured, validated sandbox URL.
- [x] Review approval controls: an authenticated Approver is required, the
  workflow owner cannot self-approve, client-supplied identity is ignored, and
  persisted approval is evidence only. With OIDC disabled, approval recording
  fails closed. No approval or target execution was fabricated.
- [x] TDD Red/Green: added a regression asserting that `/auth/me` does not claim
  `authenticated=true` when OIDC is disabled. Red reached the assertion and
  failed (`authenticated` was true while `user` was null); Green changes the
  response to `authenticated=false` while preserving local-console workspace
  access.
- [x] Verified provider output and SQL-generation boundaries by inspection and
  existing regression tests: LLM output is structured/untrusted, plan/risk
  validation remains authoritative, and sandbox SQL is constrained by the
  validator. No SQL was executed during this phase.
- [x] Verified the local configuration has
  `SCHEMAPILOT_TARGET_EXECUTION_ENABLED=false` and
  `SCHEMAPILOT_ALLOW_APP_MIGRATIONS=false` without displaying other settings.
- [x] Focused auth/configuration/SQL/planner/risk/workflow-store tests: **78
  passed, 5 route tests deselected, 2 deprecation warnings**. Phase 12 target
  execution and approval acceptance tests: **6 passed, 4 deselected, 2 warnings**.
- [ ] Full security/API test files could not complete: the Windows runner
  stalled during Starlette TestClient initialization after two tests. No
  incomplete run is counted as passing. The deselected route tests need a
  functioning HTTP test runtime for a later verification pass.
- [x] No Phase 4 PostgreSQL integration was required for the response-status
  correction. No Docker resource was created or changed, and no database was
  contacted in this phase.
- [ ] Authentication remains disabled locally; configure Entra and verify real
  role/group claims and multi-user isolation before claiming authenticated
  approval support. The repository's OIDC behavior is mock/unit tested only.
- [ ] Approval does not execute a migration. A live, fresh schema-evidence
  check at approval time and a full authenticated Engineer-to-Approver journey
  remain unverified; target execution remains unavailable.
- [ ] Production deployment security, secret rotation, TLS, log collection,
  network policy and backup controls remain release work. This review is not a
  production security certification.

Files changed for Phase 4: `backend/app/api/auth.py`,
`backend/tests/test_auth.py`, `docs/authentication.md`, and this checklist.

## Phase 5 — End-to-end workflow reliability and acceptance — 3 November 2026

This update records the live Phase 5 acceptance run on the approved disposable
PostgreSQL container `schemapilot-phase5-e2e-20261103-pg`
(`ae903b3559399733d3823898ebbb4b92994ae7e8f5b725387ddddecab2419973`), using
only its named volume `schemapilot-phase5-e2e-20261103-pgdata` and loopback port
`127.0.0.1:58862`. App, demo, and sandbox logical databases used in this run
were all inside that one disposable container. Existing project and Phase 2/3
containers and volumes were not modified.

- [x] Inspected the Migration screen, API client/contracts, FastAPI plan,
  artifact, sandbox, rollback, safety-report, and workflow-history routes. The
  UI carries artifact and snapshot-session identifiers across validation and
  recovery. History reads did not invoke rollback/recovery in the browser run.
- [x] Confirmed the repository has frontend API client and contract tests, but
  no component-level or browser E2E test suite.
- [x] Reconfirmed exact Phase 5 container ID, healthy status, loopback-only
  published port, and sole named data volume. The disposable sandbox role was
  granted `CREATEDB` inside this Phase 5 container because checkpoint cloning
  requires it; no other database role or container was changed.
- [x] Backend rollback/snapshot/process-crash integration suite: **17 passed**.
  It includes downgrade, snapshot recovery, and the Phase 2 interruption point.
- [x] Other live PostgreSQL tests: app workflow persistence **1 passed**;
  demo bookstore **5 passed**; schema inspection **2 passed**; sandbox
  validation **8 passed**. All used only the Phase 5 logical databases.
- [x] Browser plan and risk: deterministic plan proposed the nullable
  `phase5_note` column; SP-R005 classified it low/info and artifact-eligible.
  Artifact `sp0a0b70c5c530` remained unapplied.
- [x] Browser sandbox validation passed: the nullable column check and all nine
  seeded table row-count checks passed. The UI explicitly left `target_database`
  and `risk_row_checks` as `not_run`.
- [x] Browser refresh/resume: after refresh, the Migration screen rediscovered
  an active `ready` checkpoint session; the user-facing resume action returned
  `restore_verified`. A read-only schema/data/sequence fingerprint comparison
  against the retained checkpoint passed; the test column was absent and all
  nine row counts matched (12, 5, 18, 17, 12, 9, 8, 8, 10).
- [x] A second browser flow generated artifact `sp6a9dcdfdee7c`, validated it,
  and restored its checkpoint. The report showed `schema_match=true`,
  `data_match=true`, and `checkpoint_retained=true`.
- [ ] **Acceptance gap:** this UI rollback endpoint performs snapshot restore,
  not migration downgrade. Consequently the generated safety report accurately
  listed missing `sandbox upgrade` and `baseline evidence`, was not eligible for
  review, and History showed no sandbox evidence even though validation had
  passed. Workflow `3857413b-ac86-4e8a-b69a-304786bd589f` was persisted as
  blocked and read back successfully. Do not mark the full browser journey
  complete until the product workflow can retain the sandbox validation evidence
  and the intended downgrade evidence without confusing downgrade with snapshot
  restore. No production-code change was made for this finding in Phase 5.
- [x] A full backend run first produced a valid Red failure caused by a test
  fixture reusing a deterministic checksum. `backend/tests/test_workflow_integration.py`
  now uses `uuid4()` for that test-only checksum. Focused rerun: **1 passed**.
- [x] Full backend suite after the test-only correction: **226 passed,
  1 skipped** (live LLM disabled), 2 Authlib/Starlette deprecation warnings.
- [x] The full integration run left its disposable sandbox without the seeded
  bookstore schema. Re-running the packaged seed restored the nine tables and
  expected row counts, but seeded values did not match the earlier checkpoint.
  Restored the Phase 5 sandbox from retained checkpoint
  `e71b3ff4c5b24843932a1d547b8e07d3`; final read-only verification returned
  `restore_verified`, matching schema and data/sequence fingerprints, with the
  checkpoint retained. No persistent sandbox was involved.
- [x] Focused workflow/rollback/history/security subset: **56 passed**,
  2 deprecation warnings. Rollback suite independently: **17 passed**.
- [x] Frontend tests: **11 passed** across 2 files. TypeScript check and
  production build passed; the build wrote to a fresh temporary output folder
  outside the repository.
- [x] Ruff: clean. Python compilation: passed. `git diff --check`: passed with
  existing LF/CRLF warnings.
- [x] Live health reported `target_execution_enabled=false`,
  `migrations_on_startup=false`, and LLM disabled. No target URL was configured,
  no human approval was recorded, and no target migration ran.
- [x] Browser console had no errors during the final workflow/history check.
- [ ] Windows would not bind the backend to port 8000 (`WinError 10048`), and
  port 5173 was already occupied. For the browser run only, the backend used
  loopback port 8001 and Vite used 5174 with a temporary proxy config; no
  repository application configuration was changed.

Phase 5 is **partially verified, not fully accepted** because the UI safety
report/history omitted the successful sandbox validation evidence and the UI
does not perform the downgrade stage. Full backend/frontend tests and snapshot
refresh/resume passed on the approved disposable resources. No Phase 6 work has
started. The Phase 5 container and volume are retained.

## Classroom database showcase — 30 October 2026

- [x] Expanded the existing `bookstore-demo` database additively, preserving its prior rows. It now has 9 related tables and 12 foreign-key relationships, with synthetic populated records: 10 users, 5 categories, 8 products, 12 addresses, 12 orders, 17 order items, 9 payments, 8 reviews, and 18 inventory movements.
- [x] Verified the seed with `python -m app.demo verify`; the demo source contains the classroom dataset. A read-only metadata check confirmed the temporary `orders.internal_note` migration column is absent from both demo and sandbox after rollback.
- [x] Risk walkthrough on the populated schema: nullable column = low/info; nullable column with default = medium/warning and blocked pending row-data check; required column without default = high/policy-blocked; dropping `products` = high/destructive with dependent objects identified. `data_check=not_run` means row-level impact was not measured.
- [x] Generated review-only artifact `spf24a2d9943d5` for adding nullable `internal_note` to `orders`. SQL matched the plan; artifact remained unapplied.
- [x] Sandbox validation passed 12 checks; 2 remained `not_run` (`risk_row_checks`, `target_database`). Rollback returned `partial_restoration` as expected for a column whose test value is discarded; baseline was restored. Demo and target were untouched.
- [x] Recorded and read back workflow `7bc5fa64-bc7a-4445-afdd-9b69961b91f7` in History as `report_ready`, eligible for review, not approved, and not applied.
- [ ] Human approval cannot be demonstrated yet: authentication is unavailable. Do not fabricate approval; keep the workflow unapproved and target execution disabled until a separate authenticated Approver is configured.
- [x] Final backend checks for this change: Ruff clean; non-integration suite **163 passed, 1 skipped, 20 integration tests deselected** (live LLM test skipped). No integration test was run against persistent databases in this verification pass.

The risk engine currently applies policy rules; despite populated demo tables, it does not infer row-level effects unless a check explicitly says it ran. Use the synthetic Bookstore data for the teacher demonstration. The additive upgrade is intended for the original Bookstore baseline and refuses unexpected database states; do not use it as a reset or run it against app, sandbox, or target databases.

## Snapshot recovery work — 30 October 2026

This is the active rollback and checkpoint work stream for SchemaPilot.

- [x] Create a pre-migration sandbox checkpoint before destructive migration testing.
- [x] Restore the sandbox from the retained checkpoint after downgrade testing.
- [x] Verify the restored sandbox matches the original baseline schema and data.
- [x] Reject tampered checkpoints so SchemaPilot does not report a successful restore.
- [x] Keep the demo/source database and real target database outside the checkpoint path.
- [x] Verify target execution remains disabled; keep production apply, authenticated human approval, and sandbox rollback as separate evidence streams. Focused acceptance, database-safety, and rollback tests passed (29 total).
- [x] Finalize the docs/UI wording that explicitly distinguishes a PostgreSQL sandbox checkpoint from a production backup. UI now identifies a same-cluster PostgreSQL clone for sandbox recovery only; frontend tests (10 passed) and production build passed.
- [x] Confirm available user guidance reflects the same sandbox-only model; no standalone release-notes file is present.

### Snapshot recovery hardening — 1 November 2026

This section tracks the snapshot recovery handoff as well as the earlier snapshot primitives. Status below reflects the latest review on 1 November 2026. The frontend checks passed today; backend checks could not be launched from this environment, and Docker was unavailable, so the new PostgreSQL handoff has not been live-verified here.

**Scope decision:** snapshot/restore remains limited to `sandbox-db`. `app-db` and `demo-db` may be checked for availability but must not be reset, seeded, or restored by this feature. The target database remains outside the system and disabled.

- [x] Capture and verify the sandbox state before sandbox validation can reset/reseed the packaged baseline. Bind the retained checkpoint to the exact artifact and session; after rollback testing, restore this original state.
- [x] Replace the destructive drop-and-recreate restore with a verified replacement clone and a rename-based swap. Keep the previous database until the new canonical sandbox matches the checkpoint; attempt compensation if the swap fails.
- [x] Make the safety-report endpoint load saved rollback evidence instead of running rollback again. Workflow persistence uses the same stored evidence and does not rerun destructive sandbox work.
- [x] Store rollback evidence atomically and bind it to the artifact checksum; reject modified or mismatched evidence.
- [x] Serialize sandbox resets, migration tests, checkpoint creation, and restores with a PostgreSQL advisory lock; map an unavailable database to a safe unavailable result.
- [x] Set the Compose database host bindings to loopback (`127.0.0.1`). Runtime verification on 1 November confirmed the sandbox container is healthy and publishes PostgreSQL only at `127.0.0.1:5433`.
- [x] Bind rollback evidence, safety reports, and persisted workflows to the same artifact and snapshot session. Prevent replay of completed sessions and block new validation while a prior session still needs recovery.
- [x] Add regression coverage for snapshot-before-validation ordering, required session IDs, session replay/state checks, report-read side effects, evidence tampering, failure/unavailable paths, and loopback Compose binding. Previously recorded tests (before the latest session-handoff edits): backend **175 passed, 1 skipped, 27 integration tests deselected**; Ruff clean. Frontend: **10 tests passed** and production build/type check passed.
- [x] Re-run Ruff against the latest session-handoff code: **clean**.
- [x] Re-run focused sandbox-only regression tests against the latest session-handoff code (**7 passed**); Ruff is clean. (Supersedes the earlier environment failure below.)
- [x] Run and verify the live sandbox validation and recovery path without reset/reseed; the browser refresh and resume are recorded in the 1 November execution update above.
- [x] Complete browser verification of checkpoint discovery after refresh and execute the Migration screen resume action against the live backend/sandbox.
- [ ] Add recovery/reconciliation instructions and a tested operator procedure for a process or machine crash between PostgreSQL database rename steps.
- [x] Add a supported way to discover and resume an interrupted checkpoint after a browser refresh. The status API returns only safe session state; the Migration screen requires an explicit confirmation before resuming sandbox recovery.
- [ ] Define an explicit, auditable checkpoint retention and cleanup policy. Checkpoints are currently retained indefinitely; do not delete them automatically.
- [ ] Protect rollback evidence and backups with production-grade access controls, encryption, off-host storage, monitoring, and restore drills before any production use.

### Browser refresh-and-resume execution — 1 November 2026

This update supersedes earlier pending browser and focused-test statements for the sandbox-only workflow verified in this pass.

- [x] Added regression tests first and observed expected failures before implementation; the focused suite now passes (**7 passed**).
- [x] Sandbox planning uses the server-configured sandbox source and does not inspect or connect to `demo-db`.
- [x] Validation no longer drops/reseeds the existing bookstore schema; it checkpoints the current sandbox state, then applies the artifact only in that sandbox.
- [x] Failed checkpoint creation blocks migration execution; failed or mismatched restore evidence cannot report success and keeps recovery required.
- [x] Browser flow: planned a nullable-column change, generated artifact `spfb4fc3f8b8be`, validated it, refreshed the page, rediscovered checkpoint `8005d1a79ea64e88bc70e1f1be6b07bb`, then resumed through the Migration screen.
- [x] Recovery returned `restore_verified`. Session `bfc753e39f034eda911461689bdbd7e2` is `completed`; checkpoint is retained.
- [x] Read-only sandbox verification matched schema fingerprint `468fc1b7189d95ebad273a72ddc61854ae197a1daa71ae0efa328a51e94ed988` and data fingerprint `a2fc9426fc925ac6f0ef4df201b8741f7ba42ea7d6b4dbec3976f910f5c87c74` to the original baseline. All nine row counts matched and the test column is absent.
- [x] Target execution and startup migrations remain disabled. No app-db/demo-db/target connections or changes occurred; migration validation and final read-only verification used only `sandbox-db`.
- [x] Final local checks: Ruff clean; focused regression tests **7 passed**; frontend tests **11 passed**; TypeScript check and production build passed.
- [ ] The broader backend test command did not yield a final summary and was stopped; run the full backend suite before release.

### Latest verification — 1 November 2026

- [x] Frontend tests: **11 passed**. TypeScript check and production build passed after adding the recovery-session API contract test and UI path.
- [x] Added backend regression coverage for active-session discovery and the frontend recovery UI path. Ruff and frontend checks pass; focused backend tests are recorded in the later execution update.
- [x] Established test-first red/green evidence for the new recovery tests: expected failures before implementation; **7 passed** after implementation.
- [ ] Full backend regression suite: not completed in this pass. A broader focused test command remained active without a final summary and was stopped; rerun the complete suite before release.
- [x] Live PostgreSQL snapshot/restore and browser refresh/resume verified against isolated sandbox-db; schema and data fingerprints matched the original baseline.
- [x] Safety settings remain `SCHEMAPILOT_TARGET_EXECUTION_ENABLED=false` and `SCHEMAPILOT_ALLOW_APP_MIGRATIONS=false`; no target database action or migration was performed.

### Production-grade snapshot gates — remaining

- [x] Complete a test-first red/green run of the new sandbox-only recovery tests (**7 passed** after implementation).
- [x] Run live snapshot creation, sandbox validation, browser refresh/resume and exact schema/data comparison against only the isolated sandbox. Failure paths are covered by backend regression tests.
- [x] Exercise browser refresh/recovery against the live backend and sandbox; the saved checkpoint was rediscovered and resumed successfully.
- [x] Test process-crash recovery after the first committed database rename. A fresh API process discovers and resumes the checkpoint. Other crash timings, host crashes, and storage loss remain unverified.
- [x] Document the precise current `restore_verified` scope: inspected bookstore tables/columns/constraints/indexes/foreign keys plus canonical base-table row contents and sequence `pg_sequences.last_value`. Views, triggers, functions, extensions, roles/grants/ownership, database/cluster settings, large objects, and external dependencies remain outside the verification claim.
- [ ] Define retention, checkpoint quota/monitoring, and an auditable cleanup procedure; checkpoints are currently retained indefinitely.
- [ ] Before any production use, replace the same-cluster clone with an independently protected backup/recovery design: encrypted off-cluster storage, access control, retention, monitoring, and scheduled restore drills. The current feature is sandbox recovery, not production disaster recovery.
- [ ] Keep human approval and target execution separate. Authentication is unavailable and no target apply is implemented; do not claim production migration readiness.

### Phase 1 and Phase 2 follow-up — 3 November 2026

- [x] Phase 1 backend baseline: **188 passed, 1 skipped, 29 deselected, 2 warnings**; PostgreSQL integrations on three disposable tmpfs containers: **29 passed, 189 deselected, 2 warnings**; Ruff clean. Exact runtime and limitations are documented in `docs/backend-test-environment.md`.
- [x] Confirmed the original `backend/.venv` is unusable because it references missing Python 3.13.14. Tests ran with the available Python 3.13.17 `.test-runtime`; this is a working test runner, not a reproducible replacement venv. The original environment was not overwritten.
- [ ] Recreate a conventional project `.venv` from an installed supported Python distribution. A Python installer/launcher is not available in the current session.
- [x] Establish a genuine TDD Red against the explicitly disposable Phase 2 PostgreSQL container. The crash worker exited with code 86 immediately after the first committed rename; a fresh API process discovered the session/checkpoint, but resume returned `verification_incomplete` instead of `restore_verified` because recovery did not reconcile the existing staged database.
- [x] Implement minimal interrupted-swap reconciliation. On resume, verify/reuse a matching staged clone or recreate it from the retained checkpoint, promote it, verify schema and row fingerprints, and retain the previous database until verification passes. Missing checkpoint, mismatched/corrupt stage and unexpected states fail closed.
- [x] Process-crash integration: **16 passed** in `backend/tests/test_rollback_integration.py`, including hard process termination after rename one, fresh API discovery and resume, repeat-request rejection, direct idempotency, missing-stage rebuild, missing-checkpoint handling, and failure cases. This is one tested interruption point, not all possible crash timings.
- [x] Relevant backend unit tests: **26 passed, 1 deselected, 2 warnings**. `test_rollback_route_does_not_open_a_database` was deselected because the Windows app-container runner stalled while Starlette TestClient initialized its Proactor socketpair; the stall was in the test runtime, not an application assertion.
- [x] Ruff passed for the complete backend (`app tests alembic`); Python compilation checks passed for the modified recovery service and integration test; `git diff --check` passed (only line-ending warnings were reported).
- [x] All crash-recovery testing used only the approved disposable container `schemapilot-phase2-crash-20261103-pg` (ID `5b7282f43b8991d8827099191f7007eef025ee239b5feb0a8e418fd64a5baafd`) and volume `schemapilot-phase2-crash-20261103-pgdata`; no persistent app-db, demo-db, or sandbox resource was used.
- [ ] Recreate a conventional project `.venv` from an installed supported Python distribution. The original environment remains unusable because it references missing Python 3.13.14; Phase 2 used Python 3.13.17 from `.test-runtime`.
- [ ] Re-run the complete Phase 1 backend suite after this implementation in the normal Windows developer session. The focused unit and rollback integration suites passed; the full suite was not rerun in this phase.
- [ ] Test additional process-crash timings, including after promotion and during post-promotion verification, on disposable infrastructure only.

**Phase 2 isolation check:** The disposable PostgreSQL container is healthy and publishes only `127.0.0.1:58861`; its sole data mount is `schemapilot-phase2-crash-20261103-pgdata`. Existing persistent app-db (`a0d451376d66`), demo-db (`9386899b4305`), and sandbox-db (`c227572463be`) retain their original IDs and were stopped before and after this test. No application, demo, persistent sandbox, or target database was used. `SCHEMAPILOT_TARGET_EXECUTION_ENABLED=false` and `SCHEMAPILOT_ALLOW_APP_MIGRATIONS=false` remain in force. The test container and volume are intentionally retained; no cleanup or checkpoint deletion was performed.

## Phase 3 — Snapshot and checkpoint reliability — 3 November 2026

- [x] Read-only code/test review covered checkpoint creation, physical clone verification, report/history read paths, session metadata storage, restore staging/promotion, cleanup, and current fingerprint scope. Existing Phase 2 crash recovery, corrupt/missing checkpoint and rename-failure tests were not duplicated unnecessarily.
- [x] TDD Red: four focused regressions reached their intended assertions and failed against the prior store implementation: completion without verified restore evidence; replacing the checkpoint ID/baseline during a session; saving incomplete “verified” metadata; and saving mismatched test-restore fingerprints.
- [x] Green: checkpoint sessions now require a valid 32-hex checkpoint ID, retained checkpoint, verified status, non-empty baseline fingerprints, and matching schema/data fingerprints from the checkpoint test restore. Reads apply the same validation.
- [x] Green: session transitions follow the allowed state graph; completion requires `restore_verified` plus `schema_match=true` and `data_match=true`. Checkpoint identity and baseline fields cannot be changed during a session. A failed attempt to start a second validation leaves the active session record intact.
- [x] PostgreSQL sequence-state characterization: a disposable integration test confirms a change in `is_called` is reflected by PostgreSQL’s `pg_sequences.last_value` behavior and changes the data fingerprint. The final suite includes this test.
- [x] Focused checkpoint/rollback/workflow unit tests: **45 passed, 2 deselected, 2 warnings**. The deselected HTTP TestClient cases stall in this Windows runner’s Proactor socket-pair initialization. A separate attempt at four sandbox route tests was stopped after the same runner stall; it produced no test summary. Direct checkpoint discovery tests passed.
- [x] Disposable PostgreSQL rollback/checkpoint integrations: **17 passed**. Includes stage/clone/verification/rename failures, previous-canonical preservation, corrupt/missing checkpoint, sequence-state fingerprinting, and Phase 2 process-crash discovery/resume after the first rename.
- [x] Ruff across `app tests alembic`, Python compilation across `app tests alembic`, and `git diff --check`: passed. `git diff --check` reported only a Git line-ending warning for `docs/rollback.md`.
- [x] Safety-report and history side-effect review: safety reports inspect schema, may call the configured LLM, create a temporary artifact for comparison, and read saved rollback evidence; they do not restore/reset/reseed or write checkpoint state. Current workflow list/detail GET routes read app-db records; the detail route does not pass the optional fingerprint argument that would mark a workflow stale. No checkpoint deletion path exists.
- [x] Retention finding: checkpoints and session/evidence records have no automated expiry or cleanup. Active/recovery-required records block another validation; completed checkpoint clones are retained indefinitely. No arbitrary duration or deletion code was added.
- [x] Created only the new Phase 3 disposable container `schemapilot-phase3-checkpoint-20261103-pg` (ID `518e806d55f063183942a6908bb3260022c9fdcf30c3fe6cc4eeca58c07d0ba9`) and volume `schemapilot-phase3-checkpoint-20261103-pgdata`, bound to `127.0.0.1:53471`. Read-only SQL confirmed canonical sandbox present, **108 retained checkpoints**, and zero verify/replacement/previous/failed scratch databases. Test rows remained readable. The container and volume are retained; no checkpoint was deleted.
- [x] The app-db, demo-db, and persistent sandbox containers/volumes were not connected to or changed; original container IDs remain `a0d451376d66`, `9386899b4305`, and `c227572463be` (stopped at the final read-only inventory). No target URL was configured for test processes. `SCHEMAPILOT_TARGET_EXECUTION_ENABLED=false` and `SCHEMAPILOT_ALLOW_APP_MIGRATIONS=false` were verified.
- [ ] Define an owner-approved retention duration/quota and auditable operator cleanup process. Keep the only recovery checkpoint until an independent recovery copy and reference checks exist.
- [ ] Expand `restore_verified` coverage only if the product requires views, triggers/functions, permissions, large objects, database/cluster configuration, or external dependencies. Current status is limited to the documented fingerprint contract.
- [ ] Run the complete backend suite in the normal Windows developer environment; Phase 3 ran focused tests only. Repair the conventional `.venv` separately as already tracked.

Phase 3 changed `backend/app/services/sandbox_checkpoint_store.py`, focused tests in `backend/tests/test_rollback.py`, `backend/tests/test_sandbox.py`, `backend/tests/test_sandbox_only_workflow.py`, and `backend/tests/test_rollback_integration.py`, plus this TODO and `docs/rollback.md`. No frontend or Phase 4 work was started.

## Current status refresh — 30 October 2026

This section is the current status and supersedes stale LLM and runtime statements in the historical notes below.

### Verified in the latest workflow

- [x] After the user-approved change, `SCHEMAPILOT_LLM_ENABLED=true` is active in `backend/.env`; Azure provider, endpoint, deployment, and existing key were unchanged.
- [x] Existing Uvicorn backend PID 10804 responded on port 8000; health reported `llm_enabled=true`, `llm_configured=true`, provider `azure_openai`, target execution disabled, and startup migrations disabled.
- [x] Azure accepted a one-time authentication probe with HTTP 200. This confirms the configured key and deployment worked at that time; it does not remove the key-exposure risk.
- [x] SchemaPilot inspected `bookstore-demo` through the API (HTTP 200, four tables).
- [x] The same plan-only request, `Add a nullable text column called phone_number to users.`, returned HTTP 200 with `interpretation_path=llm_assisted`, `provider_status=ok`, one operation, and zero validation errors. No artifact was applied and no database data was changed.
- [x] AI-assisted artifact test: a separate unique nullable text-column request produced artifact `sp1236791d4f4d` (HTTP 200); generated SQL matched the plan, artifact stayed unapplied, downgrade removes only the new column, and reversibility is correctly marked partial because newly written values would be lost.
- [x] For the full AI workflow, existing `app-db` and `sandbox-db` containers were started; `demo-db` remained running. All three reported healthy. No app DB migration was run; its existing Alembic revision was `20261029_0002`.
- [x] Deterministic full-workflow evidence from 29 October remains valid; the 30 October AI-assisted workflow has now also completed the safety, sandbox, rollback, recording, and History stages.
- [x] The duplicate Uvicorn start failed with WinError 10048 because port 8000 was already owned by the existing Uvicorn process; the failed duplicate terminated. The active backend later responded to health checks. No process was killed.
- [x] AI-assisted safety report returned eligible for review with no blockers/missing evidence; it was not approved or applied.
- [x] AI-assisted sandbox validation passed: 7 checks passed, 2 remained `not_run` (`risk_row_checks`, `target_database`). The test used the approved sandbox-only reset/reseed; target and demo data were untouched.
- [x] AI-assisted rollback executed and matched the sandbox baseline; `partial_restoration` is expected because downgrading the added column can discard values written to it.
- [x] AI-assisted workflow `64a624b2-01a7-4e5b-b2b0-5c0759cd0259` was recorded as `report_ready`, eligible for review, unapplied; its audit records `llm_assisted` and provider status `ok`. History list/detail/audit all returned HTTP 200. Authentication was off; no human approval was recorded.
- [x] Read-only risk test: nullable `phone_number` column returned SP-R005 low/info, reversible, eligible.
- [x] Read-only risk test: required `account_code` without a default returned SP-R007 high/policy_blocked and was not artifact-eligible; live row data was not checked (`data_check=not_run`).
- [x] Read-only risk test: dropping `users.display_name` returned SP-R002 high/policy_blocked and irreversible, plus SP-R017 for dependent objects; not artifact-eligible.
- [x] The phrase `non-null` triggered clarification in deterministic planning; `required` was recognized. Record this wording limitation for interpretation/UI guidance.
- [x] Additional live AI interpretation: `Create an index on orders.placed_at.` returned HTTP 200, `llm_assisted`, provider `ok`, a proposed `add_index`, and zero validation errors. Plan only; no artifact or migration was applied.
- [x] Ambiguous live request `Add a column to users.` returned HTTP 200 with `needs_clarification` and three questions. Azure output was malformed for that request; deterministic fallback handled it without proposing an operation.
- [x] Full browser workflow on 30 October: AI plan, low-risk assessment, artifact generation, sandbox validation, rollback, safety report, app-db recording, and History/detail readback all succeeded for workflow `47a52305-8138-413e-8ea0-2aa8b0a69086`. The artifact remained unapplied; no approval was recorded.
- [x] Browser sandbox validation passed 7 checks; `risk_row_checks` and `target_database` stayed `not_run`. Rollback reported `partial_restoration`; a read-only SQL check confirmed the test column is absent from sandbox afterward.
- [x] Browser loading, plan-review, malformed-provider fallback, and unknown-table rejection states were observed. The UI gave a close-name suggestion and displayed no HTTP 500 during this journey.
- [x] Corrected Workflow Details: removed the misleading “Restore status unknown” label sourced from the earlier sandbox validation result; rollback status is displayed separately. Browser HMR, frontend tests, and production build all passed after the change.
- [x] Live malformed clarification response traced to an omitted allowed-topic list in the LLM prompt. The prompt now lists the schema's six accepted clarification topics, and a regression test covers that contract.
- [x] Restarted the existing Uvicorn backend once on the same host/port/configuration (new PID 26396); health stayed `ok`, Azure remained configured, target execution and startup migrations stayed disabled.
- [x] Retried the ambiguous request after restart: HTTP 200, provider `azure_openai`, but Azure still returned schema-invalid output. Deterministic fallback returned `needs_clarification`, three questions, zero operations, and zero validation errors. No artifact or database change occurred; the prompt addition did not eliminate this live malformed-response case.
- [x] Sanitized live validation diagnostics identify the invalid field category as `clarification_questions.topic`; raw provider output was not logged or shown. Deterministic fallback remains safe, but the live Azure clarification contract is still unresolved.
- [x] Repeated the ambiguous plan-only request against the current local backend: HTTP 200; Azure returned the same sanitized `clarification_questions.topic` validation error; fallback returned `needs_clarification`, three questions, zero operations, and zero validation errors. No artifact or database change was made.
- [x] Rechecked local health after the restart: `status=ok`, Azure enabled/configured, `target_execution_enabled=false`, `migrations_on_startup=false`, and authentication unavailable.
- [x] Re-ran local regression checks after adding Azure error-case tests: backend **163 passed, 1 skipped, 20 integration tests deselected**; Ruff clean; frontend **10 passed**; TypeScript check and production build passed. Two existing Authlib/Starlette deprecation warnings remain. The one skip is the opt-in live LLM test.
- [x] Recreated the existing PostgreSQL containers one at a time with their named volumes preserved. `app-db` and `demo-db` bind to `127.0.0.1`; `sandbox-db` remains on its previous host binding after Windows denied the loopback bind. All three are healthy. No data reset or migration was run.

### Remaining work, in priority order

#### Core migration verification

- [x] Test the planned nullable, required/no-default, and destructive-drop scenarios. Results are recorded above; deterministic risk checks passed for those cases.
- [x] Add a medium-risk scenario: nullable integer column with default `0` returned SP-R006 medium/warning, `data_check=not_run`, and `artifact_eligible=false` with reason `data_check_not_run`. The engine recommended reviewing the default and checking existing rows before artifact generation. This is a policy gate, not evidence that live rows were checked.
- [x] Generate and manually review an artifact with AI assistance enabled. Artifact `sp1236791d4f4d` was generated and not applied; its upgrade SQL matches the nullable text-column plan. The endpoint response does not include provider status, but an immediately preceding plan request for the same change returned `provider_status=ok`.
- [x] Complete AI-assisted safety report, sandbox validation, rollback, workflow persistence, and History readback (workflow `64a624b2-01a7-4e5b-b2b0-5c0759cd0259`).
- [x] Test another table/operation (`orders.placed_at` index) with Azure and an ambiguous request. The unsupported/malformed path safely fell back to clarification. Other unsupported-intent coverage remains in backend tests; no live unsupported request was sent.

#### AI reliability and UI

- [x] Verify the frontend API contract sends `use_llm=true` when AI assistance is selected: the contract test asserts the plan request body. This is automated contract evidence only; the full browser journey remains open below.
- [x] Browser verification: selected the index example, enabled AI assistance, and reviewed the visible plan. UI showed `llm_assisted`, provider `ok` (`azure_openai`), proposed `add_index` on `orders.placed_at`, and no validation errors. Plan-only; no artifact was generated.
- [x] Correct the migration screen's invalid index example from nonexistent `orders.created_at` to existing unindexed `orders.placed_at`; deterministic and live Azure plan-only requests both proposed `add_index` with zero validation errors.
- [x] Observed a malformed Azure result on an ambiguous request; SchemaPilot fell back safely to `needs_clarification` rather than proposing an operation. The prompt now enumerates allowed clarification topics, and the unit regression passes.
- [ ] Resolve the remaining live Azure schema-invalid clarification response. Retested plan-only through the current local backend: HTTP 200, Azure returned invalid `clarification_questions.topic`, and deterministic fallback returned `needs_clarification`, three questions, zero operations, and zero validation errors. Do not loosen the schema or expose raw model output; provider-side response behavior remains unresolved.
- [x] Exercise Azure failure handling with mocked 401/403 authentication/permission errors, 404 deployment-not-found, 429 throttling, and socket/URL timeouts. Provider errors are sanitized and the request is not retried for these cases; no live credentials or Azure endpoint were used. Live provider-side failures remain unverified.
- [x] Recheck UI loading, fallback, validation-error, and plan-review states. These states worked in the browser; no HTTP 500 recurred.
- [ ] Attribute the historical HTTP 500 only if its original failed request and traceback can be captured. The later `source_unavailable` 503 and duplicate-start WinError 10048 are separate, identified events.

#### Security and multi-user access

- [ ] Rotate the previously exposed Azure key with an Azure account owner. The user does not currently have Azure account access; the existing key remains unchanged and enabled for local development after explicit approval. Restrict use to local testing until rotation is available.
- [x] Restrict Docker-published PostgreSQL ports to loopback. Runtime verification on 1 November confirmed the sandbox publishes only on `127.0.0.1:5433`; app/demo were not queried or changed during this recovery workflow. (This supersedes the earlier note about the Windows bind conflict; confirm all service bindings again before deployment.)
- [ ] Complete the Engineer-to-Approver multi-user journey and record human approval through a separate authenticated Approver; no approval has been fabricated.
- [x] Keep `SCHEMAPILOT_TARGET_EXECUTION_ENABLED=false` and `SCHEMAPILOT_ALLOW_APP_MIGRATIONS=false`; health reports target execution and startup migrations disabled. No target apply or migration was run in the latest workflow.

#### Release readiness

- [x] Frontend unit tests rerun on 30 October: **10 passed** across 2 files. Tests include the `use_llm=true` plan request contract.
- [x] Frontend TypeScript check and production build rerun on 30 October: **passed**.
- [x] Final PostgreSQL integration run on temporary tmpfs app/demo/sandbox databases: **20 passed, 164 deselected**. Synthetic credentials were used; temporary containers were removed; persistent app/demo/sandbox volumes were not reset or modified.
- [x] Run the backend non-integration regression suite after the LLM prompt regression: **157 passed, 1 skipped, 20 integration tests deselected**, with two Authlib/Starlette deprecation warnings. Ruff passed. The earlier isolated PostgreSQL integration run remains recorded above (**20 passed**).
- [x] Run frontend unit tests (**10 passed**) and production build/type check (**passed**).
- [x] Update the README overview to describe current planning/sandbox capabilities and the no-target-apply, no-startup-migration, and unauthenticated-local-console limits. It now also documents the Compose host-binding limitation and named-volume behavior.
- [x] Review application error/logging paths: there is no app-wide logger; provider errors omit raw Azure response bodies; health returns configuration flags rather than URLs; sandbox/rollback errors redact database details; CLI output is limited to local demo commands. No production logging pipeline/configuration is present, so unhandled Uvicorn tracebacks still require restricted access in any deployed environment.
- [x] Complete the browser journey through risk, artifact, sandbox validation, rollback, report, and History. Workflow `47a52305-8138-413e-8ea0-2aa8b0a69086` was recorded and read back; approval/apply were not performed.
- [x] Review local deployment defaults and document the Compose host-binding limitation and named-volume behavior. `app-db` and `demo-db` are now loopback-only; `sandbox-db` still binds all interfaces. Existing target/startup safety flags remain off. This repository has no production Dockerfile/deployment manifest or production logging configuration.
- [ ] Add and review production deployment settings, including loopback/private DB access, TLS, secret injection, and controlled/redacted log collection. The exposed Azure key remains a release security blocker until an Azure account owner rotates it; no replacement key has been supplied.
- [ ] Configure Microsoft Entra and test role/group claims with real accounts. Authentication and the Engineer-to-Approver workflow remain intentionally deferred until tenant credentials and app registration are available.


## Current status refresh — 29 October 2026

### Verified in this pass

- [x] Backend Ruff check after auth changes: clean.
- [x] Focused auth, workflow-store, and health tests: **24 passed**; LLM provider tests: **18 passed, 1 skipped**.
- [x] Backend tests excluding live database integration after Azure adapter changes: **156 passed, 1 skipped, 20 deselected**, 2 dependency deprecation warnings.
- [x] Added explicit Azure OpenAI v1 adapter, using the Azure `api-key` header and requiring HTTPS Azure v1 endpoint. Added mocked regressions for URL, deployment field, and header; no live call was made.
- [x] Local `backend/.env` selects `azure_openai`. As of 30 October, `SCHEMAPILOT_LLM_ENABLED=true` was enabled with user approval; the existing key, endpoint, and deployment were unchanged. The previously exposed key remains pending rotation.
- [x] User selected Microsoft Entra ID for team sign-in. Entra-specific app-registration and role/group setup is in `docs/authentication.md`.
- [x] PostgreSQL integration suite: **20 passed, 155 deselected** using three temporary tmpfs containers with explicit app/demo/sandbox URL overrides. Containers were removed after the run; persistent Compose databases were not used.
- [x] Frontend tests: **10 passed** across 2 test files; TypeScript check and production build passed.
- [x] OIDC login/session routes, CSRF checks, engineer/approver role gates, private-owner isolation, shared-team visibility checks, and owner self-approval protection have mocked/unit coverage.
- [x] Added Alembic revision `20261029_0002` for workflow owner and visibility metadata.
- [x] Backed up the local app database to the Windows temp folder and applied revision `20261029_0002` to the app database only. Read-only verification confirms Alembic is at `20261029_0002` and both new workflow columns exist. Demo, sandbox, and target databases were not involved.
- [x] Verified a fresh PostgreSQL database upgrades through both Alembic revisions to `20261029_0002` and contains `owner_identity` and `visibility`; the temporary database used tmpfs and was removed.
- [x] Post-migration live API smoke check: health `ok`; workflow history HTTP 200; `/auth/me` reports authentication disabled as configured.
- [x] Authentication stays off by default. Target execution and migrations-on-startup remain disabled.
- [x] Full `npm audit`: **0 vulnerabilities** across 135 reported dependencies. No forced upgrade was run.
- [x] Temporary diagnostic `print()` statements are absent from `tests/test_sandbox_integration.py`.
- [x] Health response explicitly labels database status `not_checked`; process health does not claim PostgreSQL connectivity.

### Still open

- [ ] Configure Microsoft Entra: provide tenant/client/team group IDs, register the callback, assign test users, define Admin/Engineer/Approver/Viewer app roles, and set a random session secret. Keep the client secret private in `backend/.env`; authentication stays disabled until this is complete.
- [ ] Verify role/group claims and shared/private isolation with two real test accounts. Current OIDC tests mock the provider.
- [ ] Rotate the previously exposed Azure API key with an Azure account owner. A live Azure call succeeded on 30 October with the existing key, which remains unchanged; rotation is still recommended and no replacement key was entered.
- [ ] Identify which exact user action previously produced HTTP 500 and capture its request plus Uvicorn traceback if it recurs. This pass confirmed old app workflow schema drift and fixed it; the historical HTTP 500 still has no saved request/traceback for attribution.
- [ ] Complete a full UI journey after OIDC setup: sign in as Engineer, propose/validate/save private; save shared as team member; inspect history as Viewer; approve as a different Approver; verify forbidden access with a non-member.
- [ ] Human approval must be recorded by a separate signed-in Approver account after the Engineer creates the workflow. I will not impersonate the user or manufacture a human approval.
- [x] Confirmed target execution and migrations-on-startup remain disabled; no target apply route exists.

**Runtime history:** On the previous session, Docker, Uvicorn and Vite were started; API health, sources, schema inspection and deterministic plan requests returned successful responses. The old HTTP 500 did not recur. A full test invocation in this session picked up the development `.env`: 165 tests passed and 8 skipped, but the app DB integration failed because the workflow table was still at the old schema. A read-only check confirmed revision `20261015_0001` and the missing new columns. The test did not insert its workflow row. Afterward, I made an 8 KB SQL backup, applied only the app database Alembic upgrade, and verified revision `20261029_0002` plus both new columns in a read-only transaction. No database reset was performed. Future destructive DB integrations must use disposable databases and explicit URL overrides.

**LLM status (historical note superseded by 30 October refresh):** A live Azure authentication probe and one AI-assisted plan request subsequently succeeded with the existing key. The key was not rotated and remains sensitive; never put it in chat or logs.
## Live migration workflow verification — 29 October 2026

- [x] **Review:** `Add a nullable text column called phone_number to users.` returned `proposed`, one `add_column`, zero validation errors; risk assessment was eligible with no blocking findings. AI assistance was off.
- [x] **Generate:** Artifact `sp0cbdc27a64e4` was generated and remained unapplied.
- [x] **Validate:** Sandbox result `passed`; the column check passed. Seven checks passed and two remained explicitly `not_run` (`risk_row_checks` and `target_database`). No checks failed.
- [x] **Rollback:** Downgrade executed. Status `partial_restoration` is expected for a test column because rollback cannot restore values written into that new column. The sandbox schema matched the packaged baseline; a read-only check confirmed `phone_number` was absent afterward.
- [x] **Safety report:** `eligible_for_review=true`, no blocking reasons or missing evidence, `approved=false`, `applied=false`.
- [x] **Record/history:** Workflow `e14db393-7f5e-4c53-bdf1-7f42962713eb` saved as `shared` in the local app DB, status `report_ready`; history/detail/audit readback succeeded and included `workflow_persisted`.
- [x] **Isolation:** Demo source was inspected read-only; migration ran only against `schemapilot_sandbox`; one workflow record was written to `schemapilot` app DB. Target execution remained disabled.
- [ ] Browser pixels were not manually inspected in this pass. The same API routes used by the frontend were exercised through the Vite proxy. Real OIDC sign-in, multi-account permissions, and human approval remain unverified until an identity provider is configured.

## Runtime follow-up — 28 October 2026

- [x] Restore the local API and verify `GET /api/v1/sources` returns HTTP 200.
- [x] Verify the Sources screen recovers and displays the Bookstore demo as available.
- [x] Restore demo PostgreSQL and verify `GET /api/v1/sources/bookstore-demo/schema` returns HTTP 200.
- [ ] If an HTTP 500 appears again, capture the failed request and Uvicorn traceback before changing application code. The earlier `http_500` report has no saved traceback and cannot be attributed to a FastAPI exception.

**Finding:** At the start of this session, nothing was listening on `127.0.0.1:8000`; the browser showed `Failed to fetch`. Starting Uvicorn restored the API, and the Sources route returned 200 without a route exception. This resolves the current Sources failure as a stopped backend service. The earlier HTTP 500 itself remains unverified; a development proxy can surface an unavailable upstream as a 500, but there is no captured response proving that was the earlier case.

**Source unavailable follow-up:** Schema inspection initially returned `503 source_unavailable`. The configured demo database is on port 5434, which was refusing connections; Docker Desktop was stopped and no Compose containers were running. Started Docker Desktop and the existing Compose services with `up -d` (no volumes were reset), then rechecked schema inspection and received HTTP 200. The immediate source-unavailable issue was the stopped demo PostgreSQL container, not a backend route exception.

**LLM screenshot follow-up (historical):** The request shown was `drop the display_name column from uers`; the actual schema table is `users`. The provider response did not match the app's validated interpretation contract, so the configured deterministic fallback ran and rejected the misspelled table. A later strict-output request received HTTP 400. The provider now retries in JSON mode only when a 400 response identifies the response format/schema as the rejected parameter; server-side Pydantic validation still applies. Validation messages summarize missing or invalid field categories without exposing provider output. The prompt now lists the exact JSON keys and operation fields required. Unknown-table errors suggest close names without correcting them automatically. The migration example now includes the actual `users` table and explicit `text` data type. Mocked regressions passed at that checkpoint. Live provider behavior was subsequently verified on 30 October by one successful AI-assisted plan request; broader live failure handling remains unverified.

## Done through Phase 12

- [x] Phases 1–11 — foundation through optional LLM assist
- [x] Phase 12 — security/acceptance validation; target execution kept disabled

## Phase 12 deliverables

- [x] Inspected auth, approval, target isolation, LLM boundary, and existing tests
- [x] Approval fail-closed when `authentication_available=false` (no invented approver)
- [x] Target-execution preflight helper that always refuses in Phase 12 (no apply route)
- [x] Acceptance tests in `tests/test_acceptance_phase12.py`
- [x] Health reports `authentication_available` and `phase=12`
- [x] Final report: `docs/acceptance.md`
- [x] Probed Node/Docker availability; both unavailable in this environment

## Explicitly not done at the Phase 12 checkpoint (historical)

- [ ] Real authentication provider (login/session/OIDC)
- [ ] Target execution / apply endpoint
- [ ] Live PostgreSQL integration (demo + sandbox + app-db)
- [ ] Frontend `npm test` / `npm run build` (Node/npm missing)
- [ ] Live LLM provider verification

## Earlier local run (Phase 12, historical)

### Backend

```powershell
cd backend
.\.venv\Scripts\python.exe -m ruff check app tests alembic
.\.venv\Scripts\python.exe -m pytest -rs
```

**Ruff clean. Pytest: 144 passed, 20 skipped, 1 warning.**

Skipped: 19 live PostgreSQL + 1 live LLM (disabled by default). These are not passes.

### Frontend

Node/npm not available. Frontend tests and production build **not run**.

### Live databases / LLM

Not configured. Do not treat mocked SQLite/unit results as live PostgreSQL evidence.
