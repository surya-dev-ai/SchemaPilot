# Migration downgrade and sandbox recovery

SchemaPilot reports two different outcomes:

1. **Migration downgrade** tests the migration artifact's downgrade SQL. This describes whether that migration can reverse its own change. Dropping a column and re-adding it cannot recover the former values, nullability, constraints, or dependent indexes, so that downgrade is reported as partial.
2. **Sandbox snapshot recovery** restores the disposable sandbox from a retained pre-migration PostgreSQL database clone, then compares the inspected schema and canonical contents of every table and sequence in the `bookstore` schema with the checkpoint.

The snapshot recovery route is `POST /api/v1/sources/{sandbox_source_id}/artifacts/{migration_id}/rollback` with `{"confirm": true, "snapshot_session_id": "<id from sandbox validation>"}`. The sandbox-validation route captures and test-restores the current sandbox state, then validates the artifact in place without dropping or reseeding the bookstore schema. It returns an artifact-bound `snapshot_session_id`, which the UI carries through validation, downgrade, snapshot recovery, safety report, and workflow recording. The validation session persists the actual `SandboxRun` and a privacy-reduced baseline summary; it binds both to the migration ID, checksum, and session ID. Credentials, URLs, and row values are not returned by the session-status API.

**Migration downgrade** is a separate `POST /api/v1/sources/{sandbox_source_id}/artifacts/{migration_id}/downgrade` action. It executes the generated downgrade against the validated sandbox, verifies the resulting schema, and persists a downgrade report associated with the same artifact and checkpoint session. A successful downgrade does not recover values discarded by the upgrade; status can therefore be `partial_restoration`.

**Snapshot recovery** is the `/rollback` action above. It restores from the retained pre-migration checkpoint, verifies it, and records snapshot results separately from downgrade evidence. Snapshot recovery does not execute downgrade SQL. If the migration was not separately downgraded, the downgrade status remains `not_verified` and `downgrade_executed` remains false; a snapshot restore cannot make a downgrade look successful.

For each snapshot recovery, the current sandbox state is replaced from a verified checkpoint using the rename-and-promote process. The previous database is removed only after the replacement passes verification. If replacement creation fails before the swap, the current sandbox stays untouched. If an error happens during the swap, the code attempts to restore the previous database name and retains recovery-named databases if compensation itself fails.

### Process-crash recovery

Recovery is reconciled when the sandbox recovery endpoint is called; backend startup alone does not mutate PostgreSQL. The Phase 2 integration test terminated a worker process with `os._exit(86)` immediately after the first committed rename (`schemapilot_sandbox` to its recovery-named previous database), before the staged replacement was promoted. A fresh API process discovered the active session and verified checkpoint, then resumed the restore. It verifies the staged or newly cloned replacement against the retained checkpoint, promotes it to the canonical sandbox name, verifies schema and row fingerprints, and only then removes the previous database. If the staged clone is missing, the retained checkpoint is used to rebuild it. Missing/corrupt checkpoint, unexpected database states, and failed verification return an incomplete/failure result and preserve recovery evidence. A completed session is not replayed through the API; repeated requests are rejected, while the underlying restore operation is idempotent when canonical state already matches.

This covers the interruption point after the first rename only. It does not prove recovery at every crash timing, host loss, storage corruption, or independent disaster recovery. Checkpoint databases remain same-cluster clones and are not production backups.

Checkpoint databases and session evidence are retained; they are not automatically purged. A session can be used once after successful restoration, and a second unresolved session blocks a new sandbox validation. Repeated completed runs consume additional storage. Local rollback evidence is written atomically under `backend/artifacts/rollback-evidence/` with a filename scoped to migration and snapshot session, and is bound to the artifact checksum. Its SHA-256 checksum detects accidental changes, but the local file is neither signed nor protected from an actor who can edit both the report and checksum. Removing old checkpoints requires an explicit operator retention procedure, which is not currently provided by the UI.

### Checkpoint evidence and lifecycle

The checkpoint-session file uses a versioned JSON envelope, a SHA-256 payload checksum, and atomic temporary-file replacement after flushing the file. Saving a session requires a syntactically valid checkpoint ID, verified backup status, retained checkpoint, and non-empty baseline fingerprints whose test-restore fingerprints match. On each transition, the checkpoint ID, capture time, backup status, and baseline fingerprints are immutable. Legal transitions are `ready -> running|completed|recovery_required`, `running -> running|completed|recovery_required`, and `recovery_required -> running`; `completed` is terminal. A session can become `completed` only when restoration status is `restore_verified` and both schema and data match are true. This checksum protects against accidental corruption; it is not a signature or protection against a local actor who can rewrite the file and checksum.

