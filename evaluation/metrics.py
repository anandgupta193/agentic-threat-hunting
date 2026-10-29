"""Strict comparison of a returned table against the expected one (§9.4). Both tables are already normalised.

Row outputs are matched as a multiset on `eventID` when both sides have it, otherwise on the tuple of shared
expected columns. Aggregate outputs are matched on the group-key tuple (the expected non-count columns that the
returned table also has); counts are then compared for the matched groups.
"""

from collections import Counter
from dataclasses import dataclass, field
from typing import Literal

from app.modules.query_engine.dataset import COLUMNS
from evaluation.normalizers import Table, match_columns, norm_count, norm_name

Key = tuple[str | None, ...]
EXAMPLES = 3


@dataclass(slots=True)
class Comparison:
    shape: Literal["rows", "aggregate"]
    column_map: dict[str, str]
    column_jaccard: float
    key_columns: list[str]
    expected_n: int
    returned_n: int
    matched: int
    precision: float
    recall: float
    f1: float
    count_exact_rate: float | None = None
    count_mean_rel_error: float | None = None
    missing_examples: list[dict[str, str | None]] = field(default_factory=list)
    extra_examples: list[dict[str, str | None]] = field(default_factory=list)

    @property
    def missing(self) -> int:
        return self.expected_n - self.matched

    @property
    def extra(self) -> int:
        return self.returned_n - self.matched


def compare(expected: Table, returned: Table) -> Comparison:
    count_col = expected.count_column()
    mapping = match_columns(expected.columns, returned.columns)
    if (count_col is not None and count_col not in mapping
            and (fallback := _numeric_fallback(returned, set(mapping.values()))) is not None):
        mapping[count_col] = fallback
    jaccard = len(mapping) / (len(expected.columns) + len(returned.columns) - len(mapping))
    if count_col is None:
        return _compare_rows(expected, returned, mapping, jaccard)
    return _compare_groups(expected, returned, mapping, jaccard, count_col)


def _compare_rows(expected: Table, returned: Table, mapping: dict[str, str], jaccard: float) -> Comparison:
    id_col = next((e for e in mapping if e.lower() == "eventid"), None)
    keys = [id_col] if id_col else list(mapping)
    exp_keys = _keys(expected, keys)
    ret_keys = _keys(returned, [mapping[k] for k in keys])
    e, r = Counter(exp_keys), Counter(ret_keys)
    matched = sum((e & r).values()) if keys else 0  # no shared column: nothing can match
    p, rc, f1 = _prf(matched, len(returned.rows), len(expected.rows))
    return Comparison(
        shape="rows", column_map=mapping, column_jaccard=jaccard, key_columns=keys,
        expected_n=len(expected.rows), returned_n=len(returned.rows), matched=matched, precision=p, recall=rc, f1=f1,
        missing_examples=_examples(expected, exp_keys, e - r, expected.columns),
        extra_examples=_examples(returned, ret_keys, r - e, returned.columns),
    )


def _compare_groups(expected: Table, returned: Table, mapping: dict[str, str], jaccard: float,
                    count_col: str) -> Comparison:
    keys = [c for c in expected.columns if c != count_col and c in mapping]
    exp_groups = _groups(expected, keys, count_col)
    ret_count_col = mapping.get(count_col)
    ret_groups = _groups(returned, [mapping[k] for k in keys], ret_count_col) if keys else {}
    common = exp_groups.keys() & ret_groups.keys()
    p, rc, f1 = _prf(len(common), len(ret_groups), len(exp_groups))
    exact, rel_errors = 0, []
    for k in common:
        want, got = exp_groups[k], ret_groups[k]
        if got is not None and want is not None:
            exact += got == want
            rel_errors.append(abs(got - want) / want if want else float(got != want))
    exp_only = Counter({k: 1 for k in exp_groups.keys() - ret_groups.keys()})
    ret_only = Counter({k: 1 for k in ret_groups.keys() - exp_groups.keys()})
    exp_cols = keys + [count_col]
    return Comparison(
        shape="aggregate", column_map=mapping, column_jaccard=jaccard, key_columns=keys,
        expected_n=len(exp_groups), returned_n=len(ret_groups), matched=len(common), precision=p, recall=rc, f1=f1,
        count_exact_rate=exact / len(common) if common else 0.0,
        count_mean_rel_error=sum(rel_errors) / len(rel_errors) if rel_errors else None,
        missing_examples=[dict(zip(exp_cols, (*k, _str(exp_groups[k])), strict=True))
                          for k in sorted(exp_only, key=str)[:EXAMPLES]],
        extra_examples=[dict(zip(exp_cols, (*k, _str(ret_groups[k])), strict=True))
                        for k in sorted(ret_only, key=str)[:EXAMPLES]],
    )


def _keys(table: Table, columns: list[str]) -> list[Key]:
    idx = [table.columns.index(c) for c in columns]
    return [tuple(row[i] for i in idx) for row in table.rows]


def _groups(table: Table, columns: list[str], count_col: str | None) -> dict[Key, int | None]:
    """Group key → count. Duplicate keys are summed. Without a count column the counts are unknown (None)."""
    out: dict[Key, int | None] = {}
    ci = table.columns.index(count_col) if count_col else None
    for key, row in zip(_keys(table, columns), table.rows, strict=True):
        n = norm_count(row[ci]) if ci is not None else None
        if n is None:
            out.setdefault(key, None)
        else:
            out[key] = (out.get(key) or 0) + n
    return out


def _numeric_fallback(returned: Table, used: set[str]) -> str | None:
    """If the count column has an unrecognised name, accept the one remaining all-integer computed column.
    Dataset columns never qualify: an all-digit ID such as `userIdentityaccountId` is not a count."""
    raw = {norm_name(c) for c in COLUMNS}
    candidates = [c for i, c in enumerate(returned.columns)
                  if c not in used and norm_name(c) not in raw and returned.rows
                  and all(norm_count(r[i]) is not None for r in returned.rows if r[i] is not None)]
    return candidates[0] if len(candidates) == 1 else None


def _examples(table: Table, keys: list[Key], wanted: Counter[Key], columns: list[str]) -> list[dict[str, str | None]]:
    out: list[dict[str, str | None]] = []
    left = Counter(wanted)
    for key, row in zip(keys, table.rows, strict=True):
        if len(out) == EXAMPLES:
            break
        if left[key] > 0:
            left[key] -= 1
            out.append(dict(zip(columns, row, strict=True)))
    return out


def _prf(matched: int, returned: int, expected: int) -> tuple[float, float, float]:
    p = matched / returned if returned else 0.0
    r = matched / expected if expected else 0.0
    return p, r, (2 * p * r / (p + r) if p + r else 0.0)


def _str(v: int | None) -> str | None:
    return None if v is None else str(v)
