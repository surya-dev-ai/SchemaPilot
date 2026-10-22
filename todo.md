# SchemaPilot TODO

## Priority order (current)

1. **Major product functionality first** (LLM, frontend, live DBs)
2. **Authentication later / low priority** (approvals stay fail-closed until then)
3. **Target apply last** (still disabled; needs auth + live sandbox evidence)

## Done

- [x] Phases 1–12 core product (plan → risk → artifact → sandbox → rollback → report → workflow → console)
- [x] Azure OpenAI wired into `backend/.env` (`SCHEMAPILOT_LLM_*`)
- [x] Provider normalizes Azure-style aliases (`action`/`table_name`, null `index_columns`)
- [x] Live Azure smoke: `interpretation_path=llm_assisted`, `provider_status=ok`
- [x] Frontend `npm test` (10 passed) and `npm run build` succeeded
- [x] Circular import fix (`operation_kinds.py`)
- [x] Auth kept low-priority: `authentication_available=false`; no Authentik yet
- [x] Target execution remains disabled

## Pending (major)

- [ ] Start Docker Desktop daemon; `docker compose up` for app/demo/sandbox DBs
- [ ] Run live PostgreSQL integration tests (19 currently skipped)
- [ ] Live app-db Alembic + workflow persistence verification
- [ ] Live sandbox upgrade + rollback verification

## Pending (low priority)

- [ ] Real authentication (Authentik recommended later)
- [ ] Verified human approvals attributed to principals

## Pending (last)

- [ ] Gated target-apply endpoint (only after auth + live evidence)

## Latest verification

### Frontend (Node v24 / npm 11)

```powershell
cd frontend
npm test    # 10 passed
npm run build  # succeeded
```

### Backend

```powershell
cd backend
.\.venv\Scripts\python.exe -m ruff check app tests alembic  # clean
.\.venv\Scripts\python.exe -m pytest -q
```

Azure live smoke (not a pytest integration mark): assisted plan returned `llm_assisted` / `ok`.

### Docker

Docker CLI is installed, but the **Desktop engine was not running** (`dockerDesktopLinuxEngine` pipe missing). Live DB tests remain blocked until Desktop is started.

### Auth / target apply

Still intentionally deferred / disabled.
