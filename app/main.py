"""App factory + lifespan. Singletons (DB, clock; later DuckDB, schema card, LLM) live on `app.state`."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.middleware.gzip import GZipMiddleware

from app.common.deps import get_db
from app.core.clock import Clock, SystemClock
from app.core.config import Settings, get_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestContextMiddleware
from app.db.engine import Database

log = get_logger(__name__)


def load_settings() -> Settings:
    try:
        return get_settings()
    except ValidationError as exc:
        configure_logging()
        log.critical("config_invalid", errors=exc.errors(include_url=False, include_input=False))
        raise


def create_app(settings: Settings | None = None, clock: Clock | None = None) -> FastAPI:
    settings = settings or load_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        db = Database(settings.db_url, pool_size=settings.db_pool_size)
        try:
            await db.apply_schema()
        except Exception as exc:
            log.critical("startup_db_failed", exc_type=type(exc).__name__, error=str(exc))
            await db.dispose()
            raise
        app.state.settings = settings
        app.state.db = db
        app.state.clock = clock or SystemClock()
        log.info("startup_complete", model=settings.llm_model, prompt_version=settings.prompt_version)
        try:
            yield
        finally:
            await db.dispose()
            log.info("shutdown_complete")

    app = FastAPI(title="Agentic Threat Hunting API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(RequestContextMiddleware)
    register_error_handlers(app)

    @app.get("/healthz", tags=["ops"])
    async def healthz(db: Annotated[Database, Depends(get_db)]) -> JSONResponse:
        checks = {"db": await db.ping()}
        ok = all(checks.values())
        return JSONResponse(status_code=200 if ok else 503,
                            content={"status": "ok" if ok else "degraded", "checks": checks})

    return app
