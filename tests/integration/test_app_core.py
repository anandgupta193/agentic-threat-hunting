"""P0 smoke: the app boots against Postgres, echoes a request id and uses the error envelope."""

import httpx


async def test_healthz_ok_with_request_id(client: httpx.AsyncClient) -> None:
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["checks"] == {"db": True}
    assert r.headers["x-request-id"].startswith("req_")


async def test_errors_use_envelope(client: httpx.AsyncClient) -> None:
    r = await client.get("/nope")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "ROUTE_NOT_FOUND"
    assert r.json()["request_id"] == r.headers["x-request-id"]
