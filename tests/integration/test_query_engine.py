"""P2: locked-down executor, truncation and the zero-row value check, on the tiny fixture dataset."""

from collections.abc import Iterator
from pathlib import Path

import duckdb
import pytest

from app.modules.query_engine.executor import DuckDBExecutor
from app.modules.query_engine.validator import validate
from app.modules.query_engine.value_check import ValueChecker


@pytest.fixture
def executor(duckdb_path: Path) -> Iterator[DuckDBExecutor]:
    ex = DuckDBExecutor(duckdb_path, threads=1, memory_limit="256MB", timeout_s=5)
    yield ex
    ex.close()


@pytest.mark.parametrize("sql", [
    "SELECT * FROM read_csv('/etc/hosts')", "COPY (SELECT 1) TO '/tmp/out.csv'", "SET threads = 8",
    "CREATE TABLE x (a INT)",
])
def test_lockdown_blocks_even_without_validator(executor: DuckDBExecutor, sql: str) -> None:
    with pytest.raises(duckdb.Error):
        executor._con.cursor().execute(sql)


async def test_result_truncated_with_true_total(executor: DuckDBExecutor) -> None:
    result = await executor.run(validate("SELECT * FROM cloudtrail", max_rows=2), max_rows=2)
    assert (result.row_count, result.total_rows, result.truncated) == (2, 5, True)


async def test_value_check_suggests_real_value(executor: DuckDBExecutor) -> None:
    checker = ValueChecker(executor.schema_card(), executor)
    missing = await checker.missing_values(
        validate("SELECT * FROM cloudtrail WHERE errorCode = 'UnauthorizedOperation'", max_rows=10).ast)
    assert [(m.column, m.literal) for m in missing] == [("errorCode", "UnauthorizedOperation")]
    assert missing[0].suggestions[0] == "Client.UnauthorizedOperation"


async def test_value_check_accepts_existing_values(executor: DuckDBExecutor) -> None:
    checker = ValueChecker(executor.schema_card(), executor)
    sql = "SELECT * FROM cloudtrail WHERE userIdentitytype = 'Root' AND userAgent ILIKE '%KALI%'"
    assert await checker.missing_values(validate(sql, max_rows=10).ast) == []
