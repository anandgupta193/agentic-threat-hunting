"""Shared fixtures. Integration tests need the project's Postgres (`make db-up`) and use POSTGRES_TEST_DB."""

import csv
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from app.core.config import Settings
from app.main import create_app
from app.modules.llm.fake_gateway import FakeGateway
from app.modules.query_engine.dataset import COLUMNS, build_database

FIXTURE_ROWS = [
    # eventName, userIdentitytype, errorCode, userAgent, sourceIPAddress
    ("ConsoleLogin", "Root", None, "Mozilla/5.0", "1.1.1.1"),
    ("RunInstances", "IAMUser", "Client.UnauthorizedOperation", "aws-cli/1.16 kali", "2.2.2.2"),
    ("RunInstances", "IAMUser", "Client.UnauthorizedOperation", "aws-cli/1.16 kali", "2.2.2.2"),
    ("ListBuckets", "IAMUser", "AccessDenied", "[S3Console/0.4]", "3.3.3.3"),
    ("GetCallerIdentity", "AssumedRole", None, "Boto3/1.9 parrot", "4.4.4.4"),
]


@pytest.fixture(scope="session")
def duckdb_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A tiny cloudtrail.duckdb built with the real build code, so tests never need the 1 GB CSV."""
    root = tmp_path_factory.mktemp("dataset")
    csv_path = root / "events.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for i, (name, kind, err, ua, ip) in enumerate(FIXTURE_ROWS):
            w.writerow({"eventID": f"evt-{i}", "eventTime": f"2020-01-0{i + 1}T00:00:00Z", "eventName": name,
                        "userIdentitytype": kind, "errorCode": err or "", "userAgent": ua, "sourceIPAddress": ip})
    db_path = root / "cloudtrail.duckdb"
    build_database(csv_path, db_path, threads=1, memory_limit="256MB")
    return db_path


@pytest.fixture(scope="session")
def settings(duckdb_path: Path) -> Settings:
    base = Settings()
    return base.model_copy(update={"database_url": base.test_db_url, "duckdb_path": duckdb_path})


@pytest.fixture
def fake_llm() -> FakeGateway:
    return FakeGateway()


@pytest.fixture
def app(settings: Settings, fake_llm: FakeGateway) -> FastAPI:
    return create_app(settings, llm=fake_llm)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
