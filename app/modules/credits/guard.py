"""The Postgres-backed `CreditGuard` the harness calls around every LLM attempt (one per request)."""

from app.modules.credits.service import CreditService
from app.modules.harness.credit_guard import Claim
from app.modules.llm.types import LLMUsage


class MeteredCreditGuard:
    def __init__(self, credits: CreditService, user_id: str, request_id: str) -> None:
        self._credits = credits
        self._user_id = user_id
        self._request_id = request_id

    async def admit(self, attempt: int) -> Claim:
        return Claim(attempt=attempt, handle=await self._credits.admit(self._user_id, self._request_id, attempt))

    async def finalize(self, claim: Claim, usage: LLMUsage | None, model: str | None) -> None:
        await self._credits.finalize(claim.handle, usage, model)
