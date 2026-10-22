# Phase 12 acceptance report

Honest final validation of SchemaPilot Phases 1–11. Target execution was **not** enabled.

## Environment availability

| Capability | Status |
| --- | --- |
| Backend venv / pytest / Ruff | Available |
| Node.js / npm | Available (Node v24). Frontend `npm test` / `npm run build` **passed** in a later run |
| Docker / disposable PostgreSQL | CLI installed; **Desktop engine not running** → live integration still skipped |
| Live Azure OpenAI | Wired in `backend/.env`; manual smoke returned `llm_assisted` / `ok` |
| Authentication | **Low priority**; remains unavailable; approvals fail closed |

Commands used to probe tooling:

```powershell
Get-Command node,npm,docker -ErrorAction SilentlyContinue
Test-Path "$env:ProgramFiles\nodejs"
Test-Path "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
```

## Backend verification (this machine)

```powershell
cd backend
.\.venv\Scripts\python.exe -m ruff check app tests alembic
.\.venv\Scripts\python.exe -m pytest -rs
```

Latest Phase 12 result: **Ruff clean; 144 passed, 20 skipped, 1 warning**.

### What the passes cover (mocked / offline)

- Deterministic planner, risk, artifacts, SQL allowlist, checksum verification
- Sandbox/rollback unit logic without live PostgreSQL
- Workflow persistence on SQLite fixtures
- Approval fail-closed when `authentication_available=false`
- Approval bindings (artifact/report checksum, reserved targets, stale evidence) when a test-only principal is injected
- LLM structured-draft validation, prompt-injection refusal path, deterministic fallback
- Target-execution preflight module that always refuses in Phase 12
- OpenAPI contains no `/apply` route

### Skipped (not live evidence)

| Count | Suite | Reason |
| --- | --- | --- |
| 5 | bookstore demo integration | `SCHEMAPILOT_DEMO_DATABASE_URL` unset |
| 2 | schema inspection live | demo URL unset |
| 7 | sandbox upgrade live | sandbox URL / allow flag unset |
| 4 | rollback live | sandbox unset |
| 1 | workflow app-db live | `SCHEMAPILOT_APP_DATABASE_URL` unset |
| 1 | live LLM | disabled by default |

**Application-database persistence was not verified live.**  
**Sandbox upgrade and rollback were not verified live.**  
**Live LLM tests did not run.**

## Frontend verification

Frontend `npm test` and `npm run build` were **not run** (Node/npm unavailable). Typed client and Vitest sources exist under `frontend/`; they are not evidence of a successful production build.

## Authentication

- Implemented: server-side auth boundary (`app/services/auth.py`) and approval gate.
- Default: `authentication_available=false`.
- `record_approval` rejects with `authentication_unavailable` unless a real principal is provided **and** the setting is true.
- Request-body usernames / confirm checkboxes are not treated as authenticated identity.
- No login provider, session store, or password flow is implemented.
- Therefore **verified human approval is not available** in this environment.

## Target execution

| Question | Answer |
| --- | --- |
| Implemented apply endpoint? | **No** |
| Default enabled? | **No** (`SCHEMAPILOT_TARGET_EXECUTION_ENABLED=false`) |
| Frontend apply control? | **No** |
| Preflight helper? | Yes — `assert_target_execution_allowed` always fails closed in Phase 12 |
| Safe to enable now? | **No** |

### Remaining blockers before any target apply

1. Real authentication and authorization of approvers (tested end-to-end).
2. Live disposable PostgreSQL evidence for sandbox upgrade and rollback (`not_verified` must remain a blocker).
3. Live application-database workflow persistence verification.
4. Target URL isolation proven against distinct disposable target DB.
5. Duplicate/concurrent execution protection on a real apply path (no apply path exists yet).
6. Immediate preflight re-check immediately before execution.
7. Frontend must not invent approvers or apply buttons.

## LLM safety boundary (reviewed)

- `use_llm` defaults to `false`.
- Credentials are not returned by health/settings/workflow payloads.
- Draft schema forbids SQL, connection strings, and target fields (`extra=forbid`).
- Schema comments remain `comment_untrusted`.
- Model output passes through deterministic validation; success ≠ approval/apply.
- Provider failure uses deterministic fallback when configured.
- Live provider tests stay opt-in and skipped by default.

## Semantic fields remain distinct

`generated` ≠ `eligible_for_review` ≠ `approved` ≠ `applied` ≠ `fully_reversible`.  
A successful schema downgrade does not imply data recovery.

## Concrete next steps

1. Install Node.js 20+ and run `cd frontend && npm install && npm test && npm run build`.
2. Start disposable Compose databases; set distinct app/demo/sandbox URLs; run `pytest -m integration`.
3. Implement a real auth provider; keep approvals attributed to verified principals only.
4. Only after the above, design a gated target-apply path that reuses `assert_target_execution_allowed` and never auto-downgrades a target.
