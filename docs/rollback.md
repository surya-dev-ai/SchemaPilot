# Rollback and safety report

Phase 8 downgrades one artifact in `schemapilot_sandbox` after that same artifact has upgraded and validated there. It does not downgrade the bookstore source or a target, and it does not approve the migration.

## Rollback

`POST /api/v1/sources/bookstore-demo/artifacts/{migration_id}/rollback` with `{"confirm": true}` reuses the Phase 7 sandbox runner. That runner checks the checksum, migration id, Alembic module, allowlist, sandbox database name, sandbox user, and risk eligibility before the upgrade.

Before the upgrade, the packaged bookstore baseline is loaded and its fingerprint, tables, row counts, and emails are recorded. The sandbox runner then rebuilds that same baseline and applies the upgrade. Downgrade starts only when the upgrade result is `passed` and `upgrade_applied` is true. The saved artifact is loaded again, and its downgrade SQL must match the Alembic downgrade body. `DROP TABLE` is rejected.

The post-downgrade fingerprint and row evidence are compared with the recorded baseline.

| Status | Meaning |
| --- | --- |
| `exact_restoration` | Schema and recorded row evidence match the baseline, and the artifact does not drop stored column values |
| `partial_restoration` | Schema and recorded rows match, but a dropped column's former values were not recovered |
| `failed` | The downgrade command failed, or the schema or rows do not match the baseline |
| `not_verified` | PostgreSQL was unavailable, the upgrade did not pass, the baseline is missing, or the artifact failed its checks |

A finished downgrade command is not proof of complete data recovery. Recreating a dropped column does not restore its former values. For a new nullable column, the tester writes a sentinel value before the downgrade and then reports that the value is gone.

## Safety report

`POST /api/v1/sources/bookstore-demo/artifacts/{migration_id}/report` with a request and `{"confirm": true}` inspects the source, plans, and scores risk with the existing services. It loads the saved artifact and checks that a fresh plan for that request produces the same artifact id, checksum, and fingerprint.

The report includes the request, interpreted summary, operations, assumptions, source fingerprint, artifact id and checksum, risk findings, sandbox upgrade, rollback status, data-loss limitations, missing evidence, and blocking reasons.

`eligible_for_review` can be true for `exact_restoration` or `partial_restoration` when the upgrade passed and nothing is blocking. `approved` and `applied` stay false. `fully_reversible` is true only for `exact_restoration`.