There is no automated checkpoint cleanup. Unresolved sessions block a new sandbox validation, and corrupt session evidence fails closed. Completed checkpoints and evidence are also kept indefinitely today. A retention period and quota are unresolved product/operations decisions; do not invent a duration or delete a checkpoint that may be the only recovery copy. Before designing cleanup, define operator ownership, active/recovery reference checks, auditable dry-run and deletion records, retry behavior, and a recoverable independent backup. No cleanup code is exposed by the application.

If the browser refreshes or a request is interrupted, `GET /api/v1/sources/bookstore-demo/sandbox-session` discovers the single unresolved session from the server-side evidence. The Migration screen then offers an explicit resume action using that original checkpoint. The status response exposes the migration id and safe recovery state, not the database contents or checkpoint database name. Corrupt evidence, a mismatched artifact, or multiple unresolved sessions fail closed and require operator review.

## Status interpretation

| Field | Meaning |
| --- | --- |
| `status` | Outcome of the artifact's migration downgrade (`exact_restoration`, `partial_restoration`, `failed`, or `not_verified`) |
| `snapshot_recovery.backup_status` | Whether a checkpoint was captured and a test restore matched the baseline (`verified`, `failed`, `unavailable`, or `not_created`) |
| `snapshot_recovery.restore_status` | Whether the sandbox itself was restored and verified (`restore_verified`, `restore_partially_verified`, `restore_failed`, `verification_incomplete`, `backup_unavailable`, or `not_attempted`) |
| `preexisting_sandbox_recovery` | The separately captured and restored sandbox state from before the packaged test baseline was loaded |
| `schema_match` / `data_match` | Independent comparisons against the captured pre-migration fingerprints |
| `checkpoint_retained` | Whether the checkpoint database is intended to remain available for a later retry |

The safety report and workflow history consume the persisted validation run, baseline evidence, downgrade report, and snapshot result after checking that the artifact checksum and session ID match. Missing, failed, or mismatched evidence fails closed. Review eligibility requires successful validation and upgrade evidence, actual downgrade evidence, and verified snapshot restoration of schema and data. This is review readiness, not approval or target application. Authentication and a separately authenticated approver are still required to record human approval.

## Phase 5 evidence propagation and operation separation

Checkpoint-session status now carries the validation result and a sanitized baseline summary so a browser refresh can recover the evidence from the backend rather than from React component state. Downgrade evidence is saved atomically in the same artifact-bound checkpoint session. Safety-report generation and workflow recording load that source of truth and retain the associated validation, baseline, downgrade, and snapshot fields. Incomplete validation is never promoted to successful evidence; an artifact/session mismatch is rejected.

The UI exposes distinct actions and labels for “Test migration downgrade” and “Restore sandbox from the saved checkpoint.” The first runs and reports downgrade SQL; the second restores a checkpoint and reports schema/data fingerprint comparisons. Neither action approves a workflow or applies a target migration. The integration test verifies these operations in sequence and checks that snapshot restoration does not overwrite or imply the downgrade result.

## Isolation and limits

Checkpoint creation, test restoration, and replacement operate only in the identity-checked sandbox PostgreSQL cluster. Source/demo inspection remains read-only. No target database URL is used, no target apply endpoint exists, and startup migrations remain disabled.

These checkpoints are PostgreSQL database clones on the **same cluster**. They can recover the sandbox from a migration test but are not independent, encrypted, off-host production backups and do not prove target-database recovery. A production recovery service needs separate backup storage, encryption, access controls, retention, monitoring, and regularly exercised restores.

`restore_verified` means equality within this implemented fingerprint scope, not equality of every PostgreSQL object. The schema comparison uses SchemaPilot's inspected `bookstore` objects: tables, columns and their types/nullability, constraints, indexes, and foreign-key relationships. The data fingerprint covers canonical row contents of every `bookstore` base table and each sequence's `pg_sequences.last_value` (including PostgreSQL's NULL value for an uncalled sequence). It does not verify views, triggers, functions/procedures, extensions, roles, grants/ownership, database/cluster settings, large objects, or external dependencies. Restore status must not be described as proof of those objects, database roles, cluster configuration, or external services.

### Read-only report and history paths

The safety-report endpoint inspects the selected source schema, creates a temporary migration artifact for comparison, and reads saved rollback evidence. It does not run rollback, restore a checkpoint, reset/reseed the sandbox, or write checkpoint state. If AI assistance is enabled, plan interpretation may make an LLM request. Workflow list and detail HTTP GET routes read persisted app-database rows; the detail route does not pass a current fingerprint. The lower-level `get_workflow` service can mark a workflow stale when explicitly given a current fingerprint, but the current GET route does not supply one. None of these report/history read paths deletes checkpoints or databases.
