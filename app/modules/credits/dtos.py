"""Response DTOs for GET /v1/users/{id}/credits and /usage (§6)."""

from datetime import datetime

from pydantic import BaseModel


class CreditsDTO(BaseModel):
    user_id: str
    token_limit: int
    tokens_used: int
    tokens_remaining: int
    in_flight: int
    window_start: datetime
    resets_at: datetime


class UsageCallDTO(BaseModel):
    request_id: str
    attempt: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    status: str
    model: str | None
    created_at: datetime


class UsageTotalsDTO(BaseModel):
    calls: int
    input_tokens: int
    output_tokens: int
    total_tokens: int


class UsageDTO(BaseModel):
    user_id: str
    window_start: datetime
    resets_at: datetime
    totals: UsageTotalsDTO
    calls: list[UsageCallDTO]
