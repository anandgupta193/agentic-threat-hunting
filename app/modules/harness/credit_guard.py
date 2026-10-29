"""The harness's view of credits: admit before every LLM attempt, finalize after it (D4, D12).

Credit rules live in the credits module, not here. `admit` raises `CreditsExhausted` / `CreditsContended`
when the call must not happen. Until the Postgres-backed guard lands (P1), `UnmeteredCreditGuard` admits
every call and records nothing.
"""

from dataclasses import dataclass
from typing import Any, Protocol

from app.modules.llm.types import LLMUsage


@dataclass(frozen=True, slots=True)
class Claim:
    attempt: int
    handle: Any = None  # implementation-specific (e.g. the pending token_usage row id)


class CreditGuard(Protocol):
    async def admit(self, attempt: int) -> Claim: ...

    async def finalize(self, claim: Claim, usage: LLMUsage | None, model: str | None) -> None:
        """Record the actual tokens; `usage=None` means the call failed without reporting any."""
        ...


class UnmeteredCreditGuard:
    async def admit(self, attempt: int) -> Claim:
        return Claim(attempt=attempt)

    async def finalize(self, claim: Claim, usage: LLMUsage | None, model: str | None) -> None:
        return None
