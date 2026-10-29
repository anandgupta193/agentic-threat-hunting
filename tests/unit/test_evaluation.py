"""P4: normalisation, strict metrics, the composite score, runner failure handling (stub API) and replay."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from evaluation.loaders import Hypothesis
from evaluation.normalizers import Table, match_columns, norm_value
from evaluation.runner import LiveRunner, replay
from evaluation.scorer import score_response


@pytest.mark.parametrize(("raw", "want"), [
    (811596193553.0, "811596193553"), ("811596193553.0", "811596193553"), (1.05, "1.05"), ("1.10", "1.1"),
    (float("nan"), None), ("", None), ("  x ", "x"), ("0123", "0123"),
    ("2017-05-17 23:23:34", "2017-05-17T23:23:34Z"), ("2017-05-17T23:23:34.000Z", "2017-05-17T23:23:34Z"),
])
def test_norm_value(raw: Any, want: str | None) -> None:
    assert norm_value(raw) == want


def test_alias_tolerant_columns() -> None:
    assert match_columns(["instanceType", "user_agent", "count"],
                         ["requestParametersinstanceType", "userAgent", "count"]) == {
        "instanceType": "requestParametersinstanceType", "user_agent": "userAgent", "count": "count"}


def body(columns: list[str], rows: list[list[Any]]) -> dict[str, Any]:
    return {"status": "succeeded", "result": {"columns": columns, "rows": rows}}


def test_rows_are_a_multiset_and_row_shape_reweights() -> None:
    expected = Table.build(["ip", "arn"], [["1", "a"], ["1", "a"], ["2", "b"]])
    s = score_response("x", "x", expected, body(["ip", "arn", "extra"], [["1", "a", "z"], ["3", "c", "z"]]))
    c = s.comparison
    assert c is not None and (c.matched, c.missing, c.extra) == (1, 2, 1)
    # ran 1 · columns 2/3 · F1 0.4 → 25/25/50 weights (no counts for row-shaped answers)
    assert s.score == pytest.approx(0.25 + 0.25 * 2 / 3 + 0.5 * 0.4, abs=1e-4)


def test_groups_and_counts() -> None:
    expected = Table.build(["arn", "count"], [["a", 10], ["b", 5], ["c", 1]])
    s = score_response("x", "x", expected, body(["arn", "n_calls"], [["a", 10], ["b", 4]]))
    assert s.checks["match"] == pytest.approx(0.8)          # P 2/2, R 2/3
    assert s.checks["counts"] == 0.5                        # 1 of 2 matched counts exact
    assert s.comparison is not None and s.comparison.column_map["count"] == "n_calls"  # integer-column fallback


def test_failed_generation_scores_zero() -> None:
    expected = Table.build(["arn", "count"], [["a", 1]])
    s = score_response("x", "x", expected, {"status": "failed", "error": {"code": "SELF_CORRECTION_EXHAUSTED"}})
    assert (s.status, s.score, s.error) == ("failed", 0.0, "SELF_CORRECTION_EXHAUSTED")


HYPOTHESES = [Hypothesis(id, f"h{id}", f"hypothesis {id}") for id in ("1", "2", "3")]
EXPECTED = {h.id: Table.build(["eventName"], [["ConsoleLogin"]]) for h in HYPOTHESES}
OK = {"status": "succeeded", "result": {"columns": ["eventName"], "rows": [["ConsoleLogin"]]},
      "usage": {"tokens_used": 100}}


def stub_api(query_replies: list[tuple[int, dict[str, Any]]], sent_ids: list[str] | None = None) -> httpx.Client:
    """Health, user creation and account reads always succeed; /v1/queries replies come from the list in order.
    Each query gets server request id `srv-<n>`; the client's `X-Request-Id` values are appended to `sent_ids`."""
    replies = iter(query_replies)
    served = 0

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/healthz":
            return httpx.Response(200, json={"llm": {"provider": "fake", "model": "m"}, "harness": {
                "prompt_version": "v1", "prompt_hash": "abc", "max_result_rows": 100}})
        if path == "/v1/users":
            return httpx.Response(201, json={"user_id": "eval", "token_limit": 1000})
        if path.endswith("/credits") or path.endswith("/usage"):
            return httpx.Response(200, json={"totals": {"calls": 1, "total_tokens": 100}})
        nonlocal served
        served += 1
        if sent_ids is not None:
            sent_ids.append(request.headers.get("x-request-id", ""))
        status, payload = next(replies)
        headers = {"X-Request-Id": f"srv-{served}"} | ({"Retry-After": "1"} if status == 429 else {})
        return httpx.Response(status, json=payload, headers=headers)

    return httpx.Client(transport=httpx.MockTransport(handler), base_url="http://api")


def err(code: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": "m", "details": {}}, "request_id": "r"}


def test_runner_retries_once_then_skips_after_exhaustion(tmp_path: Path) -> None:
    sent_ids: list[str] = []
    client = stub_api([
        (502, err("LLM_ERROR")), (200, OK),          # #1: one upstream retry, then scored
        (429, err("CREDITS_CONTENDED")), (200, OK),  # #2: waits Retry-After once, then scored
        (429, err("CREDITS_EXHAUSTED")),             # #3: stop; skipped
    ], sent_ids)
    waits: list[float] = []
    folder, results = LiveRunner(client, HYPOTHESES, EXPECTED, tmp_path, copy_to_root=False,
                                 sleep=waits.append).run()
    assert [h["status"] for h in results["hypotheses"]] == ["scored", "scored", "skipped"]
    assert results["overall"]["score"] == 1.0 and results["overall"]["skipped"] == ["3"]
    assert waits == [5.0, 1.0]
    assert (folder / "report.md").exists() and not (folder / "responses" / "3.json").exists()
    assert sent_ids == [f"{folder.name}/{h}" for h in ("1", "1", "2", "2", "3")]  # server logs it as client_request_id
    log = (folder / "run.log").read_text()
    assert "request_id=srv-2" in log and "request_id=srv-4" in log and "credits exhausted" in log

    replayed_folder, replayed = replay(folder, HYPOTHESES, EXPECTED, tmp_path)
    assert replayed["overall"] == results["overall"]
    assert json.loads((replayed_folder / "run_config.json").read_text())["mode"] == "replay"


def test_raw_rows_never_use_an_id_column_as_the_count() -> None:
    expected = Table.build(["instanceType", "count"], [["p2.16xlarge", 3]])
    s = score_response("x", "x", expected, body(["requestParametersinstanceType", "userIdentityaccountId"],
                                                [["p2.16xlarge", "811596193553"]]))
    assert s.comparison is not None and "count" not in s.comparison.column_map
    assert s.checks["counts"] == 0.0


def test_dashboard_embeds_both_runs_safely() -> None:
    from evaluation.dashboard import render_dashboard
    run = {"run": {"label": "r"}, "overall": {"score": 0.5, "checks": {}}, "usage": None,
           "hypotheses": [{"id": "1", "name": "</script><b>x", "score": 0.5, "checks": {}}]}
    page = render_dashboard(run, run)
    assert page.count("</script>") == 2  # the two real closing tags; the payload's is escaped
    assert "<\\/script><b>x" in page
