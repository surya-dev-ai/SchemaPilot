"""Checks for a generated artifact and for the sandbox after an upgrade.

This module does not open a connection. A `not_run` risk check is never
reported as passed.
"""

import re
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from app.demo.bookstore import EXPECTED_COUNTS, EXPECTED_EMAILS, EXPECTED_TABLES
from app.schemas.artifacts import MigrationArtifact
from app.schemas.sandbox import SandboxCheck

_IDENTIFIER = r"[a-z_][a-z0-9_]*"
_TYPE = r"TEXT|INTEGER|BIGINT|BOOLEAN|TIMESTAMP WITH TIME ZONE"
_ADD_COLUMN = re.compile(
    rf'^ALTER TABLE "(?P<schema>{_IDENTIFIER})"\."(?P<table>{_IDENTIFIER})" '
    rf'ADD COLUMN "(?P<column>{_IDENTIFIER})" (?P<data_type>{_TYPE}) NULL;$'
)
_CREATE_INDEX = re.compile(
    rf'^CREATE INDEX "(?P<index>{_IDENTIFIER})" ON '
    rf'"(?P<schema>{_IDENTIFIER})"\."(?P<table>{_IDENTIFIER})" '
    rf'\((?P<columns>"{_IDENTIFIER}"(?:, "{_IDENTIFIER}")*)\);$'
)
_RENAME_COLUMN = re.compile(
    rf'^ALTER TABLE "(?P<schema>{_IDENTIFIER})"\."(?P<table>{_IDENTIFIER})" '
    rf'RENAME COLUMN "(?P<old>{_IDENTIFIER})" TO "(?P<new>{_IDENTIFIER})";$'
)
_RENAME_TABLE = re.compile(
    rf'^ALTER TABLE "(?P<schema>{_IDENTIFIER})"\."(?P<table>{_IDENTIFIER})" '
    rf'RENAME TO "(?P<new>{_IDENTIFIER})";$'
)
_BLOCKED = re.compile(
    r"\bdrop\s+table\b|\btruncate\b|\badd\s+constraint\b|\bset\s+not\s+null\b|"
    r"\bdrop\s+column\b|\bexecute\b",
    re.IGNORECASE,
)


