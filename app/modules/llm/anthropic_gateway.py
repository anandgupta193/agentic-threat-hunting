"""Claude via the Anthropic API (needs ANTHROPIC_API_KEY). The default provider, and the one evaluators use.

- structured outputs (`output_config.format` = JSON schema): the reply is guaranteed schema-valid JSON.
  Forced tool use is rejected by claude-sonnet-5-5, so tool_choice is not used (D6).
- the system prompt is marked for prompt caching (it holds the large, static schema card).
- no sampling params: claude-sonnet-5-5 rejects non-default temperature; `effort` controls depth instead.
- the SDK retries 408/409/429/5xx/connection errors with backoff (`max_retries`).
"""

import json
import time

import anthropic
from anthropic.types import MessageParam, OutputConfigParam, TextBlockParam

from app.core.logging import get_logger
from app.modules.llm.types import LLMError, LLMOutputError, LLMRequest, LLMResult, LLMTimeoutError, LLMUsage

log = get_logger(__name__)


def _usage(u: anthropic.types.Usage | None) -> LLMUsage:
    if u is None:
        return LLMUsage()
    return LLMUsage(
        input_tokens=u.input_tokens or 0,
        output_tokens=u.output_tokens or 0,
        cache_creation_input_tokens=u.cache_creation_input_tokens or 0,
        cache_read_input_tokens=u.cache_read_input_tokens or 0,
    )


class AnthropicGateway:
    provider = "anthropic"

    def __init__(self, *, api_key: str, model: str, max_tokens: int, effort: str, timeout_s: float,
                 max_retries: int = 2) -> None:
        self.model = model
        self._max_tokens = max_tokens
        self._effort = effort
        self._client = anthropic.AsyncAnthropic(api_key=api_key, timeout=timeout_s, max_retries=max_retries)

    async def generate(self, request: LLMRequest) -> LLMResult:
        system: list[TextBlockParam] = [
            {"type": "text", "text": request.system, "cache_control": {"type": "ephemeral"}},
        ]
        messages: list[MessageParam] = [{"role": "user", "content": request.user}]
        output_config: OutputConfigParam = {
            "effort": self._effort,  # type: ignore[typeddict-item]  # validated by Settings (Literal)
            "format": {"type": "json_schema", "schema": request.output_schema},
        }
        t0 = time.perf_counter()
        try:
            response = await self._client.messages.create(
                model=self.model, max_tokens=self._max_tokens,
                system=system, messages=messages, output_config=output_config,
            )
        except anthropic.APITimeoutError as exc:
            log.error("llm_timeout", provider=self.provider, model=self.model)
            raise LLMTimeoutError("LLM call timed out") from exc
        except anthropic.APIStatusError as exc:
            log.error("llm_status_error", provider=self.provider, status=exc.status_code,
                      request_id=exc.request_id, message=exc.message)
            raise LLMError("LLM provider returned an error", details={"status": exc.status_code}) from exc
        except anthropic.APIConnectionError as exc:
            log.error("llm_connection_error", provider=self.provider, error=str(exc))
            raise LLMError("Could not reach the LLM provider") from exc

        latency_ms = int((time.perf_counter() - t0) * 1000)
        usage = _usage(response.usage)

        if response.stop_reason != "end_turn":
            # refusal / max_tokens: no trustworthy JSON, but the tokens were spent and must be billed.
            log.error("llm_bad_stop", provider=self.provider, stop_reason=response.stop_reason,
                      request_id=response._request_id)
            raise LLMOutputError(f"LLM stopped with reason '{response.stop_reason}'", usage=usage,
                                 details={"stop_reason": response.stop_reason})

        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            log.error("llm_invalid_json", provider=self.provider, request_id=response._request_id)
            raise LLMOutputError("LLM returned invalid JSON", usage=usage) from exc

        return LLMResult(data=data, usage=usage, model=response.model, latency_ms=latency_ms,
                         provider=self.provider, meta={"provider_request_id": response._request_id})

    async def aclose(self) -> None:
        await self._client.close()
