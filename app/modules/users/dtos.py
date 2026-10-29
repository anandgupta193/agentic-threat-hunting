"""Request/response DTOs for POST /v1/users (§6)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.common.guards import USER_ID_PATTERN


class CreateUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str | None = Field(default=None, pattern=USER_ID_PATTERN.pattern)  # generated when omitted
    token_limit: int | None = Field(default=None, ge=1)                         # upper bound from config


class UserDTO(BaseModel):
    user_id: str
    token_limit: int
    created_at: datetime
