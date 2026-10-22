"""Static dependency lookup from an inspected snapshot.

This module reads tables, constraints, indexes, and foreign-key dependencies.
It does not open a connection and does not read schema comments.
"""

from app.schemas.domain import SchemaSnapshot, TableSnapshot


def _table(snapshot: SchemaSnapshot, name: str) -> TableSnapshot | None:
    for table in snapshot.tables:
        if table.name == name:
            return table
    return None


def _matches_table(qualified_or_name: str, schema_name: str, table: str) -> bool:
    return qualified_or_name in {table, f"{schema_name}.{table}"}


def related_object_ids(
    snapshot: SchemaSnapshot,
    table: str,
    column: str | None = None,
) -> tuple[str, ...]:
    """Return sorted ids of constraints, indexes, and foreign keys that use the object."""
    found: set[str] = set()
    schema_name = snapshot.schema_name
    for dependency in snapshot.dependencies:
        from_here = _matches_table(dependency.from_table, schema_name, table)
        to_here = _matches_table(dependency.to_table, schema_name, table)
        if not from_here and not to_here:
            continue
        if column is not None:
            from_column = from_here and column in dependency.from_columns
            to_column = to_here and column in dependency.to_columns
            if not from_column and not to_column:
                continue
        found.add(dependency.id)
    current = _table(snapshot, table)
    if current is None:
        return tuple(sorted(found))
    for constraint in current.constraints:
        if column is not None and column not in constraint.columns:
            continue
        found.add(constraint.id)
    for index in current.indexes:
        if column is not None and column not in index.columns:
            continue
        found.add(index.id)
    return tuple(sorted(found))
