# Workflow persistence and approval foundation

Phase 9 stores migration evidence in the application metadata database `schemapilot`. It does not apply migrations to a source or target, and it does not enable target execution.

## What is stored

Each persisted workflow references a generated artifact by `migration_id` and `artifact_checksum`. The Alembic/SQL files stay under `backend/artifacts/generated/`. The application tables hold:

- request text and interpreted intent
- plan and risk JSON
- sandbox and rollback JSON when present
- safety report JSON, report checksum, and evidence fingerprint
- `eligible_for_review`, `fully_reversible`, `rollback_status`, and `report_stale`
- approval bindings and audit events

`generated` does not mean `applied`. `eligible_for_review` does not mean `approved`. For an explicitly sandbox-only destructive column artifact, a passed sandbox run, recorded migration downgrade outcome, and verified pre-migration checkpoint restoration may make the evidence eligible for human review even though the risk finding remains policy-blocked for target use. The downgrade result and snapshot recovery result are shown separately. Checkpoints are PostgreSQL clones on the same cluster and prove sandbox recovery only, not independent or production backup capability. Sandbox rollback evidence does not record human approval or authorize production apply: approval requires a separate authenticated approver, and target execution remains disabled and unimplemented. `approved`/`recorded` does not mean `applied`. `not_verified` is never rewritten as success because PostgreSQL is unavailable. `fully_reversible` describes the migration downgrade only; it is not a statement about snapshot recovery.

The sandbox-validation route creates the pre-validation checkpoint session. It operates on the current `schemapilot_sandbox` schema without dropping or reseeding it. The recovery endpoint must receive that session ID and restores the sandbox from its original checkpoint; it does not run a migration downgrade. It stores a separate report under `backend/artifacts/rollback-evidence/` for that migration/session pair. Safety-report generation and workflow persistence must receive the same session ID; they only load that matching evidence and do not rerun recovery or mutate PostgreSQL. If no matching evidence exists, the report remains incomplete and ineligible for review.

## Alembic

Revision `20261015_0001` creates the metadata tables. Revision `20261029_0002` adds nullable `owner_identity` and `visibility` (default `shared`) to support private and shared team workflows. Apply both through the existing guarded Alembic path before enabling OIDC against an existing app database:

- `SCHEMAPILOT_ALLOW_APP_MIGRATIONS=true`
- `SCHEMAPILOT_APP_DATABASE_URL` points at the application database
- the URL is not the sandbox, demo, or target

API startup does not create tables or run Alembic.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/v1/sources/sandbox/artifacts/{migration_id}/workflows` | Build the Phase 8 safety report and persist it |
| GET | `/api/v1/workflows` | List persisted workflows |
| GET | `/api/v1/workflows/{workflow_id}` | Workflow detail, report, approvals, audit |
| POST | `/api/v1/workflows/{workflow_id}/approvals` | Record an approval binding |
| GET | `/api/v1/workflows/{workflow_id}/audit` | Audit events only |

Request bodies:

- Persist: `{ "request": string, "confirm": true, "use_llm"?: boolean, "visibility"?: "shared" | "private" }`
- Approval: `{ "target_identity": string, "confirm": true }`

`use_llm` defaults to false. When true, the same assisted planning path used for plans/reports is used so artifact checksum matching stays consistent. Interpretation path and provider status are stored in `plan_json` and in the `workflow_persisted` audit detail. API keys are never persisted.

Phase 7 and Phase 8 routes are unchanged aside from the optional `use_llm` flag on report requests. The console consumes these routes as documented in `docs/frontend.md` and `docs/llm.md`.

## Approval binding

An approval record stores `artifact_checksum`, `report_checksum`, and `target_identity`. It is rejected when:

- authentication is unavailable (Phase 12 default: `authentication_available=false`)
- no authenticated principal is supplied by the server (request-body usernames are ignored)
- the report is stale relative to the evidence fingerprint
- the workflow is not eligible for review
- blockers or missing evidence remain
- rollback is not `exact_restoration` or `partial_restoration`
- the sandbox checkpoint is missing, invalid, or not fully restored and verified
- the target identity names the source, sandbox, or application database
- the supplied artifact or report checksum does not match the workflow

OIDC sign-in and role checks are implemented but remain disabled by default until a provider is configured. In authenticated mode, Engineers/Admins can propose and save workflows; Approvers/Admins can record approvals; self-approval is rejected. Private workflows are visible only to their owner. Shared workflows are visible to members of the configured team group and Admins. Target execution stays disabled. See `docs/authentication.md` for provider setup and the role matrix.
