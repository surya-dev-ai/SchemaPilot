"""Shared operation literals used by planning and LLM interpretation schemas."""

from typing import Literal

OperationKind = Literal[
    "add_column",
    "add_index",
    "rename_column",
    "rename_table",
    "add_constraint",
    "destructive",
]
ConstraintRequestKind = Literal["unique", "not_null", "check"]
ClarificationTopic = Literal["table", "column", "data_type", "behavior", "constraint", "index"]
