# Backend test environment

## Current verified test runner

The checked-in project environment at `backend/.venv` is not usable on this
machine: its `pyvenv.cfg` points to a missing Windows Store Python 3.13.14
installation, and its interpreter cannot be launched. It was left untouched.

The current regression test run used `backend/.test-runtime/python.exe` (Python
3.13.17). This runner reports the following installed versions:

| Package | Version |
| --- | --- |
| pytest | 9.1.1 |
| FastAPI | 0.143.0 |
| SQLAlchemy | 2.1.4 |
| Alembic | 1.20.0 |
| psycopg | 3.3.6 |
| Pydantic | 2.14.0 |
| Ruff | 0.17.0 |

`pip check` reported no broken requirements. The embedded runner does not include
the `venv` module and therefore is a test workaround, not a replacement for a
reproducible project virtual environment. Before release, install a supported
Python 3.13 distribution and recreate `.venv` from `pyproject.toml` and the
project's lock/dependency policy.

## Verified baseline on 1 November 2026

- Non-integration backend tests: 188 passed, 1 skipped, 29 deselected, 2
  warnings. The skipped test requires a live LLM request; database integrations
  were intentionally deselected in this run.
- PostgreSQL integration tests: 29 passed, 189 deselected, 2 warnings, against
  three disposable PostgreSQL 16 containers with tmpfs storage and random
  loopback ports. No persistent app, demo, sandbox, or target database was used.
- Ruff: clean (`python -m ruff check --no-cache app tests alembic`).

The full PostgreSQL baseline used explicitly isolated app, demo, and sandbox
test databases. The target database URL was empty; target execution and startup
migrations were disabled. Integration results do not validate deployment
security or production recovery.

## Commands

From `backend` in PowerShell:

```powershell
.\.test-runtime\python.exe --version
.\.test-runtime\python.exe -m ruff check --no-cache app tests alembic
.\.test-runtime\python.exe -m pytest -q -rs -m "not integration"
```

Run PostgreSQL-marked tests only after creating disposable test containers and
setting explicit test-only database URLs. Never point destructive integration
tests at persistent Compose databases or a target database.
