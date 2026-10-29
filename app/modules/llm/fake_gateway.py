"""Scripted gateway for tests: returns queued results (or raises queued errors) and counts calls."""

import asyncio
from collections import deque

from app.modules.llm.types import LLMRequest, LLMResult, LLMUsage


class FakeGateway:
    provider = "fake"

    def __init__(self, model: str = "fake-model") -> None:
        self.model = model
        self.calls: list[LLMRequest] = []
        self.delay_s = 0.0  # > 0 keeps calls in flight, so concurrent admissions overlap in tests
        self._script: deque[LLMResult | Exception] = deque()

    def push(self, data: dict, *, input_tokens: int = 1000, output_tokens: int = 200) -> None:
        usage = LLMUsage(input_tokens=input_tokens, output_tokens=output_tokens)
        self._script.append(LLMResult(data=data, usage=usage, model=self.model, latency_ms=1, provider=self.provider))

    def push_error(self, exc: Exception) -> None:
        self._script.append(exc)

    @property
    def call_count(self) -> int:
        return len(self.calls)

    async def generate(self, request: LLMRequest) -> LLMResult:
        self.calls.append(request)
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        if not self._script:
            raise AssertionError("FakeGateway: no scripted response left")
        item = self._script.popleft()
        if isinstance(item, Exception):
            raise item
        return item

    async def aclose(self) -> None:
        return None
