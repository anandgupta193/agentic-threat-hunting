"""Run outputs (§9.3): `evaluation_results.json`, `report.md`, and the before/after comparison."""

import json
from pathlib import Path
from typing import Any

from evaluation.loaders import load_notes
from evaluation.scorer import CHECKS, HypothesisScore, overall

CELL_MAX = 60


def build_results(config: dict[str, Any], scores: list[HypothesisScore], bodies: dict[str, dict[str, Any]],
                  credits: dict[str, Any] | None, usage: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "run": config,
        "overall": overall(scores),
        "hypotheses": [_hypothesis(s, bodies.get(s.id)) for s in scores],
        "credits": credits,
        "usage": usage.get("totals") if usage else None,
    }


def _hypothesis(s: HypothesisScore, body: dict[str, Any] | None) -> dict[str, Any]:
    c = s.comparison
    body = body or {}
    result = body.get("result") or {}
    explanation = body.get("explanation") or {}
    attempts = (body.get("trace") or {}).get("attempts") or []
    return {
        "id": s.id, "name": s.name, "status": s.status, "score": s.score, "checks": s.checks, "error": s.error,
        "shape": "aggregate" if s.has_counts else "rows",
        "expected": c.expected_n if c else None, "returned": c.returned_n if c else None,
        "matched": c.matched if c else None, "missing": c.missing if c else None, "extra": c.extra if c else None,
        "precision": _r(c.precision) if c else None, "recall": _r(c.recall) if c else None,
        "count_mean_rel_error": _r(c.count_mean_rel_error) if c else None,
        "column_map": c.column_map if c else None, "key_columns": c.key_columns if c else None,
        "missing_examples": c.missing_examples if c else [], "extra_examples": c.extra_examples if c else [],
        "total_rows": result.get("total_rows"), "truncated": result.get("truncated"),
        "sql": (body.get("query") or {}).get("sql"),
        "confidence": explanation.get("confidence"), "result_summary": explanation.get("result_summary"),
        "attempts": len(attempts), "tokens": (body.get("usage") or {}).get("tokens_used"),
        "latency_ms": (body.get("trace") or {}).get("total_ms"),
    }


def _r(v: float | None) -> float | None:
    return None if v is None else round(v, 4)


def write_run(folder: Path, results: dict[str, Any]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "run_config.json").write_text(json.dumps(results["run"], indent=2) + "\n")
    (folder / "evaluation_results.json").write_text(json.dumps(results, indent=2, default=str) + "\n")
    (folder / "report.md").write_text(render_report(results))


