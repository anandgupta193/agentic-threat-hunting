"""Per-request trace: one entry per LLM attempt plus time spent per stage. Returned in the API response."""

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class AttemptTrace:
    attempt: int
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    outcome: str = "pending"  # ok | sql_rejected | execution_error | timeout | zero_rows_missing_value
    #                           | bad_output | llm_error | credits_exhausted
    error: str | None = None
    sql: str | None = None


@dataclass(slots=True)
class Trace:
    attempts: list[AttemptTrace] = field(default_factory=list)
    stage_ms: dict[str, int] = field(default_factory=dict)
    started: float = field(default_factory=time.perf_counter)

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        t0 = time.perf_counter()
        try:
            yield
        finally:
            self.stage_ms[name] = self.stage_ms.get(name, 0) + int((time.perf_counter() - t0) * 1000)

    @property
    def tokens_used(self) -> int:
        return sum(a.input_tokens + a.output_tokens for a in self.attempts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempts": [{k: v for k, v in asdict(a).items() if k != "sql"} for a in self.attempts],
            "stage_ms": dict(self.stage_ms),
            "total_ms": int((time.perf_counter() - self.started) * 1000),
        }
