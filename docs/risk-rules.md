# Risk rules

Phase 5 scores a structured proposal against the inspected snapshot. `assess_risk` reads operations, plan status, the schema fingerprint, and snapshot metadata. It does not read the natural-language request, schema comments, or live rows, and it does not execute SQL.

`POST /api/v1/sources/bookstore-demo/risk` loads the snapshot through the existing inspector, asks the existing planner for a proposal, and then scores that proposal. The route does not generate a migration artifact.

## Finding shape

Each finding has a stable `rule_id`, `severity` (`low`, `medium`, `high`), and `disposition`:

| Disposition | Meaning |
| --- | --- |
| `info` | Static result with no data-loss concern |
| `warning` | Review before a later artifact |
| `high_risk` | Allowed to remain a proposal, but not safe to treat as verified |
| `policy_blocked` | The operation or plan cannot proceed |

`affected_objects` uses snapshot ids such as `bookstore.orders` and `bookstore.orders.orders_user_fk`. `evidence` is prefixed `static:` or `not_run:`. `data_check` is `not_required` or `not_run`. A data-dependent check is never reported as passed.

## Eligibility

`artifact_eligible` means Phase 6 may generate a review artifact. Generation still refuses `not_run` checks and does not treat a low static score as a passed live check. A later sandbox run does not mark those unresolved checks as passed. See `docs/artifacts.md` and `docs/sandbox.md`.

| `eligibility_reason` | When |
| --- | --- |
| `plan_not_proposed` | Status is `needs_clarification` or `rejected` |
| `policy_blocked` | Any finding is `policy_blocked` |
| `data_check_not_run` | A required row check was not executed |
| `no_operations` | The plan is proposed and empty |
| `eligible` | Proposed, unblocked, and no pending row check |

## Rules

| Rule | Operation | Evidence | Disposition | Data check |
| --- | --- | --- | --- | --- |
| SP-R001 | Destructive table drop or truncate | Snapshot table, plus dependent ids | `policy_blocked`, irreversible | `not_required`. Row counts are not read |
| SP-R002 | Destructive column drop | Snapshot column and dependents | `policy_blocked`, irreversible | `not_required` |
| SP-R003 | Rename table | Dependent foreign keys, indexes, and constraints | `high_risk` when dependents exist, otherwise `warning` | `not_required`. Clients outside the snapshot are not scanned |
| SP-R004 | Rename column | Same dependent lookup, limited to that column | `high_risk` or `warning` | `not_required` |
| SP-R005 | Add a nullable column with no default | Column is new and nullable | `info`, reversible | `not_required` |
| SP-R006 | Add a column with an explicit default | Default text is present and is not SQL | `warning` | `not_run`. Existing rows were not updated or checked |
| SP-R007 | Add a not-null column without a default | `nullable` is false and `default` is absent | `policy_blocked` | `not_run` |
| SP-R008 | Add an index | Index columns exist and no matching index exists | `info`, reversible | `not_required`. The build is not executed |
| SP-R009 | Add a unique constraint | Column exists | `high_risk` | `not_run`. Duplicates were not counted |
| SP-R010 | Add a not-null constraint | Snapshot `nullable` flag | `warning` when the column is already not null; `high_risk` when it is nullable | `not_required` only when metadata already says not null. Otherwise `not_run` |
| SP-R011 | Add a check constraint | Expression stored as text | `high_risk` | `not_run`. The expression is not evaluated |
| SP-R012 | Check expression or default contains SQL text | Pattern match for `DROP TABLE`, `DROP COLUMN`, `ALTER TABLE`, `TRUNCATE`, `GRANT`, `EXECUTE`, or `;` | `policy_blocked` | `not_required`. The text is not executed |
| SP-R013 | Missing or conflicting object | Table, column, index, or name is absent or already present | `policy_blocked` | `not_required` |
| SP-R014 | Column type outside the supported set | Type is not `text`, `integer`, `bigint`, `boolean`, or `timestamptz` | `policy_blocked` | `not_required` |
| SP-R015 | Plan is not `proposed` | Status and validation codes from the proposal | `policy_blocked` | `not_required` |
| SP-R016 | Nullable `deleted_at` `timestamptz` column | Same shape as a soft-delete proposal | `info` | `not_required`. It does not delete rows |
| SP-R017 | Rename or destructive operation touches dependents | Foreign keys, indexes, and constraints from the snapshot | `high_risk` | `not_required` |
| SP-R018 | Proposal fingerprint differs from the snapshot | The two fingerprint strings differ | `policy_blocked` | `not_required` |

Supported planner operations are covered: nullable columns, defaulted columns, indexes, renames, soft-delete proposals, unique, not-null, and check constraints, and destructive proposals.

Schema comments stay metadata. A comment or an existing check expression that contains `DROP TABLE bookstore.orders` does not create a finding unless that text is on the structured operation itself.
