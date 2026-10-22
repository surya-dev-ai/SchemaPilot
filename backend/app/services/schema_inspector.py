"""Read-only inspection of the bookstore schema.

Catalog comments, defaults, and check expressions are returned as text.
They are never executed.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import OperationalError

from app.core.config import DEMO_DATABASE_NAME, Settings
from app.db.session import create_bookstore_source_engine
from app.schemas.domain import (
    ColumnSnapshot,
    ConstraintKind,
    ConstraintSnapshot,
    DependencySnapshot,
    GeneratedKind,
    IdentityGeneration,
    IndexDirection,
    IndexSnapshot,
    ReferentialAction,
    SchemaSnapshot,
    TableSnapshot,
)
from app.services.source_manager import (
    BOOKSTORE_SCHEMA_NAME,
    BOOKSTORE_SOURCE_ID,
    SourceNotReadOnlyError,
    SourceUnavailableError,
    UnexpectedSourceDatabaseError,
    require_bookstore_source,
)

_CONSTRAINT_KINDS: dict[str, ConstraintKind] = {
    "c": "check",
    "f": "foreign_key",
    "p": "primary_key",
    "u": "unique",
}
_ACTIONS: dict[str, ReferentialAction] = {
    "a": "no_action",
    "c": "cascade",
    "d": "set_default",
    "n": "set_null",
    "r": "restrict",
}

_READ_ONLY_SQL = "SELECT current_setting('default_transaction_read_only') AS value"
_DATABASE_SQL = "SELECT current_database() AS current_database"
_TABLES_SQL = """
SELECT c.relname AS table_name,
       pg_catalog.obj_description(c.oid, 'pg_class') AS table_comment
FROM pg_catalog.pg_class AS c
JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
WHERE n.nspname = :schema
  AND c.relkind = 'r'
ORDER BY c.relname
"""
_COLUMNS_SQL = """
SELECT cols.table_name,
       cols.column_name,
       cols.ordinal_position,
       cols.data_type,
       cols.udt_name,
       cols.is_nullable,
       cols.column_default,
       cols.is_identity,
       cols.identity_generation,
       cols.is_generated,
       pg_catalog.col_description(cls.oid, cols.ordinal_position) AS column_comment
FROM information_schema.columns AS cols
JOIN pg_catalog.pg_namespace AS ns ON ns.nspname = cols.table_schema
JOIN pg_catalog.pg_class AS cls
  ON cls.relnamespace = ns.oid AND cls.relname = cols.table_name
WHERE cols.table_schema = :schema
  AND cls.relkind = 'r'
ORDER BY cols.table_name, cols.ordinal_position
"""
_CONSTRAINTS_SQL = """
SELECT src.relname AS table_name,
       con.conname AS constraint_name,
       con.contype AS constraint_type,
       pg_get_constraintdef(con.oid, true) AS definition,
       fn.nspname AS foreign_schema,
       ft.relname AS foreign_table,
       (
           SELECT array_agg(a.attname ORDER BY cols.ord)
           FROM unnest(con.conkey) WITH ORDINALITY AS cols(attnum, ord)
           JOIN pg_catalog.pg_attribute AS a
             ON a.attrelid = con.conrelid AND a.attnum = cols.attnum
       ) AS columns,
       (
           SELECT array_agg(a.attname ORDER BY cols.ord)
           FROM unnest(con.confkey) WITH ORDINALITY AS cols(attnum, ord)
           JOIN pg_catalog.pg_attribute AS a
             ON a.attrelid = con.confrelid AND a.attnum = cols.attnum
       ) AS referenced_columns,
       con.confupdtype AS update_action,
       con.confdeltype AS delete_action
FROM pg_catalog.pg_constraint AS con
JOIN pg_catalog.pg_class AS src ON src.oid = con.conrelid
JOIN pg_catalog.pg_namespace AS n ON n.oid = src.relnamespace
LEFT JOIN pg_catalog.pg_class AS ft ON ft.oid = con.confrelid
LEFT JOIN pg_catalog.pg_namespace AS fn ON fn.oid = ft.relnamespace
WHERE n.nspname = :schema
  AND con.contype IN ('c', 'f', 'p', 'u')
ORDER BY src.relname, con.conname
"""
_INDEXES_SQL = """
SELECT t.relname AS table_name,
       i.relname AS index_name,
       ix.indisunique AS is_unique,
       ix.indisprimary AS is_primary,
       a.attname AS column_name,
       array_position(ix.indkey, a.attnum) AS position,
       CASE
           WHEN (ix.indoption[array_position(ix.indkey, a.attnum) - 1] & 1) = 1 THEN 'desc'
           ELSE 'asc'
       END AS direction
