"""P1: the brief's required rate-limit tests, plus claim expiry and the guards. Real Postgres, FakeGateway."""

import asyncio
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text

from app.core.clock import FakeClock
from app.core.config import Settings
from app.core.errors import CreditsContended
from app.main import create_app
from app.modules.llm.fake_gateway import FakeGateway
from tests.conftest import CLOCK_START, DEFAULT_USER, reset_db

BODY = {"title": "Root Access Through Console", "hypothesis": "Root user console login attempts"}
SQL = {"interpretation": "i", "reasoning": "r", "assumptions": [], "output_kind": "rows",
       "sql": "SELECT eventName FROM cloudtrail WHERE userIdentitytype = 'Root'"}


def as_user(user_id: str) -> dict[str, str]:
    return {"X-User-Id": user_id}


async def create_user(client: httpx.AsyncClient, user_id: str, token_limit: int) -> None:
    (await client.post("/v1/users", json={"user_id": user_id, "token_limit": token_limit})).raise_for_status()


async def audit_statuses(app: FastAPI, user_id: str) -> list[str]:  # sorted: the fake clock gives equal times
    async with app.state.db.engine.connect() as conn:
        rows = await conn.execute(text("SELECT status FROM query_requests WHERE user_id = :u"), {"u": user_id})
        return sorted(r[0] for r in rows)


async def test_request_within_limit_succeeds_and_records_usage(app: FastAPI, client: httpx.AsyncClient,
                                                               fake_llm: FakeGateway) -> None:
    fake_llm.push(SQL, input_tokens=1000, output_tokens=200)
    body = (await client.post("/v1/queries", json=BODY, headers=as_user(DEFAULT_USER))).json()
    assert body["status"] == "succeeded"
    assert body["usage"]["tokens_used"] == 1200 and body["usage"]["tokens_remaining"] == 200_000 - 1200
    assert body["usage"]["window_start"] == "2026-10-29T06:00:00Z"

    usage = (await client.get(f"/v1/users/{DEFAULT_USER}/usage", headers=as_user(DEFAULT_USER))).json()
    assert usage["totals"] == {"calls": 1, "input_tokens": 1000, "output_tokens": 200, "total_tokens": 1200}
    assert usage["calls"][0]["status"] == "completed" and usage["calls"][0]["request_id"] == body["request_id"]
    assert await audit_statuses(app, DEFAULT_USER) == ["succeeded"]


async def test_exhausted_credits_return_429_without_calling_the_llm(app: FastAPI, client: httpx.AsyncClient,
                                                                    fake_llm: FakeGateway) -> None:
    await create_user(client, "small", token_limit=1000)
    fake_llm.push(SQL, input_tokens=1000, output_tokens=200)  # admitted with 1000 left; overshoots by one call
    assert (await client.post("/v1/queries", json=BODY, headers=as_user("small"))).status_code == 200

    r = await client.post("/v1/queries", json=BODY, headers=as_user("small"))
    assert r.status_code == 429 and r.json()["error"]["code"] == "CREDITS_EXHAUSTED"
    assert r.headers["retry-after"] == "7200"  # 10:00 → the 12:00 reset
    assert r.json()["error"]["details"]["resets_at"] == "2026-10-29T12:00:00Z"
    assert fake_llm.call_count == 1
    assert await audit_statuses(app, "small") == ["rejected", "succeeded"]


async def test_credits_restored_after_window_reset(client: httpx.AsyncClient, fake_llm: FakeGateway,
                                                   clock: FakeClock) -> None:
    await create_user(client, "small", token_limit=1000)
    fake_llm.push(SQL, input_tokens=1000, output_tokens=200)
    await client.post("/v1/queries", json=BODY, headers=as_user("small"))
    assert (await client.post("/v1/queries", json=BODY, headers=as_user("small"))).status_code == 429

    clock.set(CLOCK_START.replace(hour=12))
    fake_llm.push(SQL)
    r = await client.post("/v1/queries", json=BODY, headers=as_user("small"))
    assert r.status_code == 200 and r.json()["usage"]["window_start"] == "2026-10-29T12:00:00Z"


