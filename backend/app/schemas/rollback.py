"""Rollback and sandbox checkpoint evidence; neither approves nor applies targets."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.sandbox import SandboxCheck, SandboxRun

RollbackStatus = Literal[
    "exact_restoration",
    "partial_restoration",
    "failed",
    "not_verified",
]

BackupStatus = Literal["verified", "failed", "unavailable", "not_created"]
SnapshotRestoreStatus = Literal[
    "restore_verified",
    "restore_partially_verified",
    "restore_failed",
    "verification_incomplete",
    "backup_unavailable",
    "not_attempted",
]


class BaselineEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_fingerprint: str
    tables: list[str]
    row_counts: dict[str, int]
    emails: list[str]


class SnapshotRecoveryReport(BaseModel):
    """Evidence for a retained PostgreSQL template-clone checkpoint."""

    model_config = ConfigDict(extra="forbid")

    checkpoint_id: str | None = None
    captured_at: str | None = None
    backup_status: BackupStatus = "not_created"
    restore_status: SnapshotRestoreStatus = "not_attempted"
    baseline_schema_fingerprint: str | None = None
    restored_schema_fingerprint: str | None = None
    baseline_data_fingerprint: str | None = None
    restored_data_fingerprint: str | None = None
    schema_match: bool | None = None
    data_match: bool | None = None
    verification_checks: list[SandboxCheck] = Field(default_factory=list)
    checkpoint_retained: bool = False
    error: str | None = None


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
    snapshot_recovery: SnapshotRecoveryReport | None = None
    preexisting_sandbox_recovery: SnapshotRecoveryReport | None = None
    snapshot_session_id: str | None = None
