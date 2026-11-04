# Bookstore demo database

Phase 2 adds a disposable PostgreSQL database for the bookstore source schema. The API does not connect to it on startup, and demo commands refuse every database except this one.

## Database roles

| Role | Compose service | Host port | Database name | Environment variable |
| --- | --- | --- | --- | --- |
| Application metadata | `app-db` | 127.0.0.1:5435 | `schemapilot` | `SCHEMAPILOT_APP_DATABASE_URL` |
| Migration sandbox | `sandbox-db` | 5433 (current Windows binding is not loopback-restricted) | `schemapilot_sandbox` | `SCHEMAPILOT_SANDBOX_DATABASE_URL` |
| Bookstore demo source | `demo-db` | 127.0.0.1:5434 | `schemapilot_bookstore` | `SCHEMAPILOT_DEMO_DATABASE_URL` |
| Future target | none in Phase 2 | none | unset | `SCHEMAPILOT_TARGET_DATABASE_URL` |

Each service has its own user, password placeholder, and volume. Alembic still uses only the application database, and only when `SCHEMAPILOT_ALLOW_APP_MIGRATIONS=true`. Sandbox upgrades use database `schemapilot_sandbox` with user `schemapilot_sandbox`, and only when `SCHEMAPILOT_ALLOW_SANDBOX_EXECUTION=true`. See `docs/sandbox.md`.

## Schema

The classroom showcase schema is `bookstore`, with nine related tables:

- `users` — unique email and non-blank display name
- `categories` — hierarchical categories with a self-referencing foreign key
- `products` — unique SKU, category foreign key, price and stock checks
- `addresses` — user foreign key and realistic optional address-line data
- `orders` — user and shipping-address foreign keys with status checks
- `order_items` — order/product foreign keys, uniqueness and quantity checks
- `payments` — order foreign key, reference uniqueness, payment-status and amount checks
- `reviews` — user/product foreign keys, uniqueness and rating checks
- `inventory_movements` — product/order-item foreign keys, reason and quantity checks

The model has 12 foreign-key relationships, including restrict, cascade, and set-null actions. This makes dependency findings visible when reviewing changes to users, products, orders, categories, and line items. `bookstore.users` retains an untrusted comment used to demonstrate safe metadata handling.

The synthetic seed contains 10 users, 5 categories, 8 products, 12 addresses, 12 orders, 17 order items, 9 payments, 8 reviews, and 18 inventory movements. It includes pending, paid, cancelled, failed and refunded states, one out-of-stock product, and a few intentionally optional text fields. All emails use the reserved `.test` domain and address data is fictional.

To enrich the already-initialized original demo without resetting it, run the one-time additive upgrade:

```powershell
cd C:\Users\suryabhansingh\Downloads\SchemaPilot\backend
.\.venv\Scripts\python.exe -m app.demo showcase-upgrade
.\.venv\Scripts\python.exe -m app.demo verify
```

The command verifies the exact original demo table set, row counts, relationships, configured database name, and connected database identity before applying the upgrade in one transaction. It refuses to run on an already-upgraded or otherwise changed schema. It adds records and constraints; it does not drop or reset existing demo rows. The app database, sandbox and target are not used.

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

Integration tests reset only their configured disposable demo database. They skip when the demo URL is not selected or PostgreSQL is not reachable. Do not point `SCHEMAPILOT_DEMO_DATABASE_URL` at the application database, the sandbox, or a target database.
