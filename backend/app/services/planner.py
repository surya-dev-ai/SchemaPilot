"""Deterministic migration planner.

The planner reads table and column names from a schema snapshot. It does not
open a connection, execute SQL, or treat schema comments as instructions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.schemas.domain import SchemaSnapshot
from app.schemas.planning import (
    Assumption,
    ClarificationQuestion,
    ClarificationTopic,
    MigrationProposal,
    PlanOperation,
    PlanStatus,
    PlanValidationError,
    ValidationCode,
)

if TYPE_CHECKING:
    from app.schemas.interpretation import LlmInterpretationPayload, LlmOperationDraft

_IDENTIFIER = r"[a-z_][a-z0-9_]*"
_TYPE_PATTERNS = (
    (r"\btimestamp with time zone\b", "timestamptz"),
    (r"\btimestamptz\b", "timestamptz"),
    (r"\btimestamp\b", "timestamptz"),
    (r"\bbigint\b", "bigint"),
    (r"\binteger\b|\bint\b", "integer"),
    (r"\bboolean\b|\bbool\b", "boolean"),
    (r"\btext\b|\bstring\b|\bvarchar\b", "text"),
)
_SKIP_NAMES = {
    "a",
    "an",
    "the",
    "to",
    "on",
    "of",
    "in",
    "table",
    "column",
    "field",
    "nullable",
    "optional",
    "null",
    "not",
    "default",
    "with",
    "text",
    "string",
    "varchar",
    "integer",
    "int",
    "bigint",
    "boolean",
    "bool",
    "timestamp",
    "timestamptz",
    "add",
    "create",
    "need",
    "give",
    "index",
    "unique",
    "constraint",
    "check",
    "soft",
    "delete",
    "support",
    "using",
}


@dataclass
class _Index:
    tables: dict[str, dict[str, bool]]
    unique_columns: dict[str, set[str]]
    indexes: dict[str, list[tuple[str, ...]]]

    @classmethod
    def from_snapshot(cls, snapshot: SchemaSnapshot) -> _Index:
        tables: dict[str, dict[str, bool]] = {}
        unique_columns: dict[str, set[str]] = {}
        indexes: dict[str, list[tuple[str, ...]]] = {}
        for table in snapshot.tables:
            tables[table.name] = {column.name: column.nullable for column in table.columns}
            unique: set[str] = set()
            for constraint in table.constraints:
                if constraint.kind in {"unique", "primary_key"}:
                    unique.update(constraint.columns)
            unique_columns[table.name] = unique
            indexes[table.name] = [tuple(index.columns) for index in table.indexes]
        return cls(tables=tables, unique_columns=unique_columns, indexes=indexes)


@dataclass
class _Draft:
    assumptions: list[str] = field(default_factory=list)
    questions: list[tuple[ClarificationTopic, str]] = field(default_factory=list)
    errors: list[tuple[ValidationCode, str, str | None]] = field(default_factory=list)
    operations: list[PlanOperation] = field(default_factory=list)
    destructive: bool = False


def propose_migration(snapshot: SchemaSnapshot, request_text: str) -> MigrationProposal:
    """Turn one natural-language request into a structured proposal."""

    normalized = _normalize(request_text)
    draft = _Draft()
    if not normalized:
        draft.errors.append(("malformed_request", "The request is empty.", None))
    else:
        index = _Index.from_snapshot(snapshot)
        _parse(normalized, index, draft)
    return _proposal(snapshot, request_text.strip(), draft)


def propose_from_llm_payload(
    snapshot: SchemaSnapshot,
    request_text: str,
    payload: LlmInterpretationPayload,
) -> MigrationProposal:
    """Validate an LLM draft through the same snapshot rules as the planner.

    This never executes SQL. Unknown objects and unsupported shapes are rejected.
    """

    from app.schemas.interpretation import LlmInterpretationPayload as PayloadModel

    if not isinstance(payload, PayloadModel):
        payload = PayloadModel.model_validate(payload)
    draft = _Draft()
    if payload.schema_fingerprint != snapshot.fingerprint:
        draft.errors.append(
            (
                "malformed_request",
                "The LLM suggestion schema fingerprint does not match the inspected snapshot.",
                None,
            )
        )
        return _proposal(snapshot, request_text.strip(), draft)
    index = _Index.from_snapshot(snapshot)
    for assumption in payload.assumptions:
        draft.assumptions.append(assumption)
    for question in payload.clarification_questions:
        draft.questions.append((question.topic, question.text))
    if not payload.operations and not payload.clarification_questions:
        draft.errors.append(
            (
                "malformed_request",
                "The LLM suggestion included neither operations nor clarification questions.",
                None,
            )
        )
        return _proposal(snapshot, request_text.strip(), draft)
    for operation in payload.operations:
        _validate_llm_operation(operation, index, draft)
    if payload.summary and not draft.errors and not draft.questions:
        # Prefer the model summary only when validation produced a clean proposal.
        pass
    proposal = _proposal(snapshot, request_text.strip(), draft)
    if (
        proposal.status == "proposed"
        and payload.summary
        and not draft.destructive
        and proposal.operations
    ):
        return proposal.model_copy(update={"summary": payload.summary[:500]})
    return proposal


def _validate_llm_operation(operation: LlmOperationDraft, index: _Index, draft: _Draft) -> None:
    if operation.kind == "destructive" or operation.destructive:
        draft.destructive = True
        table = operation.table
        if table is None or not _valid_name(table):
            _error(draft, "invalid_identifier", "Destructive operation needs a table.", None)
            return
        if table not in index.tables:
            _error(draft, "unknown_table", f"Table {table} does not exist.", table)
            return
        draft.operations.append(
            _operation(
                kind="destructive",
                summary=(
                    f"Dropping or truncating {table} is destructive and is not executed."
                    if operation.column is None
                    else f"Dropping {table}.{operation.column} is destructive and is not executed."
                ),
                table=table,
                column=operation.column,
                destructive=True,
            )
        )
        return
    if operation.kind == "add_column":
        _llm_add_column(operation, index, draft)
        return
    if operation.kind == "add_index":
        _llm_add_index(operation, index, draft)
        return
    if operation.kind == "rename_column":
        _llm_rename_column(operation, index, draft)
        return
    if operation.kind == "rename_table":
        _llm_rename_table(operation, index, draft)
        return
    if operation.kind == "add_constraint":
        _llm_add_constraint(operation, index, draft)
        return
    _error(
        draft,
        "unsupported_operation",
        f"Operation kind {operation.kind} is not supported.",
        None,
    )


def _llm_add_column(operation: LlmOperationDraft, index: _Index, draft: _Draft) -> None:
    table = operation.table
    column = operation.column
    data_type = operation.data_type
    if table is None or not _known_table(table, index, draft):
        return
    if column is None or not _valid_name(column):
        _error(draft, "invalid_identifier", "New column name is invalid.", column)
        return
    if column in index.tables[table]:
        _error(
            draft,
            "column_exists",
            f"Column {column} already exists on {table}.",
            f"{table}.{column}",
        )
        return
    if data_type is None or data_type not in {
        "text",
        "integer",
        "bigint",
        "boolean",
        "timestamptz",
    }:
        draft.questions.append(("data_type", "Which supported data type should the column use?"))
        return
    nullable = True if operation.nullable is None else operation.nullable
    if operation.nullable is None and operation.default is None:
        draft.assumptions.append(
            "Nullability was not stated by the model. The proposal keeps the column nullable."
        )
    draft.operations.append(
        _operation(
            kind="add_column",
            summary=_column_summary(table, column, data_type, nullable, operation.default),
            table=table,
            column=column,
            data_type=data_type,
            nullable=nullable,
            default=operation.default,
        )
    )


def _llm_add_index(operation: LlmOperationDraft, index: _Index, draft: _Draft) -> None:
    table = operation.table
    columns = list(operation.index_columns) or ([operation.column] if operation.column else [])
    if table is None or not _known_table(table, index, draft):
        return
    if not columns:
        draft.questions.append(("index", "Which column or columns should the index cover?"))
        return
    for column in columns:
        if not _known_column(table, column, index, draft):
            return
    if tuple(columns) in index.indexes.get(table, []):
        _error(
            draft,
            "index_exists",
            f"An index already covers {table}.{'.'.join(columns)}.",
            f"{table}.{'.'.join(columns)}",
        )
        return
    draft.operations.append(
        _operation(
            kind="add_index",
            summary=f"Add an index on {table}.{', '.join(columns)}.",
            table=table,
            index_columns=columns,
        )
    )


def _llm_rename_column(operation: LlmOperationDraft, index: _Index, draft: _Draft) -> None:
    table = operation.table
    column = operation.column
    new_name = operation.new_name
    if table is None or not _known_table(table, index, draft):
        return
    if column is None or not _known_column(table, column, index, draft):
        return
    if new_name is None or not _valid_name(new_name):
        _error(draft, "invalid_identifier", "New column name is invalid.", new_name)
        return
    if new_name in index.tables[table]:
        _error(
            draft,
            "column_exists",
            f"Column {new_name} already exists on {table}.",
            f"{table}.{new_name}",
        )
        return
    draft.operations.append(
        _operation(
            kind="rename_column",
            summary=f"Rename column {table}.{column} to {new_name}.",
            table=table,
            column=column,
            new_name=new_name,
        )
    )


def _llm_rename_table(operation: LlmOperationDraft, index: _Index, draft: _Draft) -> None:
    table = operation.table
    new_name = operation.new_name
    if table is None or not _known_table(table, index, draft):
        return
    if new_name is None or not _valid_name(new_name):
        _error(draft, "invalid_identifier", "New table name is invalid.", new_name)
        return
    if new_name in index.tables:
        _error(draft, "table_exists", f"Table {new_name} already exists.", new_name)
        return
    draft.operations.append(
        _operation(
            kind="rename_table",
            summary=f"Rename table {table} to {new_name}.",
            table=table,
            new_name=new_name,
        )
    )


def _llm_add_constraint(operation: LlmOperationDraft, index: _Index, draft: _Draft) -> None:
    table = operation.table
    column = operation.column
    kind = operation.constraint_kind
    if table is None or not _known_table(table, index, draft):
        return
    if column is None or not _known_column(table, column, index, draft):
        return
    if kind is None:
        draft.questions.append(("constraint", "Which constraint kind should be added?"))
        return
    if kind == "check" and not operation.check_expression:
        draft.questions.append(("constraint", "What check expression should be enforced?"))
        return
    if kind == "unique" and column in index.unique_columns.get(table, set()):
        _error(
            draft,
            "constraint_exists",
            f"A uniqueness constraint already covers {table}.{column}.",
            f"{table}.{column}",
        )
        return
    draft.operations.append(
        _operation(
            kind="add_constraint",
            summary=f"Add {kind} constraint on {table}.{column}.",
            table=table,
            column=column,
            constraint_kind=kind,
            check_expression=operation.check_expression,
        )
    )


def _parse(text: str, index: _Index, draft: _Draft) -> None:
    destructive = _destructive_operation(text, index, draft)
    if _parse_soft_delete(text, index, draft):
        _append_destructive(draft, destructive)
        return
    if _parse_rename_column(text, index, draft):
        _append_destructive(draft, destructive)
        return
    if _parse_rename_table(text, index, draft):
        _append_destructive(draft, destructive)
        return
    if _parse_index(text, index, draft):
        _append_destructive(draft, destructive)
        return
    if _parse_constraint(text, index, draft):
        _append_destructive(draft, destructive)
        return
    if _parse_add_column(text, index, draft):
        _append_destructive(draft, destructive)
        return
    if destructive is not None:
        _append_destructive(draft, destructive)
        return
    if _is_unsupported(text):
        draft.errors.append(
            (
                "unsupported_operation",
                "This request is not one of the supported plan intents.",
                None,
            )
        )
        return
    draft.questions.append(
        (
            "behavior",
            "What schema change should be proposed? Supported requests add a column, "
            "add an index, rename a table or column, add an explicit constraint, "
            "or describe soft delete.",
        )
    )


def _parse_soft_delete(text: str, index: _Index, draft: _Draft) -> bool:
    if not re.search(r"\bsoft\s+delete\b", text):
        return False
    table = _one_table(text, index, draft)
    if table is None:
        return True
    if "deleted_at" in index.tables[table]:
        _error(draft, "column_exists", "Column deleted_at already exists.", f"{table}.deleted_at")
        return True
    draft.assumptions.append(
        "Soft delete is represented by a nullable deleted_at timestamp and does not remove rows."
    )
    draft.operations.append(
        _operation(
            kind="add_column",
            summary=f"Add nullable timestamptz column deleted_at to {table} for soft delete.",
            table=table,
            column="deleted_at",
            data_type="timestamptz",
            nullable=True,
        )
    )
    return True


def _parse_rename_column(text: str, index: _Index, draft: _Draft) -> bool:
    match = re.search(
        rf"\brename\s+(?:the\s+)?(?:column\s+)?({_IDENTIFIER})\s+(?:column\s+)?"
        rf"(?:on|of|in)\s+(?:the\s+)?(?:table\s+)?({_IDENTIFIER})\s+to\s+({_IDENTIFIER})\b",
        text,
    )
    dotted = re.search(
        rf"\brename\s+(?:[a-z_]+\.)?({_IDENTIFIER})\.({_IDENTIFIER})\s+to\s+({_IDENTIFIER})\b",
        text,
    )
    if match is None and dotted is None:
        if re.search(r"\brename\b", text) and re.search(r"\bcolumn\b", text):
            draft.questions.append(
                ("column", "Which column should be renamed, and what is the new name?")
            )
            draft.questions.append(("table", "Which table contains the column to rename?"))
            return True
        return False
    if match is not None:
        column, table, new_name = match.group(1), match.group(2), match.group(3)
    else:
        assert dotted is not None
        table, column, new_name = dotted.group(1), dotted.group(2), dotted.group(3)
    if not _known_table(table, index, draft):
        return True
    if column not in index.tables[table]:
        _error(
            draft,
            "unknown_column",
            f"Column {column} does not exist on {table}.",
            f"{table}.{column}",
        )
        return True
    if not _valid_name(new_name):
        _error(draft, "invalid_identifier", f"{new_name} is not a usable column name.", new_name)
        return True
    if new_name in index.tables[table]:
        _error(
            draft,
            "column_exists",
            f"Column {new_name} already exists on {table}.",
            f"{table}.{new_name}",
        )
        return True
    draft.operations.append(
        _operation(
            kind="rename_column",
            summary=f"Rename column {table}.{column} to {new_name}.",
            table=table,
            column=column,
            new_name=new_name,
        )
    )
    return True


def _parse_rename_table(text: str, index: _Index, draft: _Draft) -> bool:
    match = re.search(rf"\brename\s+table\s+({_IDENTIFIER})\s+to\s+({_IDENTIFIER})\b", text)
    if match is None:
        return False
    table, new_name = match.group(1), match.group(2)
    if not _known_table(table, index, draft):
        return True
    if not _valid_name(new_name):
        _error(draft, "invalid_identifier", f"{new_name} is not a usable table name.", new_name)
        return True
    if new_name in index.tables:
        _error(draft, "table_exists", f"Table {new_name} already exists.", new_name)
        return True
    draft.operations.append(
        _operation(
            kind="rename_table",
            summary=f"Rename table {table} to {new_name}.",
            table=table,
            new_name=new_name,
        )
    )
    return True


def _parse_index(text: str, index: _Index, draft: _Draft) -> bool:
    if not re.search(r"\bindex\b", text):
        return False
    located = _locate_column(text, index)
    if located is None:
        draft.questions.append(("table", "Which table should receive the index?"))
        draft.questions.append(("index", "Which column or columns should the index cover?"))
        return True
    table, column = located
    if not _known_column(table, column, index, draft):
        return True
    if (column,) in index.indexes.get(table, []):
        _error(
            draft,
            "index_exists",
            f"An index already covers {table}.{column}.",
            f"{table}.{column}",
        )
        return True
    draft.operations.append(
        _operation(
            kind="add_index",
            summary=f"Add an index on {table}.{column}.",
            table=table,
            index_columns=[column],
        )
    )
    return True


def _parse_constraint(text: str, index: _Index, draft: _Draft) -> bool:
    if not re.search(r"\bconstraint\b", text):
        return False
    if re.search(r"\bunique\s+constraint\b", text):
        kind = "unique"
    elif re.search(r"\bnot\s+null\s+constraint\b", text):
        kind = "not_null"
    elif re.search(r"\bcheck\s+constraint\b", text):
        kind = "check"
    else:
        draft.questions.append(
            (
                "constraint",
                "Which constraint should be added: unique, not null, or check? "
                "Name the table and column.",
            )
        )
        return True
    if kind == "check":
        table = _one_table(text, index, draft)
        expression = _check_expression(text)
        if table is None or expression is None:
            if expression is None:
                draft.questions.append(
                    (
                        "constraint",
                        "What explicit check should be recorded? "
                        "The text is stored and not executed.",
                    )
                )
            return True
        draft.assumptions.append(
            "The check expression is stored as untrusted text and is not executed."
        )
        draft.operations.append(
            _operation(
                kind="add_constraint",
                summary=f"Record a check constraint on {table}. The expression is not executed.",
                table=table,
                constraint_kind="check",
                check_expression=expression,
            )
        )
        return True
    located = _locate_column(text, index)
    if located is None:
        draft.questions.append(("column", "Which column should the constraint cover?"))
        draft.questions.append(("table", "Which table contains that column?"))
        return True
    table, column = located
    if not _known_column(table, column, index, draft):
        return True
    if kind == "unique" and column in index.unique_columns.get(table, set()):
        _error(
            draft,
            "constraint_exists",
            f"Column {table}.{column} is already covered by a unique or primary-key constraint.",
            f"{table}.{column}",
        )
        return True
    if kind == "not_null" and index.tables[table][column] is False:
        _error(
            draft,
            "constraint_exists",
            f"Column {table}.{column} is already not null.",
            f"{table}.{column}",
        )
        return True
    draft.operations.append(
        _operation(
            kind="add_constraint",
            summary=f"Add a {kind.replace('_', ' ')} constraint on {table}.{column}.",
            table=table,
            column=column,
            constraint_kind=kind,
        )
    )
    return True


def _parse_add_column(text: str, index: _Index, draft: _Draft) -> bool:
    if not re.search(r"\b(?:add|create|need|give)\b", text):
        return False
    if not re.search(r"\b(?:column|field)\b", text):
        return False
    table = _one_table(text, index, draft)
    column = _new_column_name(text, index)
    data_type = _data_type(text)
    default = _default_value(text)
    nullable = _nullability(text)
    if column is None:
        draft.questions.append(("column", "What should the new column be named?"))
    elif not _valid_name(column):
        _error(draft, "invalid_identifier", f"{column} is not a usable column name.", column)
        column = None
    if table is not None and column is not None and column in index.tables[table]:
        _error(
            draft,
            "column_exists",
            f"Column {column} already exists on {table}.",
            f"{table}.{column}",
        )
        return True
    if data_type is None:
        draft.questions.append(("data_type", "What data type should the new column use?"))
    if nullable is None and default is None:
        draft.questions.append(
            (
                "behavior",
                "Should the new column be nullable, or should it have an explicit default?",
            )
        )
    incomplete = table is None or column is None or data_type is None
    if incomplete or (nullable is None and default is None):
        return True
    if nullable is None:
        nullable = True
        draft.assumptions.append(
            "Nullability was not stated. The proposal keeps the new column nullable."
        )
    draft.operations.append(
        _operation(
            kind="add_column",
            summary=_column_summary(table, column, data_type, nullable, default),
            table=table,
            column=column,
            data_type=data_type,
            nullable=nullable,
            default=default,
        )
    )
    return True


def _destructive_operation(text: str, index: _Index, draft: _Draft) -> PlanOperation | None:
    table_match = re.search(rf"\bdrop\s+table\s+(?:[a-z_]+\.)?({_IDENTIFIER})\b", text)
    named_table = re.search(rf"\bdrop\s+(?:the\s+)?({_IDENTIFIER})\s+table\b", text)
    column_match = re.search(
        rf"\b(?:drop|remove|delete)\s+(?:the\s+)?(?:column\s+)?({_IDENTIFIER})\s+column\s+"
        rf"(?:from|on)\s+({_IDENTIFIER})\b",
        text,
    )
    drop_column = re.search(
        rf"\bdrop\s+column\s+({_IDENTIFIER})\s+(?:from|on)\s+({_IDENTIFIER})\b",
        text,
    )
    truncate = re.search(rf"\btruncate\s+(?:table\s+)?(?:[a-z_]+\.)?({_IDENTIFIER})\b", text)
    matched = table_match or named_table or truncate
    if matched is not None:
        table = matched.group(1)
        draft.destructive = True
        if table not in index.tables:
            _error(draft, "unknown_table", f"Table {table} does not exist.", table)
            return None
        return _operation(
            kind="destructive",
            summary=f"Dropping or truncating {table} is destructive and is not executed.",
            table=table,
            destructive=True,
        )
    match = drop_column or column_match
    if match is None:
        return None
    column, table = match.group(1), match.group(2)
    draft.destructive = True
    if not _known_column(table, column, index, draft):
        return None
    return _operation(
        kind="destructive",
        summary=f"Dropping {table}.{column} is destructive and is not executed.",
        table=table,
        column=column,
        destructive=True,
    )


def _append_destructive(draft: _Draft, operation: PlanOperation | None) -> None:
    if operation is None:
        return
    draft.destructive = True
    draft.operations.append(operation)


def _proposal(snapshot: SchemaSnapshot, request_text: str, draft: _Draft) -> MigrationProposal:
    questions = [
        ClarificationQuestion(id=f"question-{offset}", topic=topic, text=text)
        for offset, (topic, text) in enumerate(draft.questions, start=1)
    ]
    errors = [
        PlanValidationError(id=f"error-{offset}", code=code, message=message, object_name=name)
        for offset, (code, message, name) in enumerate(draft.errors, start=1)
    ]
    operations = [
        operation.model_copy(update={"id": f"op-{offset}"})
        for offset, operation in enumerate(draft.operations, start=1)
    ]
    assumptions = [
        Assumption(id=f"assumption-{offset}", text=text)
        for offset, text in enumerate(draft.assumptions, start=1)
    ]
    if errors:
        status: PlanStatus = "rejected"
        summary = errors[0].message
        operations = []
    elif questions:
        status = "needs_clarification"
        summary = questions[0].text
        operations = [operation for operation in operations if operation.destructive]
    elif draft.destructive:
        status = "proposed"
        summary = (
            "The request includes a destructive change. "
            "It is marked for later risk assessment and is not executed."
        )
    else:
        status = "proposed"
        summary = operations[0].summary if operations else "No schema change was proposed."
    return MigrationProposal(
        source_id=snapshot.source_id,
        schema_name=snapshot.schema_name,
        schema_fingerprint=snapshot.fingerprint,
        request=request_text,
        status=status,
        summary=summary,
        assumptions=assumptions,
        clarification_questions=questions,
        operations=operations,
        validation_errors=errors,
        destructive=draft.destructive,
        requires_risk_assessment=draft.destructive,
    )


def _operation(
    *,
    kind: str,
    summary: str,
    table: str | None = None,
    column: str | None = None,
    data_type: str | None = None,
    nullable: bool | None = None,
    default: str | None = None,
    new_name: str | None = None,
    index_columns: list[str] | None = None,
    constraint_kind: str | None = None,
    check_expression: str | None = None,
    destructive: bool = False,
) -> PlanOperation:
    return PlanOperation(
        id="op-pending",
        kind=kind,  # type: ignore[arg-type]
        summary=summary,
        table=table,
        column=column,
        data_type=data_type,
        nullable=nullable,
        default=default,
        new_name=new_name,
        index_columns=index_columns or [],
        constraint_kind=constraint_kind,  # type: ignore[arg-type]
        check_expression=check_expression,
        destructive=destructive,
    )


def _one_table(text: str, index: _Index, draft: _Draft) -> str | None:
    unknown = [
        name
        for name in _explicit_table_names(text)
        if name not in index.tables and name not in _SKIP_NAMES
    ]
    if unknown:
        _error(draft, "unknown_table", f"Table {unknown[0]} does not exist.", unknown[0])
        return None
    found = _mentioned_tables(text, index)
    if len(found) == 1:
        return found[0]
    if len(found) == 0:
        draft.questions.append(("table", "Which table should this change apply to?"))
        return None
    draft.questions.append(
        ("table", "Which one of the mentioned tables should this change apply to?")
    )
    return None


def _explicit_table_names(text: str) -> list[str]:
    names = re.findall(rf"\b(?:to|on|from)\s+(?:the\s+)?({_IDENTIFIER})\b", text)
    names.extend(re.findall(rf"\btable\s+({_IDENTIFIER})\b", text))
    return names


def _mentioned_tables(text: str, index: _Index) -> list[str]:
    found: list[str] = []
    for name in sorted(index.tables, key=len, reverse=True):
        if re.search(rf"\b{re.escape(name)}\b", text):
            found.append(name)
    return found


def _known_table(table: str, index: _Index, draft: _Draft) -> bool:
    if table in index.tables:
        return True
    _error(draft, "unknown_table", f"Table {table} does not exist.", table)
    return False


def _known_column(table: str, column: str, index: _Index, draft: _Draft) -> bool:
    if not _known_table(table, index, draft):
        return False
    if column in index.tables[table]:
        return True
    _error(
        draft,
        "unknown_column",
        f"Column {column} does not exist on {table}.",
        f"{table}.{column}",
    )
    return False


def _locate_column(text: str, index: _Index) -> tuple[str, str] | None:
    dotted = re.search(rf"\b(?:[a-z_]+\.)?({_IDENTIFIER})\.({_IDENTIFIER})\b", text)
    if dotted is not None and dotted.group(1) in index.tables:
        return dotted.group(1), dotted.group(2)
    described = re.search(
        rf"\b(?:on|for)\s+the\s+({_IDENTIFIER})\s+column\s+of\s+({_IDENTIFIER})\b",
        text,
    )
    if described is not None:
        return described.group(2), described.group(1)
    by_column = re.search(rf"\b({_IDENTIFIER})\s+by\s+({_IDENTIFIER})\b", text)
    if by_column is not None and by_column.group(1) in index.tables:
        return by_column.group(1), by_column.group(2)
    return None


def _new_column_name(text: str, index: _Index) -> str | None:
    patterns = (
        rf"\b(?:called|named)\s+({_IDENTIFIER})\b",
        rf"\b({_IDENTIFIER})\s+(?:column|field)\b",
        rf"\b(?:column|field)\s+({_IDENTIFIER})\b",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            name = match.group(1)
            if name in _SKIP_NAMES or name in index.tables:
                continue
            return name
    return None


def _data_type(text: str) -> str | None:
    for pattern, name in _TYPE_PATTERNS:
        if re.search(pattern, text):
            return name
    return None


def _default_value(text: str) -> str | None:
    match = re.search(rf"\bdefault\s+('(?:[^']*)'|\d+|{_IDENTIFIER})\b", text)
    if match is None:
        return None
    value = match.group(1)
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    return value


def _nullability(text: str) -> bool | None:
    if re.search(r"\bnot\s+null\b|\brequired\b", text):
        return False
    if re.search(r"\bnullable\b|\boptional\b", text):
        return True
    return None


def _check_expression(text: str) -> str | None:
    match = re.search(r"\b(?:requiring|that)\s+(.+)$", text)
    if match is None:
        return None
    expression = match.group(1).strip(" .")
    return expression or None


def _is_unsupported(text: str) -> bool:
    return bool(
        re.search(r"\b(?:change|alter)\b.+\btype\b", text)
        or re.search(r"\bcreate\s+view\b", text)
        or re.search(r"\b(?:execute|run)\b", text)
        or re.search(r"\balembic\b", text)
        or re.search(r"\bgrant\b", text)
    )


def _column_summary(
    table: str,
    column: str,
    data_type: str,
    nullable: bool,
    default: str | None,
) -> str:
    null_text = "nullable" if nullable else "not null"
    if default is None:
        return f"Add {null_text} {data_type} column {column} to {table}."
    return f"Add {null_text} {data_type} column {column} to {table} with default {default}."


def _valid_name(value: str) -> bool:
    return bool(re.fullmatch(_IDENTIFIER, value)) and value not in _SKIP_NAMES


def _error(draft: _Draft, code: ValidationCode, message: str, object_name: str | None) -> None:
    draft.errors.append((code, message, object_name))


def _normalize(value: str) -> str:
    text = value.strip().lower().replace("-", " ")
    return re.sub(r"\s+", " ", text).strip()
