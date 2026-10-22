# SchemaPilot architecture

## Baseline

Phase 1 starts from an empty application. Before this foundation, the repository contained written specifications in `schemapilot_agent_instructions/` and no frontend, backend, tests, Docker setup, bookstore demo, or migration history.

There is no previous demo schema to preserve and no Alembic revision history to continue. `backend/alembic/versions/` is intentionally empty.

## What runs now

```text
Browser (Vite, http://localhost:5173)
        |
        |  GET /api/v1/health
        |  GET /api/v1/sources
        |  GET /api/v1/sources/bookstore-demo/schema   (read-only, on request)
        v
FastAPI (http://127.0.0.1:8000)
        |
        |  does not connect on startup
        v
Optional local PostgreSQL, only when you start Docker Compose
        app-db      127.0.0.1:5432   database schemapilot          application metadata
        sandbox-db  127.0.0.1:5433   database schemapilot_sandbox  disposable sandbox
        demo-db     127.0.0.1:5434   database schemapilot_bookstore bookstore source
```

The three PostgreSQL services use different users, passwords, database names, ports, and volumes. The API does not open any of them when it starts, and it does not run migrations or demo initialization. Alembic can run only against `SCHEMAPILOT_APP_DATABASE_URL`, and only after `SCHEMAPILOT_ALLOW_APP_MIGRATIONS=true`. It refuses a missing URL and refuses a URL that matches the sandbox, the demo database, or a configured target.

Bookstore setup is a separate command, documented in `docs/demo-database.md`. It runs only when `SCHEMAPILOT_DEMO_ENVIRONMENT=disposable` and the database name is `schemapilot_bookstore`.

Schema inspection is also separate. `GET /api/v1/sources/bookstore-demo/schema` opens a short-lived read-only session on that same demo URL. It does not use the demo initialization engine. See `docs/schema-inspection.md`.

Target execution is off unless `SCHEMAPILOT_TARGET_EXECUTION_ENABLED=true`. This build has no route that applies SQL to a target database, so turning the flag on does not execute anything.

## Phase 2

The bookstore demo is the first source schema. There is still no Alembic revision history under `backend/alembic/versions/`. Schema comments are stored as metadata and are not treated as instructions.

## Phase 3

The API can list the bookstore source and return a fingerprinted snapshot of schema `bookstore`: tables, columns, keys, checks, indexes, and foreign-key dependencies. Comments and check expressions are metadata. Health still does not connect to PostgreSQL.

## Phase 4

`POST /api/v1/sources/bookstore-demo/plans` asks the deterministic planner for a structured proposal. The route loads the snapshot through schema inspection. The planner does not connect, does not emit SQL, and does not read schema comments. See `docs/planner.md`.

## Phase 5

`POST /api/v1/sources/bookstore-demo/risk` inspects the source, plans with the existing planner, and scores that proposal. Risk uses operations and snapshot metadata: foreign keys, indexes, constraints, and nullability. It does not re-read the request, does not read schema comments, and does not execute SQL. Policy-blocked and unverified data-dependent plans are ineligible for artifact generation. See `docs/risk-rules.md`.

## Phase 6

`POST /api/v1/sources/bookstore-demo/artifacts` generates a SQL preview and an Alembic module from an eligible plan and its matching risk assessment. Files are written under `backend/artifacts/generated/` and are marked generated, not applied. The Alembic revision history in `backend/alembic/versions/` is left unchanged. See `docs/artifacts.md`.

## Phase 7

`POST /api/v1/sources/bookstore-demo/artifacts/{migration_id}/sandbox` loads one generated artifact, checks its checksum and eligibility, and applies that SQL on `schemapilot_sandbox` only. The sandbox baseline is rebuilt from the packaged bookstore schema and seed after the connection proves it is the sandbox database and the sandbox user. Source inspection stays read-only. The Alembic revision history is not changed. See `docs/sandbox.md`.

## Phase 8

`POST /api/v1/sources/bookstore-demo/artifacts/{migration_id}/rollback` downgrades that artifact only after the sandbox upgrade passes. The safety report is `POST /api/v1/sources/bookstore-demo/artifacts/{migration_id}/report`. `eligible_for_review`, `approved`, `applied`, and `fully_reversible` are separate fields. See `docs/rollback.md`.

## Phase 9

Workflow evidence is persisted in the application database `schemapilot` through guarded Alembic revision `20261015_0001`. Artifacts remain under `backend/artifacts/generated/` and are referenced by id and checksum. Approval records bind artifact checksum, report checksum, and target identity, but authentication is unavailable and target execution stays disabled. See `docs/workflow.md`.

## Phase 10

The Vite/React console calls the Phase 1–9 API for sources, planning, risk, artifacts, sandbox, rollback, safety reports, workflow history, and audit. Approval remains blocked in the UI while authentication is unavailable. Target execution is not offered. See `docs/frontend.md`.

## Phase 11

Optional server-side LLM assist interprets natural-language intent into strict structured drafts. Drafts are grounded in the inspected schema fingerprint, validated, and then processed by the same deterministic planner, risk engine, artifact, sandbox, rollback, report, and workflow path. Credentials stay server-side. See `docs/llm.md`.

## Phase 12

Acceptance and security validation. Approvals fail closed while authentication is unavailable. A target-execution preflight helper documents mandatory gates and always refuses; there is no apply route. Live PostgreSQL, frontend npm, and live LLM verification depend on local tooling and were not available in the Phase 12 environment. See `docs/acceptance.md`.

## Not in this phase

Target execution and a real authentication provider are not implemented.
