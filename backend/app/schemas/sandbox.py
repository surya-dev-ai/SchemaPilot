"""Sandbox run records. These models do not describe a target deployment."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SandboxResult = Literal["passed", "failed", "rejected"]
CheckStatus = Literal["passed", "failed", "not_run"]
CheckpointSessionState = Literal["ready", "running", "completed", "recovery_required"]


class SandboxCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    status: CheckStatus
    detail: str


class SandboxRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: bool
    snapshot_session_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")


class SandboxRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    migration_id: str
    source_id: str
    schema_fingerprint: str
    artifact_checksum: str
    sandbox_database: str
    sandbox_user: str
    postgres_version: str
    started_at: str
    finished_at: str
    result: SandboxResult
    upgrade_applied: bool
    restored: bool
    cleaned_up: bool
    checks: list[SandboxCheck]
    observed_tables: list[str]
    error: str | None = None
    snapshot_session_id: str | None = None
    pre_migration_snapshot_verified: bool = False


class SandboxCheckpointSessionStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active: bool
    migration_id: str | None = None
    snapshot_session_id: str | None = None
    state: CheckpointSessionState | None = None
    checkpoint_verified: bool = False
    restore_status: str | None = None
    validation_run: SandboxRun | None = None
    baseline_evidence: dict[str, object] | None = None
    downgrade_report: dict[str, object] | None = None
    error: str | None = None
