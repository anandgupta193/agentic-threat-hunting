"""Credit metering (§7.3): admit before every LLM call, finalize after it, and read-side views.

Admission is one short transaction holding this user's row lock; the LLM call itself happens outside it.
"""

from datetime import timedelta

from app.core.clock import Clock
from app.core.config import Settings
from app.core.errors import CreditsContended, CreditsExhausted
from app.core.logging import get_logger
from app.db.engine import Database
from app.modules.credits.dtos import CreditsDTO, UsageCallDTO, UsageDTO, UsageTotalsDTO
from app.modules.credits.policy import Admission, decide_admission, remaining, retry_after_seconds, window_bounds
from app.modules.credits.repository import CreditRepository
from app.modules.llm.types import LLMUsage
from app.modules.users.service import UserNotFound

log = get_logger(__name__)


class CreditService:
    def __init__(self, db: Database, settings: Settings, clock: Clock) -> None:
        self._db = db
        self._settings = settings
        self._clock = clock
        self._repo = CreditRepository()

    async def admit(self, user_id: str, request_id: str, attempt: int) -> int:
        """Reserve one LLM call. Returns the pending `token_usage` id, or raises a 429 error."""
        now = self._clock.now()
        window = window_bounds(now, self._settings.window_hours)
        usage_id: int | None = None
        async with self._db.session() as s, s.begin():
            user = await self._repo.lock_user(s, user_id)
            if user is None:
                raise UserNotFound("User not found", details={"user_id": user_id})
            older_than = now - timedelta(seconds=self._settings.pending_ttl_s)
            expired = await self._repo.expire_stale_pending(s, user_id, older_than=older_than, now=now)
            if expired:
                log.warning("credit_claims_expired", count=expired)
            totals = await self._repo.window_totals(s, user_id, window.start)
            decision = decide_admission(user.token_limit, totals.used, totals.in_flight,
                                        self._settings.max_call_tokens)
            if decision is Admission.ADMIT:
                usage_id = await self._repo.insert_pending(s, user_id=user_id, request_id=request_id,
                                                           attempt=attempt, window_start=window.start, now=now)
        # Committed (the lock is released, and any expirations persist even when the call is denied).
        left = remaining(user.token_limit, totals.used)
        log.info("credit_admission", decision=decision.value, attempt=attempt, tokens_used=totals.used,
                 tokens_remaining=left, in_flight=totals.in_flight, token_limit=user.token_limit)
        if decision is Admission.EXHAUSTED:
            resets_at = f"{window.resets_at:%Y-%m-%dT%H:%M:%SZ}"
            raise CreditsExhausted("Token budget exhausted for this window",
                                   retry_after_s=retry_after_seconds(now, window.resets_at),
                                   details={"tokens_remaining": 0, "resets_at": resets_at})
        if decision is Admission.CONTENDED:
            raise CreditsContended("Remaining credits are reserved by calls in flight; retry shortly",
                                   retry_after_s=self._settings.contended_retry_s,
                                   details={"tokens_remaining": left, "in_flight": totals.in_flight})
        assert usage_id is not None
        return usage_id

    async def finalize(self, usage_id: int, usage: LLMUsage | None, model: str | None) -> None:
        """Record the actual tokens. No usage reported (provider error / timeout) → `failed` with 0 tokens."""
        status = "completed" if usage is not None else "failed"
        input_tokens = usage.billable_input_tokens if usage else 0
        output_tokens = usage.output_tokens if usage else 0
        try:
            async with self._db.session() as s, s.begin():
                found = await self._repo.finalize(s, usage_id, input_tokens=input_tokens, output_tokens=output_tokens,
                                                  status=status, model=model, now=self._clock.now())
        except Exception as exc:
            # The pending claim expires after PENDING_TTL_S, so a lost write frees the credits rather than locking them.
            log.error("credit_finalize_failed", usage_id=usage_id, exc_type=type(exc).__name__, error=str(exc))
            raise
        if not found:
            log.error("credit_finalize_missing_claim", usage_id=usage_id)
        log.info("credit_finalized", usage_id=usage_id, status=status, input_tokens=input_tokens,
                 output_tokens=output_tokens)

    async def get_credits(self, user_id: str) -> CreditsDTO:
        window = window_bounds(self._clock.now(), self._settings.window_hours)
        async with self._db.session() as s:
            user = await self._repo.get_user(s, user_id)
            if user is None:
                raise UserNotFound("User not found", details={"user_id": user_id})
            totals = await self._repo.window_totals(s, user_id, window.start)
        return CreditsDTO(user_id=user_id, token_limit=user.token_limit, tokens_used=totals.used,
                          tokens_remaining=remaining(user.token_limit, totals.used), in_flight=totals.in_flight,
                          window_start=window.start, resets_at=window.resets_at)

    async def get_usage(self, user_id: str) -> UsageDTO:
        window = window_bounds(self._clock.now(), self._settings.window_hours)
        async with self._db.session() as s:
            if await self._repo.get_user(s, user_id) is None:
                raise UserNotFound("User not found", details={"user_id": user_id})
            rows = await self._repo.list_calls(s, user_id, window.start)
        calls = [UsageCallDTO(request_id=r.request_id, attempt=r.attempt, input_tokens=r.input_tokens,
                              output_tokens=r.output_tokens, total_tokens=r.input_tokens + r.output_tokens,
                              status=r.status, model=r.model, created_at=r.created_at) for r in rows]
        totals = UsageTotalsDTO(calls=len(calls), input_tokens=sum(c.input_tokens for c in calls),
                                output_tokens=sum(c.output_tokens for c in calls),
                                total_tokens=sum(c.total_tokens for c in calls))
        return UsageDTO(user_id=user_id, window_start=window.start, resets_at=window.resets_at, totals=totals,
                        calls=calls)
