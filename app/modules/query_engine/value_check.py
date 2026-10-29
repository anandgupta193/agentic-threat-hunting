"""Zero-row value check (D33). When a query runs but returns no rows, check each filter literal exists.

Only `column = 'x'`, `column IN ('x', ...)` and `column [I]LIKE 'pattern'` comparisons are checked. Categorical
columns are answered from the schema card's complete value list; others with a parameterised probe.
A literal that matches nothing makes the attempt correctable, with the closest real values as hints.
"""

import difflib
import re
from dataclasses import dataclass, field
from typing import Any

from sqlglot import exp

from app.modules.query_engine.allowlist import COLUMN_BY_LOWER
from app.modules.query_engine.executor import DuckDBExecutor

MAX_SUGGESTIONS = 3


@dataclass(frozen=True, slots=True)
class MissingValue:
    column: str
    literal: str
    operator: str
    suggestions: list[str] = field(default_factory=list)

    def describe(self) -> str:
        hint = f"; closest values: {', '.join(repr(s) for s in self.suggestions)}" if self.suggestions else ""
        return f"value {self.literal!r} not found in {self.column} ({self.operator}){hint}"


def _like_to_regex(pattern: str, case_insensitive: bool) -> re.Pattern[str]:
    body = "".join(".*" if ch == "%" else "." if ch == "_" else re.escape(ch) for ch in pattern)
    return re.compile(f"^{body}$", re.IGNORECASE | re.DOTALL if case_insensitive else re.DOTALL)


def _comparisons(tree: exp.Expr) -> list[tuple[str, str, str]]:
    """(column, literal, operator) for every checkable comparison against one of the 19 columns."""
    found: list[tuple[str, str, str]] = []

    def column_of(node: exp.Expr) -> str | None:
        if isinstance(node, exp.Lower | exp.Upper):  # LOWER(col) = 'x' is common; treat as case-insensitive
            node = node.this
        if isinstance(node, exp.Column) and node.name.lower() in COLUMN_BY_LOWER:
            return COLUMN_BY_LOWER[node.name.lower()]
        return None

    for node in tree.find_all(exp.EQ, exp.In, exp.Like, exp.ILike):
        col = column_of(node.this)
        if col is None:
            continue
        ci = isinstance(node, exp.ILike) or isinstance(node.this, exp.Lower | exp.Upper)
        if isinstance(node, exp.In):
            for lit in node.expressions:
                if isinstance(lit, exp.Literal) and lit.is_string:
                    found.append((col, lit.name, "IN-ci" if ci else "IN"))
        elif isinstance(node.expression, exp.Literal) and node.expression.is_string:
            op = "LIKE" if isinstance(node, exp.Like | exp.ILike) else "="
            found.append((col, node.expression.name, f"{op}-ci" if ci else op))
    return found


class ValueChecker:
    def __init__(self, schema_card: dict[str, Any], executor: DuckDBExecutor) -> None:
        self._executor = executor
        self._complete: dict[str, list[str]] = {}
        self._known: dict[str, list[str]] = {}
        for c in schema_card["columns"]:
            values = [v["value"] for v in c["values"]]
            self._known[c["name"]] = values
            if c["values_complete"]:
                self._complete[c["name"]] = values

    def _suggest(self, column: str, literal: str) -> list[str]:
        candidates = self._known.get(column, [])
        needle = literal.strip("%").lower()
        containing = [v for v in candidates if needle and needle in v.lower()]
        close = difflib.get_close_matches(literal, candidates, n=MAX_SUGGESTIONS, cutoff=0.5)
        return list(dict.fromkeys(containing + close))[:MAX_SUGGESTIONS]

    async def _exists(self, column: str, literal: str, operator: str) -> bool:
        ci = operator.endswith("-ci")
        like = operator.startswith("LIKE")
        values = self._complete.get(column)
        if values is not None:
            if like:
                rx = _like_to_regex(literal, ci)
                return any(rx.match(v) for v in values)
            return any((v.lower() == literal.lower()) if ci else v == literal for v in values)
        return await self._executor.value_exists(column, literal, like=like, case_insensitive=ci)

    async def missing_values(self, tree: exp.Expr) -> list[MissingValue]:
        missing = []
        for column, literal, operator in _comparisons(tree):
            if not await self._exists(column, literal, operator):
                missing.append(MissingValue(column, literal, operator.removesuffix("-ci"),
                                            self._suggest(column, literal)))
        return missing
