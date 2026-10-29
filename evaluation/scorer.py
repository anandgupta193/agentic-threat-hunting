"""Composite score per hypothesis and the run's macro averages (§9.5, D25).

ran 20% · right columns 20% · right rows/groups 40% · right counts 20%. Row-shaped answers have no counts, so
their weights become 25 / 25 / 50. A query that failed to run, or a generation that failed, scores 0 on every
check. Skipped hypotheses (no credits left) are excluded from the averages.
"""

from dataclasses import dataclass
from typing import Any, Literal

from evaluation.metrics import Comparison, compare
from evaluation.normalizers import Table

WEIGHTS = {"ran": 0.20, "columns": 0.20, "match": 0.40, "counts": 0.20}
CHECKS = tuple(WEIGHTS)

Status = Literal["scored", "failed", "error", "skipped"]


@dataclass(slots=True)
class HypothesisScore:
    id: str
    name: str
    status: Status            # scored: the query ran · failed: status "failed" · error: HTTP error · skipped
    has_counts: bool
    score: float | None       # None only when skipped
    checks: dict[str, float | None]
    comparison: Comparison | None = None
    error: str | None = None


def score_response(hid: str, name: str, expected: Table, body: dict[str, Any] | None,
                   error: str | None = None) -> HypothesisScore:
    """`body` is the raw POST /v1/queries response; None with `error` for an HTTP failure; both None if skipped."""
    has_counts = expected.count_column() is not None
    if body is None:
        status: Status = "skipped" if error is None else "error"
        return _zero(hid, name, status, has_counts, error)
    if body.get("status") != "succeeded" or not body.get("result"):
        err = (body.get("error") or {}).get("code") or "NO_RESULT"
        return _zero(hid, name, "failed", has_counts, err)
    result = body["result"]
    comparison = compare(expected, Table.build(result["columns"], result["rows"]))
    checks: dict[str, float | None] = {
        "ran": 1.0, "columns": comparison.column_jaccard, "match": comparison.f1,
        "counts": comparison.count_exact_rate if has_counts else None,
    }
    return HypothesisScore(id=hid, name=name, status="scored", has_counts=has_counts,
                           score=_weighted(checks), checks=checks, comparison=comparison)


def _zero(hid: str, name: str, status: Status, has_counts: bool, error: str | None) -> HypothesisScore:
    if status == "skipped":
        return HypothesisScore(id=hid, name=name, status=status, has_counts=has_counts, score=None,
                               checks={c: None for c in CHECKS}, error=error)
    checks: dict[str, float | None] = {c: 0.0 for c in CHECKS}
    if not has_counts:
        checks["counts"] = None
    return HypothesisScore(id=hid, name=name, status=status, has_counts=has_counts, score=0.0, checks=checks,
                           error=error)


def _weighted(checks: dict[str, float | None]) -> float:
    applicable = {c: w for c, w in WEIGHTS.items() if checks[c] is not None}
    total = sum(applicable.values())
    return round(sum(w / total * (checks[c] or 0.0) for c, w in applicable.items()), 4)


def overall(scores: list[HypothesisScore]) -> dict[str, Any]:
    counted = [s for s in scores if s.status != "skipped"]
    per_check: dict[str, float | None] = {}
    for c in CHECKS:
        values = [s.checks[c] for s in counted if s.checks[c] is not None]
        per_check[c] = round(sum(values) / len(values), 4) if values else None  # type: ignore[arg-type]
    return {
        "score": round(sum(s.score or 0.0 for s in counted) / len(counted), 4) if counted else None,
        "checks": per_check,
        "hypotheses": len(scores),
        "scored": sum(s.status == "scored" for s in scores),
        "failed": sum(s.status == "failed" for s in scores),
        "errors": sum(s.status == "error" for s in scores),
        "skipped": [s.id for s in scores if s.status == "skipped"],
    }
