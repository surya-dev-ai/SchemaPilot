# Sandbox upgrades

Phase 7 applies one generated artifact to the disposable sandbox. It does not run that artifact on the bookstore source or on a target database. Rollback of that sandbox upgrade is documented in `docs/rollback.md`.

## Database

Compose service `sandbox-db` publishes port 5433 and creates database `schemapilot_sandbox` for user `schemapilot_sandbox`. The password placeholder is `change_me_local_sandbox`. The URL comes from `SCHEMAPILOT_SANDBOX_DATABASE_URL`. Execution also requires `SCHEMAPILOT_ALLOW_SANDBOX_EXECUTION=true`.

Before any drop, seed, or artifact statement, the connection must report that database name and user. The URL must not match the application, source, or target URL, and its user must be `schemapilot_sandbox`.

An interrupted checkpoint session can be discovered with `GET /api/v1/sources/bookstore-demo/sandbox-session`. The Migration screen uses this status to offer a confirmed resume of sandbox rollback and recovery after a page refresh. Corrupt, mismatched, or multiple unresolved session evidence is rejected rather than guessed.

## Sandbox-only planning and baseline

The Migration workspace uses the distinct `sandbox` source ID. Planning, risk assessment, artifact generation, safety reports, and workflow evidence inspect `schemapilot_sandbox` with the dedicated sandbox engine. Schema inspection starts a read-only transaction and verifies both the current database and database user. The request body cannot provide a URL. The `bookstore-demo` source remains a separate read-only demo feature and is not queried by this workflow.

The schema fingerprint describes the current sandbox before migration. Validation captures and test-restores a verified checkpoint of that exact schema and data, then compares the live sandbox fingerprint with the artifact. A mismatch or failed checkpoint stops before migration execution. Normal browser validation never drops the `bookstore` schema and never loads packaged seed data. `prepare_sandbox_baseline()` and cleanup helpers are reserved for explicitly disposable test fixtures and maintenance, not this workflow.

## Artifact checks

The route is `POST /api/v1/sources/sandbox/artifacts/{migration_id}/sandbox` with `{"confirm": true}`.

The runner loads `backend/artifacts/generated/{migration_id}.json` and the sibling module. It rejects a checksum mismatch, a module that differs from the JSON, a migration id that does not match, and SQL or Alembic upgrade code outside the generated allowlist. A single generated demo column drop is allowed only in this identity-checked sandbox, using the exact no-`CASCADE` SQL form; table drops and other policy-blocked statements remain rejected. The artifact remains policy-blocked for target use. A `not_run` risk check is never recorded as passed.

The SQL that runs is the checksum-verified preview. The natural-language request is not parsed again. The module is not copied into `backend/alembic/versions/`. Generated operations are constrained by the SQL and Alembic allowlists, so validation does not run arbitrary LLM SQL or data-changing statements.

## Result

A sandbox record includes the migration id, source fingerprint, artifact checksum, sandbox identity, timestamps, result, and checks. Its pre-migration `snapshot_session_id` is stored server-side and bound to the artifact checksum. The session-discovery endpoint is `GET /api/v1/sources/sandbox/sandbox-session`; it returns safe recovery metadata only and is used after browser refresh. An interrupted session stays discoverable until the user explicitly resumes restoration.

The resume action restores the retained pre-migration sandbox checkpoint directly; it does not run a migration downgrade. Restoration is reported as successful only when the final schema and data fingerprints both match the checkpoint baseline. Failed or incomplete restoration remains visible and keeps the session in `recovery_required`, blocking another validation. Migration downgrade testing remains a separate capability and must not be conflated with snapshot restoration. Checkpoints are same-cluster PostgreSQL clones, not independent or production backups, and currently have no automatic cleanup policy.

This evidence is limited to sandbox recovery. It does not authorize or perform a production apply: human approval is a separate authenticated workflow, and target execution remains disabled.

Statement timeout is applied with `set_config`. The sandbox engine uses a 5 second connect timeout. API startup does not open the sandbox.
