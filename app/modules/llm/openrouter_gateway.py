"""Claude (or another model) through OpenRouter's chat-completions API (needs OPENROUTER_API_KEY).

- structured outputs via `response_format` = strict JSON schema; `provider.require_parameters` makes
  OpenRouter route only to an upstream that supports it
- the system prompt is marked with `cache_control`, which OpenRouter passes to Anthropic for prompt caching
- `reasoning.effort` mirrors LLM_EFFORT; no sampling params (Sonnet 5.5 rejects them)
- usage is in OpenAI form: `prompt_tokens` already includes cached tokens, so it is split into
  uncached + cache-read to keep `billable_total` = everything the provider reported (D9)
- 429 / 5xx / connection errors are retried with exponential backoff
"""

import asyncio
import json
import time
from typing import Any

import httpx

from app.core.logging import get_logger
from app.modules.llm.types import LLMError, LLMOutputError, LLMRequest, LLMResult, LLMTimeoutError, LLMUsage

log = get_logger(__name__)

RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504}
BACKOFF_BASE_S = 1.0
MAX_ERROR_LOG_CHARS = 500


def _usage(raw: dict[str, Any] | None) -> LLMUsage:
    raw = raw or {}
    prompt = int(raw.get("prompt_tokens") or 0)
    details = raw.get("prompt_tokens_details") or {}
    cached = int(details.get("cached_tokens") or 0)
    cache_write = int(details.get("cache_write_tokens") or 0)
    return LLMUsage(
        input_tokens=max(0, prompt - cached - cache_write),
        output_tokens=int(raw.get("completion_tokens") or 0),
        cache_creation_input_tokens=cache_write,
        cache_read_input_tokens=cached,
    )


class OpenRouterGateway:
    provider = "openrouter"

    def __init__(self, *, api_key: str, model: str, base_url: str, max_tokens: int, effort: str,
                 timeout_s: float, max_retries: int = 2) -> None:
        self.model = model
        self._max_tokens = max_tokens
        self._effort = effort
        self._max_retries = max_retries
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_s,
            headers={"Authorization": f"Bearer {api_key}", "X-Title": "agentic-threat-hunting"},
        )

    def _body(self, request: LLMRequest) -> dict[str, Any]:
        return {
            "model": self.model,
            "max_tokens": self._max_tokens,
            "messages": [
                {"role": "system", "content": [
                    {"type": "text", "text": request.system, "cache_control": {"type": "ephemeral"}},
                ]},
                {"role": "user", "content": request.user},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "output", "strict": True, "schema": request.output_schema},
            },
            "reasoning": {"effort": self._effort},
            "provider": {"require_parameters": True},
        }

    async def _post(self, body: dict[str, Any]) -> httpx.Response:
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.post("/chat/completions", json=body)
            except httpx.TimeoutException as exc:
                log.error("llm_timeout", provider=self.provider, model=self.model, attempt=attempt + 1)
                if attempt == self._max_retries:
                    raise LLMTimeoutError("LLM call timed out") from exc
            except httpx.TransportError as exc:
                log.error("llm_connection_error", provider=self.provider, attempt=attempt + 1, error=str(exc))
                if attempt == self._max_retries:
                    raise LLMError("Could not reach the LLM provider") from exc
            else:
                if response.status_code not in RETRYABLE_STATUS or attempt == self._max_retries:
                    return response
                log.warning("llm_retryable_status", provider=self.provider, status=response.status_code,
                            attempt=attempt + 1)
            await asyncio.sleep(BACKOFF_BASE_S * 2 ** attempt)
        raise AssertionError("unreachable")

    async def generate(self, request: LLMRequest) -> LLMResult:
        t0 = time.perf_counter()
        response = await self._post(self._body(request))
        latency_ms = int((time.perf_counter() - t0) * 1000)

        if response.status_code >= 400:
            log.error("llm_status_error", provider=self.provider, status=response.status_code,
                      body=response.text[:MAX_ERROR_LOG_CHARS])
            raise LLMError("LLM provider returned an error", details={"status": response.status_code})

        payload = response.json()
        usage = _usage(payload.get("usage"))
        if "error" in payload:  # OpenRouter can return 200 with an upstream error object
            log.error("llm_upstream_error", provider=self.provider,
                      error=str(payload["error"])[:MAX_ERROR_LOG_CHARS])
            raise LLMError("LLM upstream returned an error", usage=usage)

        choice = (payload.get("choices") or [{}])[0]
        finish = choice.get("finish_reason")
        if finish != "stop":
            log.error("llm_bad_stop", provider=self.provider, finish_reason=finish, id=payload.get("id"))
            raise LLMOutputError(f"LLM stopped with reason '{finish}'", usage=usage,
                                 details={"finish_reason": finish})
        try:
            data = json.loads((choice.get("message") or {}).get("content") or "")
        except json.JSONDecodeError as exc:
            log.error("llm_invalid_json", provider=self.provider, id=payload.get("id"))
            raise LLMOutputError("LLM returned invalid JSON", usage=usage) from exc

        return LLMResult(data=data, usage=usage, model=payload.get("model", self.model), latency_ms=latency_ms,
                         provider=self.provider,
                         meta={"provider_request_id": payload.get("id"), "upstream": payload.get("provider")})

    async def aclose(self) -> None:
        await self._client.aclose()