async def test_concurrent_requests_cannot_overspend(app: FastAPI, client: httpx.AsyncClient,
                                                    fake_llm: FakeGateway, settings: Settings) -> None:
    limit, n = 20_000, 6
    await create_user(client, "busy", token_limit=limit)
    fake_llm.delay_s = 0.3  # every admitted call stays in flight while the others try to get in
    for _ in range(n):
        fake_llm.push(SQL, input_tokens=10_000, output_tokens=500)

    responses = await asyncio.gather(*[client.post("/v1/queries", json=BODY, headers=as_user("busy"))
                                       for _ in range(n)])
    codes = sorted(r.status_code for r in responses)
    # 20,000 left: 1st admitted; 2nd admitted (20,000 − 1 × 15,000 > 0); the rest are reserved away.
    assert codes == [200, 200] + [429] * (n - 2)
    assert {r.json()["error"]["code"] for r in responses if r.status_code == 429} == {"CREDITS_CONTENDED"}
    assert fake_llm.call_count == 2
    credits = (await client.get("/v1/users/busy/credits", headers=as_user("busy"))).json()
    assert credits["tokens_used"] == 21_000 <= limit + settings.max_call_tokens  # overshoot ≤ one call


async def test_usage_persists_across_restart(settings: Settings, clock: FakeClock) -> None:
    llm = FakeGateway()
    first = create_app(settings, clock=clock, llm=llm)
    async with first.router.lifespan_context(first):
        await reset_db(first.state.db)
        transport = httpx.ASGITransport(app=first)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            await create_user(c, "durable", token_limit=50_000)
            llm.push(SQL, input_tokens=3000, output_tokens=500)
            assert (await c.post("/v1/queries", json=BODY, headers=as_user("durable"))).status_code == 200

    second = create_app(settings, clock=clock, llm=FakeGateway())  # new engine, new pool, same database
    async with second.router.lifespan_context(second):
        transport = httpx.ASGITransport(app=second)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            credits = (await c.get("/v1/users/durable/credits", headers=as_user("durable"))).json()
    assert credits["tokens_used"] == 3500 and credits["tokens_remaining"] == 46_500


async def test_stale_pending_claim_expires(app: FastAPI, client: httpx.AsyncClient, clock: FakeClock,
                                           settings: Settings) -> None:
    """A process that crashed mid-call leaves a pending claim; it stops reserving credits after the TTL."""
    await create_user(client, "crashy", token_limit=20_000)
    async with app.state.db.engine.begin() as conn:
        await conn.execute(text("INSERT INTO query_requests (request_id, user_id, hypothesis, status) "
                                "VALUES ('req_crash', 'crashy', 'h', 'in_progress')"))
    credits = app.state.credit_service
    await credits.admit("crashy", "req_crash", 1)
    await credits.admit("crashy", "req_crash", 2)   # never finalized: the process "crashed"
    with pytest.raises(CreditsContended):
        await credits.admit("crashy", "req_crash", 3)

    clock.advance(seconds=settings.pending_ttl_s + 1)
    await credits.admit("crashy", "req_crash", 3)
    usage = (await client.get("/v1/users/crashy/usage", headers=as_user("crashy"))).json()
    assert [c["status"] for c in usage["calls"]] == ["expired", "expired", "pending"]


@pytest.mark.parametrize(("method", "path", "headers", "json", "status", "code"), [
    ("POST", "/v1/users", {}, {"user_id": DEFAULT_USER}, 409, "USER_EXISTS"),
    ("POST", "/v1/users", {}, {"user_id": "bad id!"}, 422, "VALIDATION_ERROR"),
    ("POST", "/v1/users", {}, {"token_limit": 10**12}, 422, "VALIDATION_ERROR"),
    ("GET", f"/v1/users/{DEFAULT_USER}/credits", {}, None, 401, "UNAUTHENTICATED"),
    ("GET", f"/v1/users/{DEFAULT_USER}/credits", {"X-User-Id": "bad id!"}, None, 400, "BAD_REQUEST"),
    ("GET", f"/v1/users/{DEFAULT_USER}/usage", {"X-User-Id": "someone-else"}, None, 403, "FORBIDDEN"),
    ("GET", "/v1/users/ghost/credits", {"X-User-Id": "ghost"}, None, 404, "USER_NOT_FOUND"),
    ("POST", "/v1/queries", {"X-User-Id": "ghost"}, BODY, 404, "USER_NOT_FOUND"),
])
async def test_guards_exit_early(client: httpx.AsyncClient, fake_llm: FakeGateway, method: str, path: str,
                                 headers: dict[str, str], json: dict[str, Any] | None, status: int,
                                 code: str) -> None:
    r = await client.request(method, path, headers=headers, json=json)
    assert (r.status_code, r.json()["error"]["code"]) == (status, code)
    assert fake_llm.call_count == 0
