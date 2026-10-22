"""Validated schema-inspection models. Field order is part of the API contract."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AccessMode = Literal["read_only"]
SourceKind = Literal["demo"]
IdentityGeneration = Literal["always", "by_default", "none"]
GeneratedKind = Literal["always", "never"]
ConstraintKind = Literal["check", "foreign_key", "primary_key", "unique"]
IndexDirection = Literal["asc", "desc"]
ReferentialAction = Literal["cascade", "no_action", "restrict", "set_default", "set_null"]


class SourceSummary(BaseModel):
    """A configured source. This model never carries a URL or password."""

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: SourceKind
    display_name: str
    database_name: str
    schema_name: str
    configured: bool
    access: AccessMode


class SourceListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sources: list[SourceSummary]


class ColumnSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    ordinal_position: int
    data_type: str
    udt_name: str
    nullable: bool
    default: str | None = None
    identity: IdentityGeneration
    generated: GeneratedKind
    comment: str | None = None


class ConstraintSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    kind: ConstraintKind
    columns: list[str]
    referenced_schema: str | None = None
    referenced_table: str | None = None
    referenced_columns: list[str] = Field(default_factory=list)
    on_update: ReferentialAction | None = None
    on_delete: ReferentialAction | None = None
    check_expression: str | None = None


class IndexSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    unique: bool
    primary: bool
    columns: list[str]
    directions: list[IndexDirection]


class DependencySnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    from_table: str
    to_table: str
    constraint_name: str
    from_columns: list[str]
    to_columns: list[str]


class TableSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    schema_name: str
    name: str
    comment: str | None = None
    columns: list[ColumnSnapshot]
    constraints: list[ConstraintSnapshot]
    indexes: list[IndexSnapshot]


class SchemaSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    database_name: str
    schema_name: str
    tables: list[TableSnapshot]
    dependencies: list[DependencySnapshot]
    fingerprint: str
