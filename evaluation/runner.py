"""Evaluation runs (§9.1–9.6). A live run talks to the API over real HTTP only (D38); replay and compare are
offline. Every response is saved as soon as it arrives, so an interrupted run keeps what it has done.

Each query is sent with `X-Request-Id: <run label>/<hypothesis id>`, which the server logs as `client_request_id`,
and each progress line names the server's `request_id`, so a run can be matched to the server logs. Progress lines go
to stderr and to `run.log` in the run folder."""

import json
import shutil
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from evaluation.dashboard import render_dashboard
from evaluation.loaders import ROOT, Hypothesis
from evaluation.normalizers import Table
from evaluation.report import build_results, render_compare, write_run
from evaluation.scorer import HypothesisScore, score_response

QUERY_TIMEOUT_S = 600.0     # up to 1 + MAX_SELF_CORRECT LLM calls plus DuckDB time
UPSTREAM_RETRY_WAIT_S = 5.0


class ApiUnreachable(Exception):
    pass


class _CreditsExhausted(Exception):
    pass


def _stamp(now: datetime) -> str:
    return now.strftime("%Y-%m-%dT%H-%M-%SZ")


class LiveRunner:
    def __init__(self, client: httpx.Client, hypotheses: list[Hypothesis], expected: dict[str, Table],
                 runs_dir: Path, *, token_limit: int | None = None, copy_to_root: bool = True,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self._http = client
        self._hypotheses = hypotheses
        self._expected = expected
        self._runs_dir = runs_dir
        self._token_limit = token_limit
        self._copy_to_root = copy_to_root
        self._sleep = sleep
        self._log_path: Path | None = None

    def run(self) -> tuple[Path, dict[str, Any]]:
        health = self._health()
        harness, llm = health["harness"], health["llm"]
        now = datetime.now(UTC)
        label = f"{_stamp(now)}_{harness['prompt_version']}"
        folder = self._runs_dir / label
        user_id = f"eval-{now:%Y%m%dT%H%M%SZ}"
        user = {"user_id": user_id} | ({"token_limit": self._token_limit} if self._token_limit else {})
        r = self._http.post("/v1/users", json=user)
        r.raise_for_status()
        config: dict[str, Any] = {
            "label": label, "mode": "live", "started_at": now.isoformat(), "api_base_url": str(self._http.base_url),
            "user_id": user_id, "token_limit": r.json()["token_limit"], "llm_provider": llm["provider"],
            "model": llm["model"], **harness, "hypothesis_ids": [h.id for h in self._hypotheses], "incomplete": False,
        }
        (folder / "responses").mkdir(parents=True)
        self._log_path = folder / "run.log"
        self._log(f"Run {label}: {len(self._hypotheses)} hypotheses as {user_id} "
                  f"(limit {config['token_limit']:,} tokens) → {folder}")

        scores: list[HypothesisScore] = []
        bodies: dict[str, dict[str, Any]] = {}
        stop: str | None = None
        for i, h in enumerate(self._hypotheses, 1):
            if stop:
                scores.append(score_response(h.id, h.name, self._expected[h.id], None))
                continue
            try:
                body, error, request_id = self._query(h, f"{label}/{h.id}", user_id, harness["max_result_rows"])
            except _CreditsExhausted:
                stop = "credits exhausted"
                self._log(f"[{i}/{len(self._hypotheses)}] #{h.id}: credits exhausted, the rest are skipped")
                scores.append(score_response(h.id, h.name, self._expected[h.id], None))
                continue
            except (httpx.TransportError, KeyboardInterrupt) as exc:
                stop = "interrupted"
                config["incomplete"] = True
                self._log(f"[{i}/{len(self._hypotheses)}] #{h.id}: run interrupted ({type(exc).__name__}); "
                          "saving progress")
                scores.append(score_response(h.id, h.name, self._expected[h.id], None))
                continue
            (folder / "responses" / f"{h.id}.json").write_text(json.dumps(body, separators=(",", ":")) + "\n")
            bodies[h.id] = body
            s = score_response(h.id, h.name, self._expected[h.id], None if error else body, error)
            scores.append(s)
            self._log(f"[{i}/{len(self._hypotheses)}] #{h.id} {h.name}: {s.status} "
                      f"score={'–' if s.score is None else f'{s.score:.2f}'}"
                      f"{f' ({s.error})' if s.error else ''} "
                      f"tokens={(body.get('usage') or {}).get('tokens_used', '–')} request_id={request_id}")

        credits, usage = self._account(user_id)
        config["finished_at"] = datetime.now(UTC).isoformat()
        results = build_results(config, scores, bodies, credits, usage)
        write_run(folder, results)
        if self._copy_to_root and not config["incomplete"]:
            shutil.copyfile(folder / "evaluation_results.json", ROOT / "evaluation_results.json")
        return folder, results

    def _health(self) -> dict[str, Any]:
        try:
            r = self._http.get("/healthz", timeout=10)
        except httpx.TransportError as exc:
            raise ApiUnreachable(f"API not reachable at {self._http.base_url}; run `make up` first") from exc
        if r.status_code != 200:
            raise ApiUnreachable(f"API at {self._http.base_url} is not healthy: {r.text}")
        health: dict[str, Any] = r.json()
        return health

    def _log(self, msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)
        if self._log_path:
            with self._log_path.open("a", encoding="utf-8") as f:
                f.write(msg + "\n")

    def _query(self, h: Hypothesis, client_request_id: str, user_id: str,
               max_rows: int) -> tuple[dict[str, Any], str | None, str]:
        """Returns (body, error, server request_id). 429 contended → wait Retry-After once; 502/504 → retry once
        (D42)."""
        payload = {"title": h.name, "hypothesis": h.text, "include_results": True, "max_rows": max_rows}
        retried_contended = retried_upstream = False
        while True:
            headers = {"X-User-Id": user_id, "X-Request-Id": client_request_id}
            r = self._http.post("/v1/queries", json=payload, headers=headers, timeout=QUERY_TIMEOUT_S)
            body: dict[str, Any] = r.json()
            request_id = r.headers.get("x-request-id") or body.get("request_id") or "–"
            if r.status_code == 200:
                return body, None, request_id
            code = (body.get("error") or {}).get("code", "UNKNOWN")
            if r.status_code == 429 and code == "CREDITS_EXHAUSTED":
                raise _CreditsExhausted
            if r.status_code == 429 and not retried_contended:
                retried_contended = True
                self._sleep(float(r.headers.get("retry-after", "5")))
                continue
            if r.status_code in (502, 504) and not retried_upstream:
                retried_upstream = True
                self._log(f"#{h.id}: HTTP {r.status_code} {code} (request_id={request_id}), retrying once")
                self._sleep(UPSTREAM_RETRY_WAIT_S)
                continue
            return body, f"HTTP {r.status_code} {code}", request_id

    def _account(self, user_id: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        try:
            headers = {"X-User-Id": user_id}
            credits = self._http.get(f"/v1/users/{user_id}/credits", headers=headers).json()
            usage = self._http.get(f"/v1/users/{user_id}/usage", headers=headers).json()
            return credits, usage
        except httpx.TransportError:
            return None, None


def replay(source: Path, hypotheses: list[Hypothesis], expected: dict[str, Table],
           runs_dir: Path) -> tuple[Path, dict[str, Any]]:
    """Re-score a saved run with the current scoring code. No API or LLM calls."""
    src = json.loads((source / "evaluation_results.json").read_text())
    config = dict(src["run"])
    by_id = {h.id: h for h in hypotheses}
    scores: list[HypothesisScore] = []
    bodies: dict[str, dict[str, Any]] = {}
    for hid in config["hypothesis_ids"]:
        h = by_id[hid]
        path = source / "responses" / f"{hid}.json"
        if not path.exists():
            scores.append(score_response(hid, h.name, expected[hid], None))
            continue
        body = json.loads(path.read_text())
        bodies[hid] = body
        if "status" in body:
            scores.append(score_response(hid, h.name, expected[hid], body))
        else:  # a saved error envelope
            code = (body.get("error") or {}).get("code", "UNKNOWN")
            scores.append(score_response(hid, h.name, expected[hid], None, f"HTTP error {code}"))
    now = datetime.now(UTC)
    config |= {"label": f"{_stamp(now)}_replay_{config['label']}", "mode": "replay", "source_run": config["label"],
               "replayed_at": now.isoformat()}
    folder = runs_dir / config["label"]
    results = build_results(config, scores, bodies, src.get("credits"), {"totals": src["usage"]} if src.get("usage")
                            else None)
    write_run(folder, results)
    shutil.copytree(source / "responses", folder / "responses")
    return folder, results


def compare(before: Path, after: Path) -> tuple[Path, str]:
    b = json.loads((before / "evaluation_results.json").read_text())
    a = json.loads((after / "evaluation_results.json").read_text())
    text = render_compare(b, a)
    out = after / f"compare_vs_{before.name}.md"
    out.write_text(text)
    page = render_dashboard(b, a)
    (after / "dashboard.html").write_text(page)
    (ROOT / "evaluation_dashboard.html").write_text(page)  # stable path next to evaluation_results.json
    return out, text
