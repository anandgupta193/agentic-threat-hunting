"""Request/response DTOs for POST /v1/queries (§6). Separate from ORM models and harness types."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

HYPOTHESIS_MIN, HYPOTHESIS_MAX = 5, 2000
TITLE_MAX = 200


class QueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")  # no `id`: the generator can't key off answer-key ids (D32)

    hypothesis: str = Field(min_length=HYPOTHESIS_MIN, max_length=HYPOTHESIS_MAX)
    title: str | None = Field(default=None, max_length=TITLE_MAX)
    include_results: bool = True
    max_rows: int | None = Field(default=None, ge=1)

    @field_validator("hypothesis", "title", mode="before")
    @classmethod
    def _strip(cls, v: Any) -> Any:
        return v.strip() if isinstance(v, str) else v

    @field_validator("hypothesis")
    @classmethod
    def _hypothesis_length_after_trim(cls, v: str) -> str:
        if len(v) < HYPOTHESIS_MIN:
            raise ValueError(f"hypothesis must be at least {HYPOTHESIS_MIN} characters")
        return v


class QueryDTO(BaseModel):
    sql: str | None
    dialect: str = "duckdb"


class ExplanationDTO(BaseModel):
    interpretation: str | None
    reasoning: str | None
    assumptions: list[str]
    output_kind: Literal["rows", "aggregate"] | None
    confidence: float | None
    confidence_reasons: list[str]
    result_summary: str | None


class ResultDTO(BaseModel):
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    total_rows: int
    truncated: bool


class ErrorInfoDTO(BaseModel):
    code: str
    message: str | None


class UsageDTO(BaseModel):
    tokens_used: int
    tokens_remaining: int | None   # filled once credit metering (P1) is wired in
    window_start: str | None
    resets_at: str | None


class QueryResponse(BaseModel):
    request_id: str | None
    status: Literal["succeeded", "failed"]
    query: QueryDTO
    explanation: ExplanationDTO
    result: ResultDTO | None
    error: ErrorInfoDTO | None
    trace: dict[str, Any]
    usage: UsageDTO
    prompt: dict[str, str]
