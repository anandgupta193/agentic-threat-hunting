"""One normalisation applied to both sides before any comparison (§9.4).

- numbers in one canonical text form: `811596193553.0`, `"811596193553.0"` and `811596193553` are equal, as are
  `1.05` and `"1.05"`
- `NaN` / `None` / empty string are one null
- strings trimmed; timestamps in one form (`2017-05-17T23:23:34Z`, with or without `Z`, `T` or `.000`)
- column names compared case- and punctuation-insensitively, with suffix aliases (`instanceType` ↔
  `requestParametersinstanceType`)
"""

import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

_NUMBER = re.compile(r"^-?(0|[1-9]\d*)(\.\d+)?$")  # no leading zeros: "0123" stays an identifier
_TIMESTAMP = re.compile(r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(\.0+)?(Z|\+00:00|\+00)?$")
COUNT_NAMES = {"count", "cnt", "n", "total", "freq", "frequency", "occurrences", "num", "events", "hits"}
MIN_ALIAS_LEN = 4


def norm_value(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if math.isnan(v):
            return None
        return _canonical_number(repr(v))
    s = str(v).strip()
    if not s or s.lower() in {"nan", "none", "null"}:
        return None
    if _NUMBER.match(s):
        return _canonical_number(s)
    if m := _TIMESTAMP.match(s):
        return f"{m.group(1)}T{m.group(2)}Z"
    return s


def _canonical_number(s: str) -> str:
    try:
        d = Decimal(s)
    except InvalidOperation:
        return s
    if d == d.to_integral_value():
        return str(d.quantize(Decimal(1)))
    return format(d.normalize(), "f")


def norm_count(v: Any) -> int | None:
    value = norm_value(v)
    if value is None or not _NUMBER.match(value) or "." in value:
        return None
    return int(value)


def norm_name(column: str) -> str:
    return re.sub(r"[^a-z0-9]", "", column.lower())


def is_count_name(column: str) -> bool:
    n = norm_name(column)
    return n in COUNT_NAMES or n.endswith("count") or n.startswith("count") or n.startswith("num")


@dataclass(frozen=True, slots=True)
class Table:
    columns: list[str]
    rows: list[tuple[str | None, ...]]   # normalised values, same order as `columns`

    @classmethod
    def build(cls, columns: Sequence[str], rows: Iterable[Sequence[Any]]) -> "Table":
        return cls(columns=list(columns), rows=[tuple(norm_value(v) for v in r) for r in rows])

    def count_column(self) -> str | None:
        names = [c for c in self.columns if is_count_name(c)]
        return names[0] if len(names) == 1 else None


def match_columns(expected: Sequence[str], returned: Sequence[str]) -> dict[str, str]:
    """Map expected → returned columns: exact (normalised) names first, then a unique suffix alias."""
    mapping: dict[str, str] = {}
    free = {norm_name(r): r for r in returned}
    for e in expected:
        if (r := free.pop(norm_name(e), None)) is not None:
            mapping[e] = r
    for e in expected:
        if e in mapping:
            continue
        ne = norm_name(e)
        if len(ne) < MIN_ALIAS_LEN:
            continue
        candidates = [k for k in free if len(k) >= MIN_ALIAS_LEN and (k.endswith(ne) or ne.endswith(k))]
        if len(candidates) == 1:
            mapping[e] = free.pop(candidates[0])
    return mapping
