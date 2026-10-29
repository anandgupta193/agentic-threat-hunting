"""Query service (§7.2): audit row → harness (credits admitted per LLM call) → audit outcome → response DTO.
No HTTP here."""

from collections.abc import Callable

from app.core.clock import Clock
from app.core.config import Settings
from app.core.context import current_request_id, new_request_id
from app.core.errors import AppError, CreditsError, UnprocessableError
from app.core.logging import get_logger, truncate
from app.db.engine import Database
from app.modules.credits.service import CreditService
from app.modules.harness.credit_guard import CreditGuard
from app.modules.harness.pipeline import GenerationHarness, HarnessOutcome
from app.modules.queries.dtos import (
    ErrorInfoDTO,
    ExplanationDTO,
    QueryDTO,
    QueryRequest,
    QueryResponse,
    ResultDTO,
    UsageDTO,
)
from app.modules.queries.repository import QueryCompletion, QueryRepository

log = get_logger(__name__)

CreditGuardFactory = Callable[[str, str], CreditGuard]  # (user_id, request_id) -> guard


class QueryService:
    def __init__(self, *, harness: GenerationHarness, settings: Settings, db: Database, clock: Clock,
                 credits: CreditService, guard_factory: CreditGuardFactory) -> None:
        self._harness = harness
        self._settings = settings
        self._db = db
        self._clock = clock
        self._credits = credits
        self._guard_factory = guard_factory
        self._repo = QueryRepository()

    async def generate(self, user_id: str, req: QueryRequest) -> QueryResponse:
        max_rows = req.max_rows or self._settings.max_result_rows
        if max_rows > self._settings.max_result_rows:
            raise UnprocessableError(f"max_rows must be ≤ {self._settings.max_result_rows}",
                                     details={"max_rows": req.max_rows})
        request_id = current_request_id() or new_request_id()
        log.info("query_requested", hypothesis=truncate(req.hypothesis), include_results=req.include_results)
        async with self._db.session() as s, s.begin():
            await self._repo.start(s, request_id=request_id, user_id=user_id, hypothesis=req.hypothesis,
                                   now=self._clock.now())
        try:
            outcome = await self._harness.run(
                hypothesis=req.hypothesis, title=req.title or "(none)", max_rows=max_rows,
                guard=self._guard_factory(user_id, request_id),
            )
        except CreditsError as exc:  # denied before any LLM call → 429
            await self._complete_quietly(request_id, QueryCompletion(status="rejected", error_code=exc.code))
            raise
        except AppError as exc:      # provider error / timeout → 502 / 504
            await self._complete_quietly(request_id, QueryCompletion(status="failed", error_code=exc.code))
            raise
        except Exception:
            await self._complete_quietly(request_id, QueryCompletion(status="failed", error_code="INTERNAL_ERROR"))
            raise

        trace = outcome.trace.to_dict()
        await self._complete(request_id, self._completion(outcome, trace["total_ms"]))
        credits = await self._credits.get_credits(user_id)
        usage = UsageDTO(tokens_used=outcome.trace.tokens_used, tokens_remaining=credits.tokens_remaining,
                         window_start=credits.window_start, resets_at=credits.resets_at)
        return self._to_response(request_id, req, outcome, trace, usage)

    async def _complete(self, request_id: str, completion: QueryCompletion) -> None:
        async with self._db.session() as s, s.begin():
            await self._repo.complete(s, request_id, completion, self._clock.now())

    async def _complete_quietly(self, request_id: str, completion: QueryCompletion) -> None:
        """On an error path the original exception matters more than the audit write; log and move on."""
        try:
            await self._complete(request_id, completion)
        except Exception as exc:
            log.error("query_audit_write_failed", status=completion.status, exc_type=type(exc).__name__,
                      error=str(exc))

    def _completion(self, o: HarnessOutcome, latency_ms: int) -> QueryCompletion:
        final_sql = o.validated.count_sql if o.validated else (o.draft.sql if o.draft else None)
        return QueryCompletion(
            status=o.status, error_code=o.error_code, final_sql=final_sql,
            confidence=o.explanation.confidence if o.explanation else None,
            row_count=o.result.total_rows if o.result and o.status == "succeeded" else None,
            attempts=len(o.trace.attempts), prompt_version=self._harness.prompts.version,
            prompt_hash=self._harness.prompts.hash, model=o.models[-1] if o.models else self._harness.model,
            latency_ms=latency_ms,
        )

    def _to_response(self, request_id: str, req: QueryRequest, o: HarnessOutcome, trace: dict,
                     usage: UsageDTO) -> QueryResponse:
        d, ex, res = o.draft, o.explanation, o.result
        result = None
        if req.include_results and res is not None and o.status == "succeeded":
            result = ResultDTO(columns=res.columns, rows=res.rows, row_count=res.row_count,
                               total_rows=res.total_rows, truncated=res.truncated)
        return QueryResponse(
            request_id=request_id,
            status=o.status,
            # the query as written (normalised), not the internal row cap the harness executed it with
            query=QueryDTO(sql=o.validated.count_sql if o.validated else (d.sql if d else None)),
            explanation=ExplanationDTO(
                interpretation=d.interpretation if d else None,
                reasoning=d.reasoning if d else None,
                assumptions=d.assumptions if d else [],
                output_kind=d.output_kind if d else None,
                confidence=ex.confidence if ex else None,
                confidence_reasons=ex.confidence_reasons if ex else [],
                result_summary=ex.result_summary if ex else None,
            ),
            result=result,
            error=ErrorInfoDTO(code=o.error_code, message=o.error_message) if o.error_code else None,
            trace=trace,
            usage=usage,
            prompt={"version": self._harness.prompts.version, "hash": self._harness.prompts.hash,
                    "model": o.models[-1] if o.models else self._harness.model},
        )
