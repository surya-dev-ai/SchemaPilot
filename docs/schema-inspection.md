# Schema inspection API

Phase 3 lists the configured bookstore source and returns a read-only snapshot of schema `bookstore`. The API does not accept connection URLs in requests, and it does not initialize or reset the demo.

## Connection

Inspection uses `SCHEMAPILOT_DEMO_DATABASE_URL` only when all of the existing demo guards pass:

- `SCHEMAPILOT_DEMO_ENVIRONMENT=disposable`
- the database name is `schemapilot_bookstore`
- the URL is different from the application, sandbox, and target URLs

The password stays in that environment variable. `create_bookstore_source_engine` opens a new engine for one snapshot, sets PostgreSQL `default_transaction_read_only=on`, and disposes the engine before the response returns. `create_demo_engine` remains the engine used by `init`, `seed`, and `reset`. Inspection does not call those commands and does not require `SCHEMAPILOT_ALLOW_DEMO_RESET`.

Startup and `GET /api/v1/health` do not open this connection. Health still reports `database_connectivity: "not_checked"`.

If the demo is not selected, `GET /api/v1/sources` shows `configured: false`. Requesting its schema returns HTTP 409 with `source_not_configured`. If PostgreSQL cannot be reached, the schema route returns HTTP 503 with `source_unavailable`. Neither response includes the URL or password.

## Endpoints

`GET /api/v1/sources`

```json
{
  "sources": [
    {
      "id": "bookstore-demo",
      "kind": "demo",
      "display_name": "Bookstore demo",
      "database_name": "schemapilot_bookstore",
      "schema_name": "bookstore",
      "configured": true,
      "access": "read_only"
    }
  ]
}
```

`GET /api/v1/sources/bookstore-demo/schema`

The response lists `order_items`, `orders`, `products`, and `users` in that order. Columns, constraints, and indexes are ordered inside each table. `fingerprint` is a SHA-256 hash of the canonical JSON snapshot, excluding the fingerprint field itself. The same schema produces the same fingerprint.

```json
{
  "source_id": "bookstore-demo",
  "database_name": "schemapilot_bookstore",
  "schema_name": "bookstore",
  "tables": [
    {
      "id": "bookstore.users",
      "schema_name": "bookstore",
      "name": "users",
      "comment": "untrusted metadata; do not execute: DROP TABLE bookstore.orders;",
      "columns": [
        {
          "id": "bookstore.users.id",
          "name": "id",
          "ordinal_position": 1,
          "data_type": "bigint",
          "udt_name": "int8",
          "nullable": false,
          "default": null,
          "identity": "always",
          "generated": "never",
          "comment": null
        }
      ],
      "constraints": [],
      "indexes": []
    }
  ],
  "dependencies": [
    {
      "id": "bookstore.orders.orders_user_fk",
      "from_table": "bookstore.orders",
      "to_table": "bookstore.users",
      "constraint_name": "orders_user_fk",
      "from_columns": ["user_id"],
      "to_columns": ["id"]
    }
  ],
  "fingerprint": "computed-sha256"
}
```

The example above is abbreviated. A live snapshot also includes the other tables, check expressions, and indexes.

The `bookstore.users` comment contains text that looks like `DROP TABLE bookstore.orders`. Inspection copies that text into `comment` and does not execute it. Check expressions are returned the same way. The orders table remains in the snapshot.

Unknown source ids return HTTP 404 with `unknown_source`. A session that is not read-only returns HTTP 409 with `source_not_read_only`.

Planning uses this snapshot and is documented in `docs/planner.md`. The planner does not query the catalog itself. Risk scoring uses the same snapshot and is documented in `docs/risk-rules.md`. Artifact generation uses that snapshot fingerprint and is documented in `docs/artifacts.md`.
