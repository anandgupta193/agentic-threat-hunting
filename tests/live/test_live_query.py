"""Opt-in (D43): one real hypothesis through the configured real gateway and the real dataset.

    pytest -m live      # needs a provider key in .env and data/cloudtrail.duckdb
"""

import httpx
import pytest

from app.core.config import Settings
from app.main import create_app

pytestmark = pytest.mark.live


async def test_real_hypothesis_end_to_end() -> None:
    base = Settings()
    if not base.duckdb_path.exists():
        pytest.skip("data/cloudtrail.duckdb not built")
    app = create_app(base.model_copy(update={"database_url": base.test_db_url}))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://live", timeout=300) as client:
            r = await client.post("/v1/queries", headers={"X-User-Id": "live-test"}, json={
                "title": "Root Access Through Console",
                "hypothesis": "Root user console login attempts can be identified in CloudTrail logs",
                "max_rows": 100,
            })
    body = r.json()
    assert r.status_code == 200, body
    assert body["status"] == "succeeded", body["error"]
    assert body["result"]["total_rows"] > 0
    attempt = body["trace"]["attempts"][-1]
    assert attempt["input_tokens"] > 0 and attempt["output_tokens"] > 0
    assert body["usage"]["tokens_used"] == sum(a["input_tokens"] + a["output_tokens"]
                                               for a in body["trace"]["attempts"])
