# Bookstore demo database

Phase 2 adds a disposable PostgreSQL database for the bookstore source schema. The API does not connect to it on startup, and demo commands refuse every database except this one.

## Database roles

| Role | Compose service | Host port | Database name | Environment variable |
| --- | --- | --- | --- | --- |
| Application metadata | `app-db` | 5432 | `schemapilot` | `SCHEMAPILOT_APP_DATABASE_URL` |
| Migration sandbox | `sandbox-db` | 5433 | `schemapilot_sandbox` | `SCHEMAPILOT_SANDBOX_DATABASE_URL` |
| Bookstore demo source | `demo-db` | 5434 | `schemapilot_bookstore` | `SCHEMAPILOT_DEMO_DATABASE_URL` |
| Future target | none in Phase 2 | none | unset | `SCHEMAPILOT_TARGET_DATABASE_URL` |

Each service has its own user, password placeholder, and volume. Alembic still uses only the application database, and only when `SCHEMAPILOT_ALLOW_APP_MIGRATIONS=true`. Sandbox upgrades use database `schemapilot_sandbox` with user `schemapilot_sandbox`, and only when `SCHEMAPILOT_ALLOW_SANDBOX_EXECUTION=true`. See `docs/sandbox.md`.

## Schema

The demo schema is `bookstore`, with:

- `users` — unique email, non-blank name, display-name index
- `products` — unique SKU, non-negative price and stock, active index
- `orders` — foreign key to `users`, status check, user and status indexes
- `order_items` — foreign keys to `orders` and `products`, unique product per order, positive quantity

`bookstore.users` carries a schema comment that contains the text `DROP TABLE bookstore.orders`. That comment is untrusted metadata. Verification reads it with a parameterized catalog query and does not execute it. The orders table remains in place.

Seed data uses fixed ids: 3 users, 4 products (one with stock 0), 2 orders, and 3 order items. One user has no orders. Verification also tries a duplicate email, a zero quantity, and an order for a missing user, then rolls those probes back.

## Safety rules

Demo commands run only when all of these are true:

- `SCHEMAPILOT_DEMO_DATABASE_URL` is set
- `SCHEMAPILOT_DEMO_ENVIRONMENT=disposable`
- the URL is different from the application, sandbox, and target URLs
- the database name is `schemapilot_bookstore`
- the connected database reports that same name

`reset` is destructive. It drops schema `bookstore` and requires both `SCHEMAPILOT_ALLOW_DEMO_RESET=true` and the CLI flag `--confirm-demo-reset`. `init` does not drop existing tables. `seed` does not delete existing rows.

Schema inspection does not call `init` or `reset`. It uses a separate read-only engine, documented in `docs/schema-inspection.md`.

## Windows PowerShell

Start the databases after installing Docker Desktop:

```powershell
cd C:\Users\suryabhansingh\Downloads\SchemaPilot
Copy-Item backend\.env.example .env
docker compose --env-file .env -f docker\compose.yaml up -d
```

Copy the same example into `backend\.env` if that file does not exist yet. The passwords there are local placeholders.

Initialize, seed, and verify:

```powershell
cd C:\Users\suryabhansingh\Downloads\SchemaPilot\backend
.\.venv\Scripts\python.exe -m app.demo init
.\.venv\Scripts\python.exe -m app.demo seed
.\.venv\Scripts\python.exe -m app.demo verify
```

Rebuild the disposable demo from scratch:

```powershell
$env:SCHEMAPILOT_ALLOW_DEMO_RESET = "true"
.\.venv\Scripts\python.exe -m app.demo reset --confirm-demo-reset
```

Leave `SCHEMAPILOT_ALLOW_DEMO_RESET=false` in the saved `.env`. The shell variable applies only to that PowerShell session and overrides the file for the reset command.

Integration tests also reset this database. They skip when the demo URL is not selected or PostgreSQL is not reachable. Do not point `SCHEMAPILOT_DEMO_DATABASE_URL` at the application database, the sandbox, or a target database.
