"""All SQL for the `query_requests` audit trail. Callers own the session and the transaction."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import insert, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.queries.models import QueryRecord


@dataclass(slots=True)
class QueryCompletion:
    status: str                       # succeeded | failed | rejected
    error_code: str | None = None
    final_sql: str | None = None
    confidence: float | None = None
    row_count: int | None = None
    attempts: int = 0
    prompt_version: str | None = None
    prompt_hash: str | None = None
    model: str | None = None
    latency_ms: int | None = None


class QueryRepository:
    async def start(self, session: AsyncSession, *, request_id: str, user_id: str, hypothesis: str,
                    now: datetime) -> None:
        await session.execute(insert(QueryRecord).values(
            request_id=request_id, user_id=user_id, hypothesis=hypothesis, status="in_progress", created_at=now,
        ))

    async def complete(self, session: AsyncSession, request_id: str, c: QueryCompletion, now: datetime) -> None:
        await session.execute(update(QueryRecord).where(QueryRecord.request_id == request_id).values(
            status=c.status, error_code=c.error_code, final_sql=c.final_sql,
            confidence=Decimal(str(c.confidence)) if c.confidence is not None else None,
            row_count=c.row_count, attempts=c.attempts, prompt_version=c.prompt_version,
            prompt_hash=c.prompt_hash, model=c.model, latency_ms=c.latency_ms, completed_at=now,
        ))
