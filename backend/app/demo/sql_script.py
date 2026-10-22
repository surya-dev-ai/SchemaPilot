"""Load the packaged bookstore SQL scripts. These files are not user uploads."""

from pathlib import Path

SQL_DIRECTORY = Path(__file__).with_name("sql")
ALLOWED_SQL_FILES = frozenset({"schema.sql", "seed.sql"})


def read_sql_file(name: str) -> str:
    if name not in ALLOWED_SQL_FILES:
        raise ValueError(f"Unknown demo SQL file: {name}")
    return (SQL_DIRECTORY / name).read_text(encoding="utf-8")


def split_sql_script(script: str) -> list[str]:
    """Split a simple SQL script on semicolons.

    Line comments are discarded. Quoted semicolons stay inside the statement.
    This splitter is for the packaged demo scripts, which do not use dollar quotes.
    """

    statements: list[str] = []
    current: list[str] = []
    in_single = False
    index = 0
    while index < len(script):
        character = script[index]
        following = script[index + 1] if index + 1 < len(script) else ""
        if not in_single and character == "-" and following == "-":
            newline = script.find("\n", index)
            if newline == -1:
                break
            index = newline + 1
            continue
        if character == "'":
            in_single = not in_single
            current.append(character)
            index += 1
            continue
        if character == ";" and not in_single:
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
            index += 1
            continue
        current.append(character)
        index += 1
    tail = "".join(current).strip()
    if tail:
        statements.append(tail)
    return statements
