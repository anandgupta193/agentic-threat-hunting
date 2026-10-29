"""P3: POST /v1/queries end to end with FakeGateway on the tiny fixture dataset."""

from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.errors import CreditsExhausted
from app.modules.harness.credit_guard import Claim
from app.modules.llm.fake_gateway import FakeGateway
from app.modules.llm.types import LLMUsage

HEADERS = {"X-User-Id": "analyst-1"}
BODY = {"title": "Unauthorized API Calls", "hypothesis": "Unauthorized API calls reveal malicious activity"}


def draft(sql: str, kind: str = "rows", assumptions: list[str] | None = None) -> dict[str, Any]:
    return {"interpretation": "i", "reasoning": "r", "assumptions": assumptions or [], "sql": sql,
            "output_kind": kind}


async def test_success_first_attempt(client: httpx.AsyncClient, fake_llm: FakeGateway) -> None:
    fake_llm.push(draft("SELECT errorCode, COUNT(*) AS count FROM cloudtrail WHERE errorCode IS NOT NULL "
                        "GROUP BY 1", kind="aggregate"), input_tokens=1000, output_tokens=200)
    r = await client.post("/v1/queries", json=BODY, headers=HEADERS)
    body = r.json()
    assert r.status_code == 200 and body["status"] == "succeeded"
    assert body["result"]["total_rows"] == 2
    assert body["explanation"]["confidence"] == 1.0
    assert body["usage"]["tokens_used"] == 1200
    assert "LIMIT" not in body["query"]["sql"]  # internal row cap is not exposed


async def test_self_correction_after_rejected_sql(client: httpx.AsyncClient, fake_llm: FakeGateway) -> None:
    fake_llm.push(draft("SELECT * FROM events"))
    fake_llm.push(draft("SELECT eventName FROM cloudtrail WHERE userIdentitytype = 'Root'"))
    r = await client.post("/v1/queries", json=BODY, headers=HEADERS)
    body = r.json()
    assert body["status"] == "succeeded" and fake_llm.call_count == 2
    assert [a["outcome"] for a in body["trace"]["attempts"]] == ["sql_rejected", "ok"]
    assert "Unknown table" in fake_llm.calls[1].user  # the rejection reason is fed back


async def test_zero_rows_with_wrong_value_triggers_retry(client: httpx.AsyncClient, fake_llm: FakeGateway) -> None:
    fake_llm.push(draft("SELECT * FROM cloudtrail WHERE errorCode = 'UnauthorizedOperation'"))
    fake_llm.push(draft("SELECT * FROM cloudtrail WHERE errorCode = 'Client.UnauthorizedOperation'"))
    body = (await client.post("/v1/queries", json={**BODY, "include_results": False}, headers=HEADERS)).json()
    assert body["status"] == "succeeded" and body["result"] is None
    assert "'Client.UnauthorizedOperation'" in fake_llm.calls[1].user
    assert body["explanation"]["result_summary"].startswith("2 rows")


async def test_credits_running_out_midway_stops_retries(app: FastAPI, client: httpx.AsyncClient,
                                                        fake_llm: FakeGateway) -> None:
    class OneCallGuard:
        async def admit(self, attempt: int) -> Claim:
            if attempt > 1:
                raise CreditsExhausted("Token budget exhausted", retry_after_s=60)
            return Claim(attempt)

        async def finalize(self, claim: Claim, usage: LLMUsage | None, model: str | None) -> None:
            return None

    app.state.query_service._guard_factory = lambda user_id, request_id: OneCallGuard()
    fake_llm.push(draft("SELECT * FROM events"))
    body = (await client.post("/v1/queries", json=BODY, headers=HEADERS)).json()
    assert body["status"] == "failed" and body["error"]["code"] == "CREDITS_EXHAUSTED_MIDWAY"
    assert fake_llm.call_count == 1


@pytest.mark.parametrize(("headers", "body", "status"), [
    ({}, BODY, 401),
    (HEADERS, {"hypothesis": "  hi  "}, 422),
    (HEADERS, {**BODY, "id": "4"}, 422),
    (HEADERS, {**BODY, "max_rows": 10_000_000}, 422),
])
async def test_bad_requests_exit_before_the_llm(client: httpx.AsyncClient, fake_llm: FakeGateway,
                                                headers: dict[str, str], body: dict[str, Any], status: int) -> None:
    r = await client.post("/v1/queries", json=body, headers=headers)
    assert r.status_code == status and fake_llm.call_count == 0
