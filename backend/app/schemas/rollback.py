"""Rollback evidence. These models do not approve or apply a target migration."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.schemas.sandbox import SandboxCheck, SandboxRun

RollbackStatus = Literal[
    "exact_restoration",
    "partial_restoration",
    "failed",
    "not_verified",
]


class BaselineEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_fingerprint: str
    tables: list[str]
    row_counts: dict[str, int]
    emails: list[str]


class RollbackReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    migration_id: str
    artifact_checksum: str
    source_id: str
    schema_fingerprint: str
    sandbox_database: str
    sandbox_user: str
    postgres_version: str
    started_at: str
    finished_at: str
    status: RollbackStatus
    upgrade: SandboxRun | None = None
    baseline: BaselineEvidence | None = None
    observed_fingerprint: str | None = None
    downgrade_executed: bool
    schema_matches_baseline: bool | None = None
    data_checks: list[SandboxCheck]
    data_loss_limitations: list[str]
    error: str | None = None
