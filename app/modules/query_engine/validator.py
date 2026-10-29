"""Allowlist SQL validator (D41, layer 1). Parses with sqlglot and fails closed.

Rules: exactly one read-only query (SELECT / set operation, CTEs allowed); reads only `cloudtrail` and its own
CTEs; references only the 19 columns or aliases the query defines; calls only allowlisted functions; the
outer LIMIT is injected or capped. Each rejection carries a rule id and an LLM-friendly reason, which the
harness feeds back for self-correction.
"""

from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from app.modules.query_engine.allowlist import ALLOWED_COLUMNS, ALLOWED_FUNCTIONS, ALLOWED_TABLES
from app.modules.query_engine.dataset import COLUMNS, TABLE

DIALECT = "duckdb"
# AND/OR/NOT and comparison operators are Func subclasses in sqlglot; they are operators, not functions.
_OPERATOR_TYPES = (exp.Connector, exp.Binary, exp.Unary, exp.Predicate)


class SqlRejected(Exception):
    def __init__(self, rule: str, reason: str) -> None:
        super().__init__(reason)
        self.rule = rule
        self.reason = reason


@dataclass(frozen=True, slots=True)
class ValidatedSql:
    sql: str        # what is executed: normalised, outer LIMIT capped at max_rows + 1
    count_sql: str  # the query as written (no cap), used to report the true row count when truncated
    ast: exp.Query


def _defined_names(tree: exp.Expr) -> tuple[set[str], set[str]]:
    """CTE / subquery aliases (usable as table names) and every alias name (usable as a column)."""
    relations: set[str] = set()
    aliases: set[str] = set()
    for ta in tree.find_all(exp.TableAlias):  # covers CTE names, subquery and table aliases
        if ta.name:
            relations.add(ta.name.lower())
        aliases.update(c.name.lower() for c in ta.columns)
    for al in tree.find_all(exp.Alias):
        aliases.add(al.alias.lower())
    return relations, aliases


def _function_name(fn: exp.Func) -> str:
    return fn.name.lower() if isinstance(fn, exp.Anonymous) else fn.key


def validate(sql: str, *, max_rows: int) -> ValidatedSql:
    """`max_rows` is the cap on returned rows; LIMIT is set to max_rows + 1 so truncation is detectable."""
    text = (sql or "").strip().rstrip(";").strip()
    if not text:
        raise SqlRejected("empty", "The SQL is empty. Return one SELECT statement.")
    try:
        statements = [s for s in sqlglot.parse(text, read=DIALECT) if s is not None]
    except ParseError as exc:
        detail = exc.errors[0]["description"] if exc.errors else str(exc)
        raise SqlRejected("syntax", f"The SQL could not be parsed: {detail}") from exc
    if len(statements) != 1:
        raise SqlRejected("multiple_statements",
                          "Return exactly one SQL statement, with no semicolons between statements.")
    tree = statements[0]
    if not isinstance(tree, exp.Query):
        raise SqlRejected("not_select", f"Only read-only SELECT queries are allowed (got {tree.key.upper()}).")
    if any(isinstance(n, exp.Command) for n in tree.walk()):
        raise SqlRejected("not_select", "Only read-only SELECT queries are allowed.")

    relations, aliases = _defined_names(tree)

    for table in tree.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier):
            raise SqlRejected("table_function", f"Table functions are not allowed; read from `{TABLE}` only.")
        if table.args.get("db") or table.args.get("catalog"):
            raise SqlRejected("table", f"Do not qualify tables with a schema or database; use `{TABLE}`.")
        name = table.name.lower()
        if name not in ALLOWED_TABLES and name not in relations:
            raise SqlRejected("table", f"Unknown table `{table.name}`. The only table is `{TABLE}`.")

    for fn in tree.find_all(exp.Func):
        if isinstance(fn, _OPERATOR_TYPES):
            continue
        name = _function_name(fn)
        if name not in ALLOWED_FUNCTIONS:
            shown = fn.name if isinstance(fn, exp.Anonymous) else fn.sql_name()
            raise SqlRejected("function", f"Function `{shown}` is not allowed. Use standard aggregate, string, "
                                          "regex, date/time, CAST/CASE/COALESCE or window functions.")

    for col in tree.find_all(exp.Column):
        name = col.name.lower()
        if not name:  # e.g. `t.*`
            continue
        if col.table and col.table.lower() not in ALLOWED_TABLES | relations:
            raise SqlRejected("column", f"Unknown table alias `{col.table}` in `{col.sql(dialect=DIALECT)}`.")
        if name not in ALLOWED_COLUMNS and name not in aliases:
            raise SqlRejected("column", f"Unknown column `{col.name}`. Columns of `{TABLE}` are: {', '.join(COLUMNS)}.")

    cap = max_rows + 1
    limit = tree.args.get("limit")
    if limit is not None:
        value = limit.expression
        if not (isinstance(value, exp.Literal) and value.is_int):
            raise SqlRejected("limit", "LIMIT must be a plain integer.")
        executed = tree if int(value.name) <= cap else tree.limit(cap, copy=True)
    else:
        executed = tree.limit(cap, copy=True)
    return ValidatedSql(sql=executed.sql(dialect=DIALECT), count_sql=tree.sql(dialect=DIALECT), ast=tree)
