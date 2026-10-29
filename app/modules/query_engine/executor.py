"""Locked-down DuckDB executor (D41, layer 2). Holds even if the validator has a gap.

- one read-only connection opened at startup, external access off, configuration locked
- a cursor per query, run in a worker thread so the event loop never blocks
- per-query timeout through `interrupt()`; results capped at `max_rows`, truncation reported
"""

import asyncio
import json
import time
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

from app.core.logging import get_logger
from app.modules.query_engine.allowlist import COLUMN_BY_LOWER
from app.modules.query_engine.dataset import TABLE
from app.modules.query_engine.validator import ValidatedSql

log = get_logger(__name__)


class QueryTimeout(Exception):
    pass


class QueryFailed(Exception):
    pass


@dataclass(frozen=True, slots=True)
class QueryResult:
    columns: list[str]
    rows: list[list[Any]]
    row_count: int    # rows returned (≤ max_rows)
    total_rows: int   # rows the query produces
    truncated: bool
    elapsed_ms: int


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


class DuckDBExecutor:
    def __init__(self, path: Path, *, threads: int, memory_limit: str, timeout_s: float) -> None:
        if not path.exists():
            raise FileNotFoundError(f"{path} not found; run `make prepare-data` (or the data-prep service)")
        self._timeout_s = timeout_s
        self._con = duckdb.connect(str(path), read_only=True, config={
            "enable_external_access": False,
            "autoinstall_known_extensions": False,
            "autoload_known_extensions": False,
            "threads": threads,
            "memory_limit": memory_limit,
            "lock_configuration": True,
        })

    def meta(self) -> dict[str, str]:
        return dict(self._con.cursor().execute("SELECT key, value FROM _meta").fetchall())

    def schema_card(self) -> dict[str, Any]:
        card: dict[str, Any] = json.loads(self.meta()["schema_card"])
        return card

    def ping(self) -> bool:
        try:
            self._con.cursor().execute("SELECT 1").fetchone()
            return True
        except duckdb.Error as exc:
            log.error("duckdb_ping_failed", error=str(exc))
            return False

    async def run(self, validated: ValidatedSql, *, max_rows: int, timeout_s: float | None = None) -> QueryResult:
        return await self._in_thread(self._run_sync, validated, max_rows, timeout_s=timeout_s)

    async def value_exists(self, column: str, value: str, *, like: bool, case_insensitive: bool) -> bool:
        """Trusted, parameterised existence probe used by the zero-row value check (never LLM SQL)."""
        col = f'"{COLUMN_BY_LOWER[column.lower()]}"'
        if like:
            predicate = f"{col} {'ILIKE' if case_insensitive else 'LIKE'} ?"
        else:
            predicate = f"lower({col}) = lower(?)" if case_insensitive else f"{col} = ?"
        sql = f"SELECT 1 FROM {TABLE} WHERE {predicate} LIMIT 1"
        return bool(await self._in_thread(lambda cur: cur.execute(sql, [value]).fetchone() is not None))

    async def _in_thread(self, fn: Any, *args: Any, timeout_s: float | None = None) -> Any:
        timeout = timeout_s or self._timeout_s
        cursor = self._con.cursor()
        loop = asyncio.get_running_loop()
        timer = loop.call_later(timeout, cursor.interrupt)
        try:
            return await asyncio.to_thread(fn, cursor, *args)
        except duckdb.InterruptException as exc:
            log.error("duckdb_timeout", timeout_s=timeout)
            raise QueryTimeout(f"Query exceeded {timeout:g}s; simplify it or aggregate earlier") from exc
        except duckdb.Error as exc:
            log.error("duckdb_error", exc_type=type(exc).__name__, error=str(exc)[:300])
            raise QueryFailed(str(exc).split("\n")[0]) from exc
        finally:
            timer.cancel()
            cursor.close()

    @staticmethod
    def _run_sync(cursor: duckdb.DuckDBPyConnection, validated: ValidatedSql, max_rows: int) -> QueryResult:
        t0 = time.perf_counter()
        cursor.execute(validated.sql)
        columns = [d[0] for d in cursor.description or []]
        fetched = cursor.fetchmany(max_rows + 1)
        truncated = len(fetched) > max_rows
        rows = [[_jsonable(v) for v in r] for r in fetched[:max_rows]]
        total = len(rows)
        if truncated:
            counted = cursor.execute(f"SELECT COUNT(*) FROM ({validated.count_sql}) AS _q").fetchone()
            total = int(counted[0]) if counted else len(rows)
        return QueryResult(columns=columns, rows=rows, row_count=len(rows), total_rows=total, truncated=truncated,
                           elapsed_ms=int((time.perf_counter() - t0) * 1000))

    def close(self) -> None:
        self._con.close()
