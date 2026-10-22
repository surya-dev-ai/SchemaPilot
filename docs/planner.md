# Deterministic planner

Phase 4 turns a natural-language request into a structured proposal. It does not generate SQL or Alembic code, and the planner does not open a database connection.

The plan route loads the current snapshot from the existing schema inspector, then plans against that snapshot. Table and column names come from the snapshot. Schema comments are ignored, including the bookstore comment that contains `DROP TABLE bookstore.orders`.

## Endpoint

`POST /api/v1/sources/bookstore-demo/plans`

```json
{
  "request": "Add a nullable text column called nickname to users"
}
```

```json
{
  "source_id": "bookstore-demo",
  "schema_name": "bookstore",
  "schema_fingerprint": "sha256-of-the-inspected-snapshot",
  "request": "Add a nullable text column called nickname to users",
  "status": "proposed",
  "summary": "Add nullable text column nickname to users.",
  "assumptions": [],
  "clarification_questions": [],
  "operations": [
    {
      "id": "op-1",
      "kind": "add_column",
      "summary": "Add nullable text column nickname to users.",
      "table": "users",
      "column": "nickname",
      "data_type": "text",
      "nullable": true,
      "default": null,
      "new_name": null,
      "index_columns": [],
      "constraint_kind": null,
      "check_expression": null,
      "destructive": false
    }
  ],
  "validation_errors": [],
  "destructive": false,
  "requires_risk_assessment": false
}
```

`status` is `proposed`, `needs_clarification`, or `rejected`. A destructive request such as dropping a table is `proposed` with `requires_risk_assessment: true` and is not executed. Risk scoring is documented in `docs/risk-rules.md`. Artifact generation is a later step and is documented in `docs/artifacts.md`.

Supported intents are: add a nullable column, add a column with an explicit default, add an index, rename a column, rename a table, soft-delete as a nullable `deleted_at` timestamp, and add a unique, not-null, or check constraint when the request states that constraint. Other requests are rejected or asked to clarify the table, column, type, or behavior.

The same request and snapshot always produce the same deterministic proposal when `use_llm` is omitted or false.

Optional LLM assist (`use_llm: true`) is documented in `docs/llm.md`. The model may propose a structured draft; deterministic validation still owns the final proposal. Without credentials the API falls back to the deterministic planner when `SCHEMAPILOT_LLM_FALLBACK_TO_DETERMINISTIC=true`.

A blank request, a request longer than 2000 characters, or an extra field such as a connection URL is HTTP 422 and does not inspect the database. Unknown sources use the same error codes as schema inspection.
