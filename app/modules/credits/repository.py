"""All SQL for credits. Callers own the session and the transaction (admission is one short transaction)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.credits.models import TokenUsage
from app.modules.users.models import User


@dataclass(frozen=True, slots=True)
class WindowTotals:
    used: int
    in_flight: int


class CreditRepository:
    async def lock_user(self, session: AsyncSession, user_id: str) -> User | None:
        """Serialise this user's admissions. FOR NO KEY UPDATE (not FOR UPDATE): admissions still exclude each
        other, but the FK checks of concurrent `query_requests` inserts (FOR KEY SHARE) are not blocked."""
        stmt = select(User).where(User.user_id == user_id).with_for_update(key_share=True)
        return (await session.execute(stmt)).scalar_one_or_none()

    async def get_user(self, session: AsyncSession, user_id: str) -> User | None:
        return await session.get(User, user_id)

    async def expire_stale_pending(self, session: AsyncSession, user_id: str, older_than: datetime,
                                   now: datetime) -> int:
        """Crash recovery: a claim whose call never finalized stops reserving credits after PENDING_TTL_S."""
        stmt = (update(TokenUsage)
                .where(TokenUsage.user_id == user_id, TokenUsage.status == "pending",
                       TokenUsage.created_at < older_than)
                .values(status="expired", completed_at=now))
        result = await session.execute(stmt)
        return int(result.rowcount or 0)  # type: ignore[attr-defined]

    async def window_totals(self, session: AsyncSession, user_id: str, window_start: datetime) -> WindowTotals:
        """The hot query (§5): an index-only scan of ix_tu_user_window."""
        stmt = select(
            func.coalesce(func.sum(TokenUsage.input_tokens + TokenUsage.output_tokens), 0),
            func.count().filter(TokenUsage.status == "pending"),
        ).where(TokenUsage.user_id == user_id, TokenUsage.window_start == window_start)
        used, in_flight = (await session.execute(stmt)).one()
        return WindowTotals(used=int(used), in_flight=int(in_flight))

    async def insert_pending(self, session: AsyncSession, *, user_id: str, request_id: str, attempt: int,
                             window_start: datetime, now: datetime) -> int:
        stmt = insert(TokenUsage).values(
            user_id=user_id, request_id=request_id, attempt=attempt, window_start=window_start,
            status="pending", created_at=now,
        ).returning(TokenUsage.id)
        return int((await session.execute(stmt)).scalar_one())

    async def finalize(self, session: AsyncSession, usage_id: int, *, input_tokens: int, output_tokens: int,
                       status: str, model: str | None, now: datetime) -> bool:
        """Applies to an `expired` claim too: a late call is still billed in full."""
        stmt = (update(TokenUsage).where(TokenUsage.id == usage_id)
                .values(input_tokens=input_tokens, output_tokens=output_tokens, status=status, model=model,
                        completed_at=now))
        result = await session.execute(stmt)
        return bool(result.rowcount)  # type: ignore[attr-defined]

    async def list_calls(self, session: AsyncSession, user_id: str, window_start: datetime) -> Sequence[TokenUsage]:
        stmt = (select(TokenUsage)
                .where(TokenUsage.user_id == user_id, TokenUsage.window_start == window_start)
                .order_by(TokenUsage.id))
        return (await session.execute(stmt)).scalars().all()
