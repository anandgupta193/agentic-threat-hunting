"""Provider-neutral LLM contract: a JSON schema goes in, schema-valid JSON + token usage come out.

Every gateway implements `LLMGateway`, so the harness never knows which provider is behind it.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.core.errors import GatewayTimeoutError, UpstreamError


@dataclass(frozen=True, slots=True)
class LLMRequest:
    system: str
    user: str
    output_schema: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LLMUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    @property
    def billable_input_tokens(self) -> int:
        # D9: cached input counts toward credits in full ("count what the LLM reports").
        return self.input_tokens + self.cache_creation_input_tokens + self.cache_read_input_tokens

    @property
    def billable_total(self) -> int:
        return self.billable_input_tokens + self.output_tokens


@dataclass(frozen=True, slots=True)
class LLMResult:
    data: dict[str, Any]
    usage: LLMUsage
    model: str
    latency_ms: int
    provider: str
    meta: dict[str, Any] = field(default_factory=dict)


class LLMGateway(Protocol):
    provider: str
    model: str

    async def generate(self, request: LLMRequest) -> LLMResult: ...

    async def aclose(self) -> None: ...


class LLMError(UpstreamError):
    """Provider call failed. `usage` is set when the provider still reported tokens (so they can be billed)."""

    code = "LLM_ERROR"

    def __init__(self, message: str, *, usage: LLMUsage | None = None, details: dict[str, Any] | None = None):
        super().__init__(message, details=details)
        self.usage = usage


class LLMOutputError(LLMError):
    """The provider answered, but not with schema-valid JSON (refusal, truncation, malformed output)."""

    code = "LLM_BAD_OUTPUT"


class LLMTimeoutError(GatewayTimeoutError):
    code = "LLM_TIMEOUT"
    usage: LLMUsage | None = None