def render_report(results: dict[str, Any]) -> str:
    run, ov = results["run"], results["overall"]
    lines = [
        f"# Evaluation report: {run.get('label', '')}",
        "",
        f"- Prompt `{run.get('prompt_version')}` (`{run.get('prompt_hash')}`), model `{run.get('model')}` via "
        f"`{run.get('llm_provider')}`; self-correction {run.get('max_self_correct')}, value check "
        f"{run.get('zero_row_value_check')}",
        f"- Mode: {run.get('mode')}" + (f" (source `{run['source_run']}`)" if run.get("source_run") else "")
        + (" · **incomplete**" if run.get("incomplete") else ""),
        f"- **Overall score: {_fmt(ov['score'])}** · ran {_fmt(ov['checks']['ran'])} · columns "
        f"{_fmt(ov['checks']['columns'])} · rows/groups {_fmt(ov['checks']['match'])} · counts "
        f"{_fmt(ov['checks']['counts'])}",
        f"- {ov['scored']} scored, {ov['failed']} failed, {ov['errors']} errors, skipped: "
        f"{', '.join(ov['skipped']) or 'none'}",
    ]
    if results.get("usage"):
        u = results["usage"]
        lines.append(f"- Tokens: {u['total_tokens']:,} over {u['calls']} LLM calls")
    lines += ["", "| # | Hypothesis | Status | Score | Ran | Columns | Rows/Groups F1 | Counts | Expected | Returned "
              "| Matched | Missing | Extra | Attempts | Tokens |", "|" + "---|" * 15]
    for h in results["hypotheses"]:
        ch = h["checks"]
        lines.append(f"| {h['id']} | {h['name']} | {h['status']} | {_fmt(h['score'])} | {_fmt(ch['ran'])} | "
                     f"{_fmt(ch['columns'])} | {_fmt(ch['match'])} | {_fmt(ch['counts'])} | {_n(h['expected'])} | "
                     f"{_n(h['returned'])} | {_n(h['matched'])} | {_n(h['missing'])} | {_n(h['extra'])} | "
                     f"{h['attempts'] or '–'} | {_n(h['tokens'])} |")
    lines += ["", "## Expected vs found", ""]
    notes = load_notes()
    for h in results["hypotheses"]:
        lines += [f"### {h['id']}. {h['name']}: {h['status']}", ""]
        if note := notes.get(h["id"]):
            lines += [f"> **Answer-key note:** {note}", ""]
        if h["status"] != "scored":
            lines += [f"Not scored: `{h['error']}`.", ""]
            continue
        lines.append(f"Expected {h['expected']:,} {'groups' if h['shape'] == 'aggregate' else 'rows'}, returned "
                     f"{h['returned']:,} (total {_n(h['total_rows'])}{', truncated' if h['truncated'] else ''}): "
                     f"{h['matched']:,} matched, {h['missing']:,} missing, {h['extra']:,} extra. "
                     f"Matched on `{', '.join(h['key_columns']) or '(no shared columns)'}`.")
        if h["result_summary"]:
            lines.append(f"API summary: {h['result_summary']}")
        lines += ["", "```sql", h["sql"] or "", "```"]
        for label, rows in (("Missing (expected, not returned)", h["missing_examples"]),
                            ("Extra (returned, not expected)", h["extra_examples"])):
            if rows:
                lines += ["", f"{label}:", ""] + [f"- {_row(r)}" for r in rows]
        lines.append("")
    return "\n".join(lines) + "\n"


def render_compare(before: dict[str, Any], after: dict[str, Any]) -> str:
    b, a = before["overall"], after["overall"]
    lines = [f"# Compare: {before['run'].get('label')} → {after['run'].get('label')}", "",
             "| | Before | After | Δ |", "|---|---|---|---|",
             f"| **Overall** | {_fmt(b['score'])} | {_fmt(a['score'])} | {_delta(b['score'], a['score'])} |"]
    for c in CHECKS:
        lines.append(f"| {c} | {_fmt(b['checks'][c])} | {_fmt(a['checks'][c])} | "
                     f"{_delta(b['checks'][c], a['checks'][c])} |")
    lines += ["", "| # | Hypothesis | Before | After | Δ | Status |", "|---|---|---|---|---|---|"]
    after_by_id = {h["id"]: h for h in after["hypotheses"]}
    for hb in before["hypotheses"]:
        ha = after_by_id.get(hb["id"], {})
        lines.append(f"| {hb['id']} | {hb['name']} | {_fmt(hb['score'])} | {_fmt(ha.get('score'))} | "
                     f"{_delta(hb['score'], ha.get('score'))} | {hb['status']} → {ha.get('status', '–')} |")
    return "\n".join(lines) + "\n"


def _row(r: dict[str, Any]) -> str:
    return ", ".join(f"{k}=`{_cell(v)}`" for k, v in r.items())


def _cell(v: Any) -> str:
    s = "null" if v is None else str(v)
    return s if len(s) <= CELL_MAX else s[: CELL_MAX - 1] + "…"


def _fmt(v: float | None) -> str:
    return "–" if v is None else f"{v:.2f}"


def _n(v: int | None) -> str:
    return "–" if v is None else f"{v:,}"


def _delta(b: float | None, a: float | None) -> str:
    return "–" if a is None or b is None else f"{a - b:+.2f}"
