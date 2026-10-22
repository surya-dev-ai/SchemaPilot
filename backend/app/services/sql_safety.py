"""Policy checks for structured operations. Nothing in this module runs SQL."""

import re

from app.schemas.domain import SchemaSnapshot, TableSnapshot
from app.schemas.planning import PlanOperation

ALLOWED_COLUMN_TYPES = frozenset({"text", "integer", "bigint", "boolean", "timestamptz"})
_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")
_UNTRUSTED_SQL = re.compile(
    r"\bdrop\s+table\b|\bdrop\s+column\b|\balter\s+table\b|\btruncate\b|\bgrant\b|\bexecute\b|;",
    re.IGNORECASE,
)


def contains_untrusted_sql(value: str | None) -> bool:
    """True when text contains SQL that must not be treated as a constraint or default."""
    if value is None or not value.strip():
        return False
    return _UNTRUSTED_SQL.search(value) is not None


def _table(snapshot: SchemaSnapshot, name: str | None) -> TableSnapshot | None:
    if name is None:
        return None
    for table in snapshot.tables:
        if table.name == name:
            return table
    return None


def _has_column(table: TableSnapshot, name: str | None) -> bool:
    return name is not None and any(column.name == name for column in table.columns)


def target_problems(snapshot: SchemaSnapshot, operation: PlanOperation) -> list[str]:
    """Static object checks. An empty list means the named objects exist in the snapshot."""
    table = _table(snapshot, operation.table)
    if table is None:
        label = operation.table or "(none)"
        return [f"missing table {label}"]
    problems: list[str] = []
    if operation.kind == "add_column":
        _add_column_problems(table, operation, problems)
    elif operation.kind == "add_index":
        _index_problems(table, operation, problems)
    elif operation.kind == "rename_column":
        _rename_column_problems(table, operation, problems)
    elif operation.kind == "rename_table":
        _rename_table_problems(snapshot, operation, problems)
    elif operation.kind == "add_constraint":
        _constraint_problems(table, operation, problems)
    elif operation.kind == "destructive" and operation.column is not None:
        if not _has_column(table, operation.column):
            problems.append(f"missing column {table.name}.{operation.column}")
    return problems


def _add_column_problems(
    table: TableSnapshot,
    operation: PlanOperation,
    problems: list[str],
) -> None:
    if operation.column is None or _IDENTIFIER.fullmatch(operation.column) is None:
        problems.append("invalid column name")
    elif _has_column(table, operation.column):
        problems.append(f"column {table.name}.{operation.column} already exists")


def _index_problems(
    table: TableSnapshot,
    operation: PlanOperation,
    problems: list[str],
) -> None:
    columns = list(operation.index_columns)
    if not columns:
        problems.append("missing index columns")
        return
    for column in columns:
        if not _has_column(table, column):
            problems.append(f"missing column {table.name}.{column}")
    if any(list(index.columns) == columns for index in table.indexes):
        joined = ", ".join(columns)
        problems.append(f"index on {table.name}({joined}) already exists")


def _rename_column_problems(
    table: TableSnapshot,
    operation: PlanOperation,
    problems: list[str],
) -> None:
    if not _has_column(table, operation.column):
        problems.append(f"missing column {table.name}.{operation.column}")
    if operation.new_name is None or _IDENTIFIER.fullmatch(operation.new_name) is None:
        problems.append("invalid new column name")
    elif _has_column(table, operation.new_name):
        problems.append(f"column {table.name}.{operation.new_name} already exists")


def _rename_table_problems(
    snapshot: SchemaSnapshot,
    operation: PlanOperation,
    problems: list[str],
) -> None:
    if operation.new_name is None or _IDENTIFIER.fullmatch(operation.new_name) is None:
        problems.append("invalid new table name")
    elif any(table.name == operation.new_name for table in snapshot.tables):
        problems.append(f"table {operation.new_name} already exists")


def _constraint_problems(
    table: TableSnapshot,
    operation: PlanOperation,
    problems: list[str],
) -> None:
    if operation.constraint_kind is None:
        problems.append("missing constraint kind")
        return
    if operation.constraint_kind == "check":
        if operation.check_expression is None or not operation.check_expression.strip():
            problems.append("missing check expression")
        return
    if not _has_column(table, operation.column):
        problems.append(f"missing column {table.name}.{operation.column}")
