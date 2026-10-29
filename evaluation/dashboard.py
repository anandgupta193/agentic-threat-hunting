"""A self-contained HTML page comparing two evaluation runs (written by `main.py --compare`).

One file, no external assets: the run data is embedded as JSON and rendered by a few lines of vanilla JS, so the
page opens offline straight from disk.
"""

import json
from pathlib import Path
from typing import Any

from evaluation.loaders import load_notes
from evaluation.scorer import WEIGHTS

TEMPLATE_PATH = Path(__file__).resolve().parent / "dashboard_template.html"
HYPOTHESIS_FIELDS = ("id", "name", "status", "score", "checks", "shape", "expected", "returned", "matched", "missing",
                     "extra", "truncated", "total_rows", "sql", "confidence", "result_summary", "attempts", "tokens",
                     "latency_ms", "error")


def render_dashboard(before: dict[str, Any], after: dict[str, Any]) -> str:
    data = {
        "before": _slim(before), "after": _slim(after), "notes": load_notes(), "weights": WEIGHTS,
    }
    payload = json.dumps(data, default=str).replace("</", "<\\/")  # safe inside <script>
    return TEMPLATE_PATH.read_text(encoding="utf-8").replace("__DATA__", payload)


def _slim(results: dict[str, Any]) -> dict[str, Any]:
    run = results["run"]
    return {
        "run": {k: run.get(k) for k in ("label", "source_run", "prompt_version", "prompt_hash", "model",
                                        "llm_provider", "max_self_correct", "zero_row_value_check", "started_at")},
        "overall": results["overall"],
        "usage": results.get("usage"),
        "hypotheses": [{k: h.get(k) for k in HYPOTHESIS_FIELDS} for h in results["hypotheses"]],
    }

