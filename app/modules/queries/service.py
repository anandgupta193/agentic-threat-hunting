"""Query service: request rules, then the generation harness, then the response DTO. No HTTP here."""

from collections.abc import Callable

from app.core.config import Settings
from app.core.context import current_request_id
from app.core.errors import AppError
from app.core.logging import get_logger, truncate
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

log = get_logger(__name__)

CreditGuardFactory = Callable[[str, str], CreditGuard]  # (user_id, request_id) -> guard


class InvalidQueryRequest(AppError):
    status_code = 422
    code = "VALIDATION_ERROR"
    log_level = "info"


class QueryService:
    def __init__(self, *, harness: GenerationHarness, settings: Settings, guard_factory: CreditGuardFactory) -> None:
        self._harness = harness
        self._settings = settings
        self._guard_factory = guard_factory

    async def generate(self, user_id: str, req: QueryRequest) -> QueryResponse:
        max_rows = req.max_rows or self._settings.max_result_rows
        if max_rows > self._settings.max_result_rows:
            raise InvalidQueryRequest(f"max_rows must be ≤ {self._settings.max_result_rows}",
                                      details={"max_rows": req.max_rows})
        request_id = current_request_id() or ""
        log.info("query_requested", hypothesis=truncate(req.hypothesis), include_results=req.include_results)
        outcome = await self._harness.run(
            hypothesis=req.hypothesis, title=req.title or "(none)", max_rows=max_rows,
            guard=self._guard_factory(user_id, request_id),
        )
        return self._to_response(request_id, req, outcome)

    def _to_response(self, request_id: str, req: QueryRequest, o: HarnessOutcome) -> QueryResponse:
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
            trace=o.trace.to_dict(),
            usage=UsageDTO(tokens_used=o.trace.tokens_used, tokens_remaining=None, window_start=None,
                           resets_at=None),
            prompt={"version": self._harness.prompts.version, "hash": self._harness.prompts.hash,
                    "model": o.models[-1] if o.models else self._harness.model},
        )
