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

`generated` does not mean `applied`. `eligible_for_review` does not mean `approved`. `approved`/`recorded` does not mean `applied`. `not_verified` is never rewritten as success because PostgreSQL is unavailable. `fully_reversible` is only true for `exact_restoration`.

## Alembic

Revision `20261015_0001` creates the metadata tables. It runs only through the existing guarded Alembic path:

- `SCHEMAPILOT_ALLOW_APP_MIGRATIONS=true`
- `SCHEMAPILOT_APP_DATABASE_URL` points at the application database
- the URL is not the sandbox, demo, or target

API startup does not create tables or run Alembic.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/v1/sources/bookstore-demo/artifacts/{migration_id}/workflows` | Build the Phase 8 safety report and persist it |
| GET | `/api/v1/workflows` | List persisted workflows |
| GET | `/api/v1/workflows/{workflow_id}` | Workflow detail, report, approvals, audit |
| POST | `/api/v1/workflows/{workflow_id}/approvals` | Record an approval binding |
| GET | `/api/v1/workflows/{workflow_id}/audit` | Audit events only |

Request bodies:

- Persist: `{ "request": string, "confirm": true, "use_llm"?: boolean }`
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
- the target identity names the source, sandbox, or application database
- the supplied artifact or report checksum does not match the workflow

Authentication is not implemented as a login provider. Approvals therefore fail closed with `authentication_unavailable` until a real principal can be verified. Target execution stays disabled. See `docs/acceptance.md`.
