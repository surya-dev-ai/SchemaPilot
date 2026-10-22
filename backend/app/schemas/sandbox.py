"""Sandbox run records. These models do not describe a target deployment."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

SandboxResult = Literal["passed", "failed", "rejected"]
CheckStatus = Literal["passed", "failed", "not_run"]


class SandboxCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    status: CheckStatus
    detail: str


class SandboxRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: bool


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
