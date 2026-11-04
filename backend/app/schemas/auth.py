"""Safe authentication status returned to the frontend."""

from pydantic import BaseModel, ConfigDict


class AuthenticatedUser(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str | None = None
    display_name: str | None = None
    roles: list[str]


class AuthSessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    authenticated: bool
    user: AuthenticatedUser | None = None
    csrf_token: str | None = None
    can_access_team_workspace: bool = False
