# Migration artifacts

Phase 6 writes a reviewable SQL preview and an Alembic module from a structured plan. It does not apply either file to a database.

`POST /api/v1/sources/bookstore-demo/artifacts` loads the snapshot, plans with the existing planner, scores that proposal with `assess_risk`, and then calls `generate_migration`. The generator does not read the natural-language request or schema comments.

## Provenance

Generation requires the current snapshot and the risk assessment for that same plan. The assessment must match a fresh `assess_risk` result for the snapshot and proposal: source id, schema name, fingerprint, plan status, and findings. A modified assessment is rejected with `provenance_mismatch`.

## What can be generated

The SQL preview and the Alembic module are rendered from the same validated operations.

| Operation | Upgrade | Downgrade | Reversibility |
| --- | --- | --- | --- |
| Nullable column, no default | `ADD COLUMN ... NULL` and `op.add_column` | `DROP COLUMN` and `op.drop_column` | `partially_reversible`. Recreating the column does not recover its former values |
| Nullable `deleted_at` `timestamptz` | Same as a nullable column | Same as a nullable column | `partially_reversible` |
| Non-unique index | `CREATE INDEX` and `op.create_index` | `DROP INDEX` and `op.drop_index` | `reversible`. Row values stay in place |
| Rename column | `RENAME COLUMN` and `op.alter_column` | Rename back to the previous name | `reversible`. Dependent snapshot ids are recorded |
| Rename table | `RENAME TO` and `op.rename_table` | Rename back to the previous name | `reversible`. Dependent snapshot ids are recorded |

Identifiers are accepted only when they match `^[a-z_][a-z0-9_]*$`, then quoted. Supported column types are `text`, `integer`, `bigint`, `boolean`, and `timestamptz`.

## What is rejected

| Result | Code |
| --- | --- |
| Any `policy_blocked` finding, including drops | `policy_blocked` |
| Any `data_check` of `not_run` | `data_check_not_run` |
| Plan status is not `proposed` | `plan_not_proposed` |
| Proposed plan with no operations | `no_operations` |
| Unique, not-null, or check constraint, including a low static score | `unsupported_operation` |
| Assessment does not match this plan and snapshot | `provenance_mismatch` |
| Output path is inside `backend/alembic/versions` | `unsafe_to_generate` |

A low static score is not treated as a passed live row check. `not_run` stays unresolved.

## Checksum

The checksum is `sha256:` plus the SHA-256 hex digest of the artifact JSON. That JSON is `sort_keys` with separators `(",", ":")` and excludes `checksum` and `location`. The same plan and snapshot always produce the same migration id, SQL, Alembic module, and checksum. Changing the SQL preview or the module invalidates the checksum. Changing only the storage path does not.

## Files

Modules are written to `backend/artifacts/generated/`, next to a JSON record of the same migration id. `status` is `generated` and `applied` is false. These files are not copied into `backend/alembic/versions/`. The Alembic environment still refuses to run unless application migrations are explicitly allowed against the application database.

Generated modules can be parsed as Python. Phase 7 may apply the checksum-verified SQL preview on the disposable sandbox. Phase 8 may downgrade that same sandbox change and record a safety report. See `docs/sandbox.md` and `docs/rollback.md`. The module is not copied into `backend/alembic/versions/` and Alembic is not called against the application database.
