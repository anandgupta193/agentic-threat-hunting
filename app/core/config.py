"""Application settings, loaded from `.env` and validated once at startup."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # LLM. "anthropic" = Anthropic API key (default, for evaluators); "openrouter" = OpenRouter API key;
    # "claude_code" = local Claude Code CLI on the developer's subscription (dev only).
    llm_provider: Literal["anthropic", "openrouter", "claude_code"] = "anthropic"
    anthropic_api_key: SecretStr = SecretStr("")
    llm_model: str = "claude-sonnet-5-5"
    llm_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    llm_max_tokens: int = Field(8000, gt=0)
    llm_timeout_s: float = Field(90.0, gt=0)
    openrouter_api_key: SecretStr = SecretStr("")
    openrouter_model: str = "anthropic/claude-sonnet-5.5"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    claude_cli_path: str = "claude"
    claude_cli_max_concurrency: int = Field(2, gt=0)
    prompt_version: str = "v2"

    # Postgres (credit store)
    postgres_user: str = "threat_hunt"
    postgres_password: SecretStr = SecretStr("change-me")
    postgres_db: str = "threat_hunt"
    postgres_test_db: str = "threat_hunt_test"
    postgres_host: str = "localhost"
    postgres_port: int = Field(5433, gt=0, lt=65536)
    database_url: str | None = None
    db_pool_size: int = Field(10, gt=0)

    # Credits
    token_limit_default: int = Field(200_000, gt=0)
    max_token_limit: int = Field(10_000_000, gt=0)
    window_hours: int = Field(6, gt=0)
    max_call_tokens: int = Field(12_000, gt=0)
    pending_ttl_s: int = Field(120, gt=0)
    contended_retry_s: int = Field(5, gt=0)

    # Query engine
    dataset_csv_path: Path = Path("./data/nineteenFeaturesDf.csv")
    duckdb_path: Path = Path("./data/cloudtrail.duckdb")
    query_timeout_s: float = Field(20.0, gt=0)
    max_result_rows: int = Field(10_000, gt=0)
    max_self_correct: int = Field(2, ge=0, le=5)
    zero_row_value_check: bool = True
    schema_card_max_distinct: int = Field(200, gt=0)
    schema_card_top_n: int = Field(30, gt=0)
    duckdb_threads: int = Field(4, gt=0)
    duckdb_memory_limit: str = "2GB"

    # Confidence penalties (D34)
    confidence_penalty_retry: float = Field(0.15, ge=0, le=1)
    confidence_penalty_zero_rows: float = Field(0.20, ge=0, le=1)
    confidence_penalty_assumption: float = Field(0.05, ge=0, le=1)
    confidence_penalty_assumption_max: float = Field(0.20, ge=0, le=1)
    confidence_penalty_truncated: float = Field(0.05, ge=0, le=1)
    confidence_penalty_shape_mismatch: float = Field(0.15, ge=0, le=1)

    # Evaluation client + service
    api_base_url: str = "http://localhost:8000"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    @field_validator("window_hours")
    @classmethod
    def _window_divides_day(cls, v: int) -> int:
        # Windows are anchored to UTC midnight; only divisors of 24 give fixed boundaries (D10).
        if 24 % v != 0:
            raise ValueError(f"WINDOW_HOURS must divide 24 (got {v})")
        return v

    @model_validator(mode="after")
    def _limits_consistent(self) -> "Settings":
        if self.token_limit_default > self.max_token_limit:
            raise ValueError("TOKEN_LIMIT_DEFAULT must not exceed MAX_TOKEN_LIMIT")
        if self.confidence_penalty_assumption > self.confidence_penalty_assumption_max:
            raise ValueError("CONFIDENCE_PENALTY_ASSUMPTION must not exceed CONFIDENCE_PENALTY_ASSUMPTION_MAX")
        return self

    def _pg_url(self, database: str) -> str:
        return URL.create(
            "postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=database,
        ).render_as_string(hide_password=False)

    @property
    def db_url(self) -> str:
        return self.database_url or self._pg_url(self.postgres_db)

    @property
    def test_db_url(self) -> str:
        return self._pg_url(self.postgres_test_db)


@lru_cache
def get_settings() -> Settings:
    return Settings()