class ArtifactNotEligible(Exception):
    """The artifact cannot be applied. `code` is a stable rejection reason."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class UpgradeStatement:
    kind: str
    sql_text: str
    schema_name: str
    table: str
    column: str | None = None
    data_type: str | None = None
    index_name: str | None = None
    columns: tuple[str, ...] = ()
    new_name: str | None = None


def parse_upgrade_sql(sql_preview: str) -> list[UpgradeStatement]:
    """Accept only the upgrade statements the artifact generator can emit."""

    statements: list[UpgradeStatement] = []
    for raw_line in sql_preview.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _BLOCKED.search(line):
            raise ArtifactNotEligible(
                "policy_blocked",
                "The artifact SQL contains an operation this sandbox will not run.",
            )
        parsed = _parse_line(line)
        if parsed is None or parsed.schema_name != "bookstore":
            raise ArtifactNotEligible(
                "unsupported_operation",
                "The artifact SQL is not one of the supported upgrade statements.",
            )
        statements.append(parsed)
    if not statements:
        raise ArtifactNotEligible(
            "unsupported_operation",
            "The artifact has no upgrade statement to run.",
        )
    return statements


def assert_alembic_matches(artifact: MigrationArtifact, statements: list[UpgradeStatement]) -> None:
    """Require the Alembic upgrade body to name the same objects as the SQL preview."""

    upgrade = _upgrade_body(artifact.alembic_source)
    if upgrade is None or re.search(r"\bop\.(execute|drop_table|add_constraint)\b", upgrade):
        raise ArtifactNotEligible(
            "policy_blocked",
            "The Alembic upgrade body is not an eligible generated operation.",
        )
    if "nullable=False" in upgrade:
        raise ArtifactNotEligible(
            "data_check_not_run",
            "A not-null column was not cleared by a live row check.",
        )
    for statement in statements:
        if not _upgrade_mentions(upgrade, statement):
            raise ArtifactNotEligible(
                "artifact_inconsistent",
                "The SQL preview and the Alembic module do not describe the same change.",
            )


def validate_upgrade(
    connection: Connection,
    statements: list[UpgradeStatement],
) -> list[SandboxCheck]:
    """Read the sandbox catalog after an upgrade. Unrun checks stay `not_run`."""

    checks = [
        _check(
            "risk_row_checks",
            "not_run",
            "Unresolved risk row checks are not treated as passed.",
        ),
        _check(
            "target_database",
            "not_run",
            "Target execution is not part of this phase.",
        ),
    ]
    checks.extend(_change_checks(connection, statements))
    checks.extend(_invariant_checks(connection, statements))
    return checks


def baseline_matches(connection: Connection) -> bool:
    """True when the bookstore tables and seed counts match the packaged source."""

    if _table_names(connection) != EXPECTED_TABLES:
        return False
    return all(_count(connection, table) == expected for table, expected in EXPECTED_COUNTS.items())


def _parse_line(line: str) -> UpgradeStatement | None:
    match = _ADD_COLUMN.fullmatch(line)
    if match is not None:
        return UpgradeStatement(
            kind="add_column",
            sql_text=line,
            schema_name=match.group("schema"),
            table=match.group("table"),
            column=match.group("column"),
            data_type=match.group("data_type"),
        )
    match = _CREATE_INDEX.fullmatch(line)
    if match is not None:
        columns = tuple(part.strip().strip('"') for part in match.group("columns").split(","))
        return UpgradeStatement(
            kind="add_index",
            sql_text=line,
            schema_name=match.group("schema"),
            table=match.group("table"),
            index_name=match.group("index"),
            columns=columns,
        )
    match = _RENAME_COLUMN.fullmatch(line)
    if match is not None:
        return UpgradeStatement(
            kind="rename_column",
            sql_text=line,
            schema_name=match.group("schema"),
            table=match.group("table"),
            column=match.group("old"),
            new_name=match.group("new"),
        )
    match = _RENAME_TABLE.fullmatch(line)
    if match is not None:
        return UpgradeStatement(
            kind="rename_table",
            sql_text=line,
            schema_name=match.group("schema"),
            table=match.group("table"),
            new_name=match.group("new"),
        )
    return None


def _upgrade_body(source: str) -> str | None:
    if "def upgrade()" not in source or "def downgrade()" not in source:
        return None
    return source.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]


def _upgrade_mentions(upgrade: str, statement: UpgradeStatement) -> bool:
    if statement.kind == "add_column":
        return (
            "op.add_column(" in upgrade
            and f'"{statement.table}"' in upgrade
            and f'"{statement.column}"' in upgrade
        )
    if statement.kind == "add_index":
        return "op.create_index(" in upgrade and f'"{statement.index_name}"' in upgrade
    if statement.kind == "rename_column":
        return (
            "op.alter_column(" in upgrade
            and f'"{statement.column}"' in upgrade
            and f'"{statement.new_name}"' in upgrade
        )
    return (
        "op.rename_table(" in upgrade
        and f'"{statement.table}"' in upgrade
        and f'"{statement.new_name}"' in upgrade
    )


def _change_checks(
    connection: Connection,
    statements: list[UpgradeStatement],
) -> list[SandboxCheck]:
    checks: list[SandboxCheck] = []
    for statement in statements:
        if statement.kind == "add_column":
            checks.append(_column_check(connection, statement))
        elif statement.kind == "add_index":
            checks.append(_index_check(connection, statement))
        elif statement.kind == "rename_column":
            checks.append(_renamed_column_check(connection, statement))
        else:
            checks.append(_renamed_table_check(connection, statement))
    return checks


def _column_check(connection: Connection, statement: UpgradeStatement) -> SandboxCheck:
    row = connection.execute(
        text(
            "SELECT data_type, is_nullable FROM information_schema.columns "
            "WHERE table_schema = :schema AND table_name = :table AND column_name = :column"
        ),
        {
            "schema": statement.schema_name,
            "table": statement.table,
            "column": statement.column,
        },
    ).one_or_none()
    expected = _sql_type(statement.data_type or "")
    if row is None or row[0] != expected or row[1] != "YES":
        return _check(
            f"column:{statement.table}.{statement.column}",
            "failed",
            "The new column is missing or does not match the artifact.",
        )
    populated = connection.execute(
        text(
            f'SELECT count(*) FROM "{statement.schema_name}"."{statement.table}" '
            f'WHERE "{statement.column}" IS NOT NULL'
        )
    ).scalar_one()
    if populated != 0:
        return _check(
            f"column:{statement.table}.{statement.column}",
            "failed",
            "Existing rows were expected to keep the new nullable column empty.",
        )
    return _check(
        f"column:{statement.table}.{statement.column}",
        "passed",
        "The nullable column exists and existing rows are null.",
    )


def _index_check(connection: Connection, statement: UpgradeStatement) -> SandboxCheck:
    found = connection.execute(
        text(
            "SELECT count(*) FROM pg_catalog.pg_class AS c "
            "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
            "WHERE n.nspname = :schema AND c.relname = :index AND c.relkind = 'i'"
        ),
        {"schema": statement.schema_name, "index": statement.index_name},
    ).scalar_one()
    if found != 1:
        return _check(
            f"index:{statement.index_name}",
            "failed",
            "The artifact index was not found.",
        )
    return _check(f"index:{statement.index_name}", "passed", "The artifact index exists.")


def _renamed_column_check(connection: Connection, statement: UpgradeStatement) -> SandboxCheck:
    new_name = _column_present(connection, statement.table, statement.new_name)
    old_name = _column_present(connection, statement.table, statement.column)
    if new_name and not old_name:
        return _check(
            f"rename_column:{statement.table}.{statement.new_name}",
            "passed",
            "The column uses the artifact name.",
        )
    return _check(
        f"rename_column:{statement.table}.{statement.column}",
        "failed",
        "The column rename was not observed.",
    )


def _renamed_table_check(connection: Connection, statement: UpgradeStatement) -> SandboxCheck:
    tables = _table_names(connection)
    if statement.new_name in tables and statement.table not in tables:
        return _check(
            f"rename_table:{statement.new_name}",
            "passed",
            "The table uses the artifact name.",
        )
    return _check(
        f"rename_table:{statement.table}",
        "failed",
        "The table rename was not observed.",
    )


def _invariant_checks(
    connection: Connection,
    statements: list[UpgradeStatement],
) -> list[SandboxCheck]:
    renamed = {
        statement.table: statement.new_name
        for statement in statements
        if statement.kind == "rename_table" and statement.new_name is not None
    }
    checks: list[SandboxCheck] = []
    for table, expected in EXPECTED_COUNTS.items():
        current = renamed.get(table, table)
        if current not in _table_names(connection):
            checks.append(_check(f"count:{table}", "not_run", "The table is not in the sandbox."))
            continue
        actual = _count(connection, current)
        status = "passed" if actual == expected else "failed"
        checks.append(_check(f"count:{table}", status, f"Observed {actual} rows."))
    if "users" in _table_names(connection) and "users" not in renamed:
        emails = tuple(
            connection.execute(text("SELECT email FROM bookstore.users ORDER BY id")).scalars()
        )
        status = "passed" if emails == EXPECTED_EMAILS else "failed"
        checks.append(_check("seed_emails", status, "Compared the packaged user emails."))
        checks.append(_duplicate_email_check(connection))
    else:
        checks.append(_check("seed_emails", "not_run", "users was renamed or is absent."))
        checks.append(
            _check("duplicate_email", "not_run", "The email constraint was not probed.")
        )
    return checks


def _duplicate_email_check(connection: Connection) -> SandboxCheck:
    try:
        with connection.begin_nested():
            connection.execute(
                text(
                    "INSERT INTO bookstore.users (email, display_name) "
                    "VALUES ('mira@example.test', 'Duplicate')"
                )
            )
    except IntegrityError:
        return _check(
            "duplicate_email",
            "passed",
            "The unique email constraint raised a violation and the insert was rolled back.",
        )
    return _check(
        "duplicate_email",
        "failed",
        "The unique email constraint did not reject a duplicate.",
    )


def _column_present(connection: Connection, table: str, column: str | None) -> bool:
    if column is None:
        return False
    found = connection.execute(
        text(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_schema = 'bookstore' AND table_name = :table AND column_name = :column"
        ),
        {"table": table, "column": column},
    ).scalar_one()
    return found == 1


def _table_names(connection: Connection) -> tuple[str, ...]:
    rows = connection.execute(
        text(
            "SELECT c.relname FROM pg_catalog.pg_class AS c "
            "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'bookstore' AND c.relkind = 'r' ORDER BY c.relname"
        )
    ).scalars()
    return tuple(rows)


def _count(connection: Connection, table: str) -> int:
    if not re.fullmatch(_IDENTIFIER, table):
        raise ArtifactNotEligible("unsupported_operation", "The table name is not safe.")
    value = connection.execute(text(f'SELECT count(*) FROM "bookstore"."{table}"')).scalar_one()
    return int(value)


def _sql_type(rendered: str) -> str:
    return {
        "TEXT": "text",
        "INTEGER": "integer",
        "BIGINT": "bigint",
        "BOOLEAN": "boolean",
        "TIMESTAMP WITH TIME ZONE": "timestamp with time zone",
    }[rendered]


def _check(name: str, status: str, detail: str) -> SandboxCheck:
    return SandboxCheck(name=name, status=status, detail=detail)  # type: ignore[arg-type]
