"""Async Postgres engine + session factory. `schema.sql` is the source of truth and is applied at startup (D15)."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.logging import get_logger

log = get_logger(__name__)

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schema.sql"


class Database:
    def __init__(self, url: str, pool_size: int = 10) -> None:
        self.engine: AsyncEngine = create_async_engine(
            url, pool_size=pool_size, max_overflow=pool_size, pool_pre_ping=True,
        )
        self.sessionmaker: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self.engine, expire_on_commit=False,
        )

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.sessionmaker() as session:
            yield session

    async def apply_schema(self, path: Path = SCHEMA_PATH) -> None:
        """Run schema.sql (idempotent: every statement uses IF NOT EXISTS)."""
        ddl = await asyncio.to_thread(_read_text, path)
        statements = [ln for ln in ddl.splitlines() if ln.strip() and not ln.lstrip().startswith("--")]
        if not statements:
            log.warning("schema_empty", path=str(path))
            return
        async with self.engine.begin() as conn:
            # asyncpg runs a multi-statement script only through its simple-query protocol.
            raw = await conn.get_raw_connection()
            await raw.driver_connection.execute(ddl)  # type: ignore[union-attr]
        log.info("schema_applied", path=str(path))

    async def ping(self) -> bool:
        try:
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception as exc:
            log.error("db_ping_failed", exc_type=type(exc).__name__, error=str(exc))
            return False

    async def dispose(self) -> None:
        await self.engine.dispose()


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""