FROM pg_catalog.pg_index AS ix
JOIN pg_catalog.pg_class AS t ON t.oid = ix.indrelid
JOIN pg_catalog.pg_class AS i ON i.oid = ix.indexrelid
JOIN pg_catalog.pg_namespace AS n ON n.oid = t.relnamespace
JOIN pg_catalog.pg_attribute AS a
  ON a.attrelid = t.oid AND a.attnum = ANY (ix.indkey)
WHERE n.nspname = :schema
  AND t.relkind = 'r'
  AND a.attnum > 0
ORDER BY t.relname, i.relname, position
"""

INSPECTION_QUERIES = (
    _READ_ONLY_SQL,
    _DATABASE_SQL,
    _TABLES_SQL,
    _COLUMNS_SQL,
    _CONSTRAINTS_SQL,
    _INDEXES_SQL,
)


@dataclass(frozen=True)
class Catalog:
    tables: tuple[Mapping[str, object], ...]
    columns: tuple[Mapping[str, object], ...]
    constraints: tuple[Mapping[str, object], ...]
    indexes: tuple[Mapping[str, object], ...]


def inspect_source(settings: Settings, source_id: str) -> SchemaSnapshot:
    """Inspect one configured source and dispose the read-only engine afterward."""

    require_bookstore_source(settings, source_id)
    engine = create_bookstore_source_engine(settings)
    try:
        with engine.connect() as connection:
            _assert_read_only(connection)
            _assert_bookstore_database(connection)
            catalog = load_catalog(connection)
            return assemble_snapshot(catalog)
    except OperationalError:
        raise SourceUnavailableError from None
    finally:
        engine.dispose()


def load_catalog(connection: Connection) -> Catalog:
    params = {"schema": BOOKSTORE_SCHEMA_NAME}
    return Catalog(
        tables=_rows(connection, _TABLES_SQL, params),
        columns=_rows(connection, _COLUMNS_SQL, params),
        constraints=_rows(connection, _CONSTRAINTS_SQL, params),
        indexes=_rows(connection, _INDEXES_SQL, params),
    )


def assemble_snapshot(catalog: Catalog) -> SchemaSnapshot:
    """Build a deterministic snapshot. Comments stay in metadata fields."""

    columns_by_table: dict[str, list[ColumnSnapshot]] = {}
    for row in catalog.columns:
        table_name = str(row["table_name"])
        columns_by_table.setdefault(table_name, []).append(_column(table_name, row))
    for columns in columns_by_table.values():
        columns.sort(key=lambda column: column.ordinal_position)

    constraints_by_table: dict[str, list[ConstraintSnapshot]] = {}
    dependencies: list[DependencySnapshot] = []
    for row in catalog.constraints:
        table_name = str(row["table_name"])
        constraint = _constraint(table_name, row)
        constraints_by_table.setdefault(table_name, []).append(constraint)
        if constraint.kind == "foreign_key" and constraint.referenced_table:
            dependencies.append(
                DependencySnapshot(
                    id=constraint.id,
                    from_table=f"{BOOKSTORE_SCHEMA_NAME}.{table_name}",
                    to_table=(
                        f"{constraint.referenced_schema or BOOKSTORE_SCHEMA_NAME}."
                        f"{constraint.referenced_table}"
                    ),
                    constraint_name=constraint.name,
                    from_columns=list(constraint.columns),
                    to_columns=list(constraint.referenced_columns),
                )
            )
    for constraints in constraints_by_table.values():
        constraints.sort(key=lambda constraint: (constraint.kind, constraint.name))
    dependencies.sort(key=lambda dependency: dependency.id)

    indexes_by_table = _group_indexes(catalog.indexes)
    tables = [
        TableSnapshot(
            id=f"{BOOKSTORE_SCHEMA_NAME}.{row['table_name']}",
            schema_name=BOOKSTORE_SCHEMA_NAME,
            name=str(row["table_name"]),
            comment=_optional_text(row.get("table_comment")),
            columns=columns_by_table.get(str(row["table_name"]), []),
            constraints=constraints_by_table.get(str(row["table_name"]), []),
            indexes=indexes_by_table.get(str(row["table_name"]), []),
        )
        for row in sorted(catalog.tables, key=lambda item: str(item["table_name"]))
    ]
    snapshot = SchemaSnapshot(
        source_id=BOOKSTORE_SOURCE_ID,
        database_name=DEMO_DATABASE_NAME,
        schema_name=BOOKSTORE_SCHEMA_NAME,
        tables=tables,
        dependencies=dependencies,
        fingerprint="",
    )
    return snapshot.model_copy(update={"fingerprint": schema_fingerprint(snapshot)})


def schema_fingerprint(snapshot: SchemaSnapshot) -> str:
    """Hash a canonical JSON form. Key order and the fingerprint field do not affect it."""

    payload = snapshot.model_dump(mode="json", exclude={"fingerprint"})
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _assert_read_only(connection: Connection) -> None:
    row = _one(connection, _READ_ONLY_SQL, None)
    if str(row["value"]).lower() != "on":
        raise SourceNotReadOnlyError


def _assert_bookstore_database(connection: Connection) -> None:
    row = _one(connection, _DATABASE_SQL, None)
    if row["current_database"] != DEMO_DATABASE_NAME:
        raise UnexpectedSourceDatabaseError


def _rows(
    connection: Connection,
    sql: str,
    params: dict[str, str],
) -> tuple[Mapping[str, object], ...]:
    result = _execute_select(connection, sql, params)
    return tuple(result.mappings().all())


def _one(connection: Connection, sql: str, params: dict[str, str] | None) -> Mapping[str, object]:
    result = _execute_select(connection, sql, params)
    return result.mappings().one()


def _execute_select(connection: Connection, sql: str, params: dict[str, str] | None):
    stripped = sql.lstrip()
    if not stripped.upper().startswith("SELECT"):
        raise RuntimeError("Refusing to run a non-SELECT inspection query.")
    if "DROP TABLE" in stripped.upper():
        raise RuntimeError("Refusing to run an inspection query that contains DROP TABLE.")
    if params is None:
        return connection.execute(text(sql))
    return connection.execute(text(sql), params)


def _column(table_name: str, row: Mapping[str, object]) -> ColumnSnapshot:
    name = str(row["column_name"])
    return ColumnSnapshot(
        id=f"{BOOKSTORE_SCHEMA_NAME}.{table_name}.{name}",
        name=name,
        ordinal_position=int(row["ordinal_position"]),
        data_type=str(row["data_type"]),
        udt_name=str(row["udt_name"]),
        nullable=str(row["is_nullable"]).upper() in {"YES", "TRUE"},
        default=_optional_text(row.get("column_default")),
        identity=_identity(row.get("is_identity"), row.get("identity_generation")),
        generated=_generated(row.get("is_generated")),
        comment=_optional_text(row.get("column_comment")),
    )


def _constraint(table_name: str, row: Mapping[str, object]) -> ConstraintSnapshot:
    kind = _CONSTRAINT_KINDS[str(row["constraint_type"])]
    name = str(row["constraint_name"])
    referenced_table = _optional_text(row.get("foreign_table"))
    return ConstraintSnapshot(
        id=f"{BOOKSTORE_SCHEMA_NAME}.{table_name}.{name}",
        name=name,
        kind=kind,
        columns=_names(row.get("columns")),
        referenced_schema=(
            _optional_text(row.get("foreign_schema")) if kind == "foreign_key" else None
        ),
        referenced_table=referenced_table if kind == "foreign_key" else None,
        referenced_columns=_names(row.get("referenced_columns")) if kind == "foreign_key" else [],
        on_update=_ACTIONS.get(str(row.get("update_action"))) if kind == "foreign_key" else None,
        on_delete=_ACTIONS.get(str(row.get("delete_action"))) if kind == "foreign_key" else None,
        check_expression=_optional_text(row.get("definition")) if kind == "check" else None,
    )


def _group_indexes(
    rows: Sequence[Mapping[str, object]],
) -> dict[str, list[IndexSnapshot]]:
    grouped: dict[tuple[str, str], list[Mapping[str, object]]] = {}
    for row in rows:
        key = (str(row["table_name"]), str(row["index_name"]))
        grouped.setdefault(key, []).append(row)
    indexes_by_table: dict[str, list[IndexSnapshot]] = {}
    for (table_name, index_name), members in grouped.items():
        ordered = sorted(members, key=lambda item: int(item["position"]))
        snapshot = IndexSnapshot(
            id=f"{BOOKSTORE_SCHEMA_NAME}.{table_name}.{index_name}",
            name=index_name,
            unique=bool(ordered[0]["is_unique"]),
            primary=bool(ordered[0]["is_primary"]),
            columns=[str(item["column_name"]) for item in ordered],
            directions=[_direction(item["direction"]) for item in ordered],
        )
        indexes_by_table.setdefault(table_name, []).append(snapshot)
    for indexes in indexes_by_table.values():
        indexes.sort(key=lambda index: index.name)
    return indexes_by_table


def _identity(is_identity: object, generation: object) -> IdentityGeneration:
    if str(is_identity).upper() not in {"YES", "TRUE"}:
        return "none"
    normalized = str(generation or "").upper().replace(" ", "_")
    if normalized == "ALWAYS":
        return "always"
    if normalized == "BY_DEFAULT":
        return "by_default"
    return "none"


def _generated(value: object) -> GeneratedKind:
    if str(value).upper() == "ALWAYS":
        return "always"
    return "never"


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _names(value: object) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item) for item in value]


def _direction(value: object) -> IndexDirection:
    if value == "desc":
        return "desc"
    return "asc"
