"""App factory + lifespan. Singletons (DB, clock, LLM, DuckDB executor, schema card) live on `app.state`."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Request
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
from app.modules.harness.credit_guard import UnmeteredCreditGuard
from app.modules.harness.pipeline import GenerationHarness
from app.modules.llm.factory import build_gateway
from app.modules.llm.prompt_registry import FilePromptRegistry
from app.modules.llm.types import LLMGateway
from app.modules.queries.controller import router as queries_router
from app.modules.queries.service import QueryService
from app.modules.query_engine.executor import DuckDBExecutor
from app.modules.query_engine.schema_card import render_schema_card
from app.modules.query_engine.value_check import ValueChecker

log = get_logger(__name__)


def load_settings() -> Settings:
    try:
        return get_settings()
    except ValidationError as exc:
        configure_logging()
        log.critical("config_invalid", errors=exc.errors(include_url=False, include_input=False))
        raise


def create_app(settings: Settings | None = None, clock: Clock | None = None,
               llm: LLMGateway | None = None) -> FastAPI:
    settings = settings or load_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            prompts = FilePromptRegistry().get(settings.prompt_version)
        except RuntimeError as exc:
            log.critical("startup_prompts_failed", prompt_version=settings.prompt_version, error=str(exc))
            raise
        try:
            executor = DuckDBExecutor(settings.duckdb_path, threads=settings.duckdb_threads,
                                      memory_limit=settings.duckdb_memory_limit, timeout_s=settings.query_timeout_s)
            schema_card = executor.schema_card()
        except Exception as exc:
            log.critical("startup_dataset_failed", path=str(settings.duckdb_path), error=str(exc))
            raise
        try:
            gateway = llm or build_gateway(settings)
        except RuntimeError as exc:
            log.critical("startup_llm_failed", provider=settings.llm_provider, error=str(exc))
            executor.close()
            raise
        db = Database(settings.db_url, pool_size=settings.db_pool_size)
        try:
            await db.apply_schema()
        except Exception as exc:
            log.critical("startup_db_failed", exc_type=type(exc).__name__, error=str(exc))
            await db.dispose()
            await gateway.aclose()
            executor.close()
            raise
        app.state.settings = settings
        app.state.db = db
        app.state.clock = clock or SystemClock()
        app.state.llm = gateway
        app.state.executor = executor
        app.state.schema_card = schema_card
        app.state.schema_card_text = render_schema_card(schema_card)
        app.state.value_checker = ValueChecker(schema_card, executor)
        harness = GenerationHarness(settings=settings, prompts=prompts, schema_card_text=app.state.schema_card_text,
                                    llm=gateway, executor=executor, value_checker=app.state.value_checker)
        # Credits are metered per LLM attempt through this factory; P1 swaps in the Postgres-backed guard.
        app.state.query_service = QueryService(harness=harness, settings=settings,
                                               guard_factory=lambda user_id, request_id: UnmeteredCreditGuard())
        log.info("startup_complete", llm_provider=gateway.provider, model=gateway.model,
                 prompt_version=prompts.version, prompt_hash=prompts.hash, dataset_rows=schema_card["row_count"])
        try:
            yield
        finally:
            await gateway.aclose()
            await db.dispose()
            executor.close()
            log.info("shutdown_complete")

    app = FastAPI(title="Agentic Threat Hunting API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(RequestContextMiddleware)
    register_error_handlers(app)
    app.include_router(queries_router)

    @app.get("/healthz", tags=["ops"])
    async def healthz(request: Request, db: Annotated[Database, Depends(get_db)]) -> JSONResponse:
        checks = {"db": await db.ping(), "duckdb": request.app.state.executor.ping()}
        ok = all(checks.values())
        llm: LLMGateway = request.app.state.llm
        return JSONResponse(status_code=200 if ok else 503, content={
            "status": "ok" if ok else "degraded", "checks": checks,
            "llm": {"provider": llm.provider, "model": llm.model},
        })

    return app
