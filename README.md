# SchemaPilot

SchemaPilot is a local foundation for natural-language PostgreSQL migration planning. Phase 2 adds a disposable bookstore demo database. The API does not plan or apply migrations, and it does not initialize a database on startup.

The specification files in `schemapilot_agent_instructions/` are unchanged. Alembic revision history is still empty.

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
| `app-db` | 5432 | `schemapilot` | Application metadata and Alembic |
| `sandbox-db` | 5433 | `schemapilot_sandbox` | Future disposable migration sandbox |
| `demo-db` | 5434 | `schemapilot_bookstore` | Bookstore demo source |

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

The planner is documented in `docs/planner.md`. It does not apply the change. Risk scoring for that proposal is documented in `docs/risk-rules.md` and is available at `POST /api/v1/sources/bookstore-demo/risk`. A reviewable SQL preview and Alembic module, when the plan is eligible, are documented in `docs/artifacts.md` and available at `POST /api/v1/sources/bookstore-demo/artifacts`. A sandbox upgrade of that artifact is documented in `docs/sandbox.md`. It runs only on `schemapilot_sandbox` and does not apply the migration to the source or a target. Rollback of that sandbox upgrade, and the safety report, are documented in `docs/rollback.md`. Persisted workflow history and the approval foundation are documented in `docs/workflow.md`. The Phase 10 console (sources, migration wizard, history, settings) is documented in `docs/frontend.md`. Optional Phase 11 LLM assist is documented in `docs/llm.md`. Phase 12 acceptance status is in `docs/acceptance.md`: authentication is unavailable, approvals fail closed, and target execution stays disabled. LLM API keys, when configured, remain server-side only.

Do not point `SCHEMAPILOT_APP_DATABASE_URL` or `SCHEMAPILOT_DEMO_DATABASE_URL` at a database you did not create for SchemaPilot.

Alembic does nothing unless both of these are true:

- `SCHEMAPILOT_APP_DATABASE_URL` is the application database, not the sandbox, the bookstore demo, or a target database.
- `SCHEMAPILOT_ALLOW_APP_MIGRATIONS=true`.

Phase 1 has no revision files, so there is nothing to upgrade. When a revision exists:

```powershell
cd C:\Users\suryabhansingh\Downloads\SchemaPilot\backend
.\.venv\Scripts\python.exe -m alembic upgrade head
```

Target execution stays disabled with `SCHEMAPILOT_TARGET_EXECUTION_ENABLED=false`. This build has no endpoint that applies SQL to a target database.

## Layout

```text
backend/     FastAPI, SQLAlchemy, Alembic, bookstore demo, pytest
frontend/    React, TypeScript, Vite
docker/      Compose file for app-db, sandbox-db, and demo-db
docs/        Architecture baseline and demo database workflow
```

See `docs/architecture.md` for the startup boundary.
