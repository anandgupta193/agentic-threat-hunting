import pytest

from app.modules.query_engine.validator import SqlRejected, validate


@pytest.mark.parametrize("sql", [
    "SELECT eventName, COUNT(*) AS n FROM cloudtrail WHERE errorCode IN ('AccessDenied') GROUP BY 1",
    "WITH t AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY eventName ORDER BY eventTime) AS rn FROM cloudtrail) "
    "SELECT eventName FROM t WHERE rn = 1",
])
def test_allows_selects_ctes_and_window_functions(sql: str) -> None:
    assert validate(sql, max_rows=100).sql.endswith("LIMIT 101")


@pytest.mark.parametrize(("sql", "rule"), [
    ("DROP TABLE events", "not_select"),
    ("SELECT 1; DELETE FROM cloudtrail", "multiple_statements"),
    ("SELECT * FROM events", "table"),
    ("SELECT * FROM read_csv('/etc/passwd')", "table_function"),
    ("SELECT getenv('HOME')", "function"),
    ("SELECT nope FROM cloudtrail", "column"),
])
def test_rejects_outside_allowlist(sql: str, rule: str) -> None:
    with pytest.raises(SqlRejected) as exc:
        validate(sql, max_rows=100)
    assert exc.value.rule == rule


def test_limit_capped_but_smaller_limit_kept() -> None:
    assert validate("SELECT * FROM cloudtrail LIMIT 99999", max_rows=100).sql.endswith("LIMIT 101")
    assert validate("SELECT * FROM cloudtrail LIMIT 5", max_rows=100).sql.endswith("LIMIT 5")
