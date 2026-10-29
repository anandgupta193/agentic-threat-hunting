"""Shared fixtures. Integration tests need the project's Postgres (`make db-up`) and use POSTGRES_TEST_DB."""

from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI

from app.core.config import Settings
from app.main import create_app


@pytest.fixture(scope="session")
def settings() -> Settings:
    base = Settings()
    return base.model_copy(update={"database_url": base.test_db_url, "anthropic_api_key": base.anthropic_api_key})


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
