# SchemaPilot

SchemaPilot is a local PostgreSQL migration planning workspace. It supports natural-language planning, risk assessment, reviewable migration artifact generation, sandbox validation, rollback checks, safety reports, and workflow history. Optional Azure OpenAI assistance interprets requests; deterministic validation remains authoritative.

This development build validates and simulates changes in the isolated sandbox. Rollback checkpoints are PostgreSQL database clones on the same cluster for sandbox recovery only, not independent or production backups. Sandbox rollback evidence is separate from authenticated human approval and does not authorize production apply; target execution is disabled, with no target-database apply endpoint, and application migrations do not run on startup. Authentication is available only after an OIDC provider is configured; until then this is a single-user local development console.

## Prerequisites

- Python 3.11 or newer. This repository was checked with Python 3.13.
- Node.js 20 or newer, including npm, for the frontend build.
- Docker Desktop, only if you want the local PostgreSQL containers.

The API starts without PostgreSQL. It does not run migrations on startup.

## Backend (Windows PowerShell)

From the repository root:

```powershell
cd C:\Users\suryabhansingh\Downloads\SchemaPilot\backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check app tests alembic
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Health check:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
```

`backend/.env` is gitignored. The example file contains local placeholders only. Replace them before any shared or long-lived database.

## Frontend (Windows PowerShell)

In a second terminal:

```powershell
cd C:\Users\suryabhansingh\Downloads\SchemaPilot\frontend
npm install
npm run typecheck
npm run build
npm run dev
```

Open `http://localhost:5173`. Vite proxies `/api` to `http://127.0.0.1:8000`.

## Databases

Docker Compose defines three databases with different users, passwords, ports, and volumes:

| Service | Host port | Database | Used by |
| --- | --- | --- | --- |
| `app-db` | 5435 | `schemapilot` | Application metadata and Alembic (container port 5432) |
| `sandbox-db` | 5433 | `schemapilot_sandbox` | Future disposable migration sandbox |
| `demo-db` | 5434 | `schemapilot_bookstore` | Bookstore demo source |

Compose uses named volumes, so container recreation preserves database data. `app-db` and `demo-db` bind to `127.0.0.1`; Windows denied the explicit loopback bind for `sandbox-db` on port 5433, so it retains Docker's default host binding. Do not use this Compose setup on a network-accessible host until the sandbox port is also private.

```powershell
cd C:\Users\suryabhansingh\Downloads\SchemaPilot
Copy-Item backend\.env.example .env
Copy-Item backend\.env.example backend\.env
docker compose --env-file .env -f docker\compose.yaml up -d
```

Demo initialization is manual. From `backend`, after `demo-db` is healthy:

```powershell
.\.venv\Scripts\python.exe -m app.demo init
.\.venv\Scripts\python.exe -m app.demo seed
.\.venv\Scripts\python.exe -m app.demo verify
```

Reset drops schema `bookstore` on `schemapilot_bookstore` only:

```powershell
$env:SCHEMAPILOT_ALLOW_DEMO_RESET = "true"
.\.venv\Scripts\python.exe -m app.demo reset --confirm-demo-reset
```

The command refuses to run unless `SCHEMAPILOT_DEMO_ENVIRONMENT=disposable`. Details and the untrusted-comment rule are in `docs/demo-database.md`.

Read-only schema inspection, after the demo has been initialized:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/sources
Invoke-RestMethod http://127.0.0.1:8000/api/v1/sources/bookstore-demo/schema
```

Request and response examples are in `docs/schema-inspection.md`. Inspection does not reset the database and does not accept a connection URL from the client.

A natural-language plan, after the API is running and the demo source is configured:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/sources/bookstore-demo/plans `
  -Method POST `
  -ContentType "application/json" `
  -Body '{"request":"Add a nullable text column called nickname to users"}'
```

The planner is documented in `docs/planner.md`. It does not apply the change. Risk scoring for that proposal is documented in `docs/risk-rules.md` and is available at `POST /api/v1/sources/bookstore-demo/risk`. A reviewable SQL preview and Alembic module, when the plan is eligible, are documented in `docs/artifacts.md` and available at `POST /api/v1/sources/bookstore-demo/artifacts`. A sandbox upgrade of that artifact is documented in `docs/sandbox.md`. It runs only on `schemapilot_sandbox` and does not apply the migration to the source or a target. Rollback of that sandbox upgrade, and the safety report, are documented in `docs/rollback.md`. Persisted workflow history and the approval foundation are documented in `docs/workflow.md`. The Phase 10 console (sources, migration wizard, history, settings) is documented in `docs/frontend.md`. Optional Phase 11 LLM assist is documented in `docs/llm.md`. Phase 12 acceptance status is in `docs/acceptance.md`. Multi-user sign-in, OIDC configuration, shared/private workspace access, role mapping, and the required workflow metadata migration are documented in `docs/authentication.md`. Authentication remains off until a real OIDC provider is configured; target execution stays disabled. LLM API keys, when configured, remain server-side only.

Do not point `SCHEMAPILOT_APP_DATABASE_URL` or `SCHEMAPILOT_DEMO_DATABASE_URL` at a database you did not create for SchemaPilot.

Alembic does nothing unless both of these are true:

- `SCHEMAPILOT_APP_DATABASE_URL` is the application database, not the sandbox, the bookstore demo, or a target database.
- `SCHEMAPILOT_ALLOW_APP_MIGRATIONS=true`.

The current application database revisions are `20261015_0001` and `20261029_0002`. Back up the local app database and confirm `SCHEMAPILOT_APP_DATABASE_URL` points to the `schemapilot` application database before upgrading. Alembic is opt-in:

```powershell
Set-Location C:\Users\suryabhansingh\Downloads\SchemaPilot\backend
$env:SCHEMAPILOT_ALLOW_APP_MIGRATIONS = 'true'
.\.venv\Scripts\python.exe -m alembic upgrade head
Remove-Item Env:\SCHEMAPILOT_ALLOW_APP_MIGRATIONS
```

Do not run this against the sandbox, demo, or any target database. Review `docs/authentication.md` before enabling OIDC; the owner/visibility migration must be applied first.

Target execution stays disabled with `SCHEMAPILOT_TARGET_EXECUTION_ENABLED=false`. This build has no endpoint that applies SQL to a target database.

## Layout

```text
backend/     FastAPI, SQLAlchemy, Alembic, bookstore demo, pytest
frontend/    React, TypeScript, Vite
docker/      Compose file for app-db, sandbox-db, and demo-db
docs/        Architecture baseline and demo database workflow
```

See `docs/architecture.md` for the startup boundary.
