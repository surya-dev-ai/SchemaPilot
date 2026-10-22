# Sandbox upgrades

Phase 7 applies one generated artifact to the disposable sandbox. It does not run that artifact on the bookstore source or on a target database. Rollback of that sandbox upgrade is documented in `docs/rollback.md`.

## Database

Compose service `sandbox-db` publishes port 5433 and creates database `schemapilot_sandbox` for user `schemapilot_sandbox`. The password placeholder is `change_me_local_sandbox`. The URL comes from `SCHEMAPILOT_SANDBOX_DATABASE_URL`. Execution also requires `SCHEMAPILOT_ALLOW_SANDBOX_EXECUTION=true`.

Before any drop, seed, or artifact statement, the connection must report that database name and user. The URL must not match the application, source, or target URL, and its user must be `schemapilot_sandbox`.

## Baseline

The sandbox is not assumed to be initialized. Each run drops schema `bookstore` and loads the packaged source files `schema.sql` and `seed.sql`. Those files are the bookstore source definition and its fixed test rows. The comment that contains `DROP TABLE bookstore.orders` stays a comment.

The catalog is then fingerprinted with the same assembler the source inspector uses. The artifact's source fingerprint must match. A mismatch stops the run before the artifact SQL executes.

## Artifact checks

The route is `POST /api/v1/sources/bookstore-demo/artifacts/{migration_id}/sandbox` with `{"confirm": true}`.

The runner loads `backend/artifacts/generated/{migration_id}.json` and the sibling module. It rejects a checksum mismatch, a module that differs from the JSON, a migration id that does not match, and SQL or Alembic upgrade code outside the generated allowlist. Policy-blocked statements and not-null changes are rejected. A `not_run` risk check is never recorded as passed.

The SQL that runs is the checksum-verified preview. The natural-language request is not parsed again. The module is not copied into `backend/alembic/versions/`.

## Result

A sandbox record includes the migration id, source id, source fingerprint, artifact checksum, sandbox database name, sandbox user, PostgreSQL version, start and end times, result, and a sanitized error. Checks say whether they passed, failed, or did not run. `upgrade_applied` is true only after the artifact statements commit. `restored` is true only when a failed upgrade rolls back and the packaged baseline is observed again. `cleaned_up` is true only when a cleanup run verifies that the bookstore tables are gone.

Statement timeout is applied with `set_config`. The sandbox engine uses a 5 second connect timeout. API startup does not open the sandbox.
