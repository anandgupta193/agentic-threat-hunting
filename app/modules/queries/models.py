"""ORM mirror of the `query_requests` audit table in schema.sql. Named `QueryRecord` to keep it apart from the
`QueryRequest` DTO."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import CHAR, DateTime, Integer, Numeric, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class QueryRecord(Base):
    __tablename__ = "query_requests"

    request_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64))
    hypothesis: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))
    error_code: Mapped[str | None] = mapped_column(String(40))
    final_sql: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    row_count: Mapped[int | None] = mapped_column(Integer)
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0)
    prompt_version: Mapped[str | None] = mapped_column(String(16))
    prompt_hash: Mapped[str | None] = mapped_column(CHAR(12))
    model: Mapped[str | None] = mapped_column(String(64))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
