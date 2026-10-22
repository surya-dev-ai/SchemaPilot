"""Reviewable migration artifacts. These models do not apply SQL."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.schemas.planning import OperationKind

ArtifactStatus = Literal["generated"]
ArtifactReversibility = Literal["reversible", "partially_reversible", "irreversible"]


class OperationReversibility(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: str
    kind: OperationKind
    reversibility: ArtifactReversibility
    upgrade_effect: str
    downgrade_effect: str
    data_loss_on_downgrade: bool


class MigrationArtifact(BaseModel):
    """A generated preview. `applied` stays false because this phase does not run it."""

    model_config = ConfigDict(extra="forbid")

    migration_id: str
    source_id: str
    schema_name: str
    schema_fingerprint: str
    summary: str
    status: ArtifactStatus
    applied: Literal[False] = False
    operation_ids: list[str]
    sql_preview: str
    downgrade_sql: str
    alembic_source: str
    reversibility: ArtifactReversibility
    operation_reversibility: list[OperationReversibility]
    checksum: str
    location: str
