"""Health response. It reports configuration, not a guessed database connection."""

from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str
    api_version: Literal["v1"]
    target_execution_enabled: bool
    migrations_on_startup: Literal[False] = False
    database_connectivity: Literal["not_checked"] = "not_checked"
    app_database_configured: bool
    sandbox_database_configured: bool
    target_database_configured: bool
    llm_enabled: bool = False
    llm_configured: bool = False
    llm_provider: str = "none"
    llm_model: str | None = None
    authentication_available: bool = False
    phase: str = Field(default="1")
