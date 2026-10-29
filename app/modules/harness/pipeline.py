"""Generation harness (§8): Build prompt → Generate → Validate → Execute → Value check → Explain,
with self-correction. Every attempt is a separately admitted and billed LLM call (D12).

Correctable failures (SQL rejected, DuckDB error/timeout, a filter value that doesn't exist, malformed LLM
output) are fed back to the LLM while attempts remain. Provider failures (502/504) end the request.
"""

from dataclasses import dataclass, field
from typing import Literal

from app.core.config import Settings
from app.core.errors import CreditsError
from app.core.logging import get_logger, truncate
from app.modules.harness.credit_guard import CreditGuard
from app.modules.harness.stages import (
    BuildPrompt,
    Execute,
    Explain,
    Explanation,
    Generate,
    GenerationDraft,
    PromptInput,
    Validate,
    ValueCheck,
)
from app.modules.harness.trace import AttemptTrace, Trace
from app.modules.llm.prompt_registry import PromptSet
from app.modules.llm.types import LLMError, LLMGateway, LLMOutputError, LLMTimeoutError, LLMUsage
from app.modules.query_engine.executor import DuckDBExecutor, QueryFailed, QueryResult, QueryTimeout
from app.modules.query_engine.validator import SqlRejected, ValidatedSql
from app.modules.query_engine.value_check import ValueChecker

log = get_logger(__name__)

MAX_QUERY_TIMEOUTS = 2  # a timeout is fed back once ("simplify / aggregate"); a second one ends the request


@dataclass(slots=True)
class HarnessOutcome:
    status: Literal["succeeded", "failed"]
    trace: Trace
    draft: GenerationDraft | None = None
    validated: ValidatedSql | None = None
    result: QueryResult | None = None
    explanation: Explanation | None = None
    error_code: str | None = None
    error_message: str | None = None
    models: list[str] = field(default_factory=list)


class GenerationHarness:
    def __init__(self, *, settings: Settings, prompts: PromptSet, schema_card_text: str, llm: LLMGateway,
                 executor: DuckDBExecutor, value_checker: ValueChecker) -> None:
        self.prompts = prompts
        self.model = llm.model
        self._max_attempts = 1 + settings.max_self_correct
        self._build = BuildPrompt(prompts, schema_card_text)
        self._generate = Generate(llm)
        self._validate = Validate()
        self._execute = Execute(executor)
        self._value_check = ValueCheck(value_checker, settings.zero_row_value_check)
        self._explain = Explain(settings)

    async def run(self, *, hypothesis: str, title: str, max_rows: int, guard: CreditGuard) -> HarnessOutcome:
        trace = Trace()
        outcome = HarnessOutcome(status="failed", trace=trace)
        feedback: PromptInput = PromptInput(title=title, hypothesis=hypothesis)
        timeouts = 0

        for n in range(1, self._max_attempts + 1):
            # --- admit (credits) -------------------------------------------------------------
            try:
                claim = await guard.admit(n)
            except CreditsError:
                if n == 1:
                    raise  # nothing spent yet: the caller returns 429 and the LLM is never called
                log.info("self_correction_stopped_no_credits", attempt=n)
                outcome.error_code = "CREDITS_EXHAUSTED_MIDWAY"
                outcome.error_message = "Credits ran out before the query could be corrected"
                return outcome
            attempt = AttemptTrace(attempt=n)
            trace.attempts.append(attempt)

            # --- build + generate ------------------------------------------------------------
            with trace.stage("build_prompt"):
                request = await self._build.run(feedback)
            try:
                with trace.stage("generate"):
                    draft, llm_result = await self._generate.run(request)
            except LLMOutputError as exc:
                await guard.finalize(claim, exc.usage, self.model)
                self._record_usage(attempt, exc.usage)
                attempt.outcome, attempt.error = "bad_output", exc.message
                feedback = PromptInput(title, hypothesis, feedback.previous_sql,
                                       "Your answer did not contain every required field in the required format.")
                continue
            except (LLMError, LLMTimeoutError) as exc:
                await guard.finalize(claim, getattr(exc, "usage", None), self.model)
                attempt.outcome, attempt.error = "llm_error", exc.message
                raise
            await guard.finalize(claim, llm_result.usage, llm_result.model)
            self._record_usage(attempt, llm_result.usage, llm_result.latency_ms)
            outcome.models.append(llm_result.model)
            outcome.draft = draft
            attempt.sql = draft.sql

            # --- validate ------------------------------------------------------------------------
            try:
                with trace.stage("validate"):
                    validated = await self._validate.run(draft.sql, max_rows=max_rows)
            except SqlRejected as exc:
                log.warning("sql_rejected", attempt=n, rule=exc.rule, reason=exc.reason)
                attempt.outcome, attempt.error = "sql_rejected", exc.reason
                feedback = PromptInput(title, hypothesis, draft.sql, exc.reason)
                continue
            outcome.validated = validated

            # --- execute -------------------------------------------------------------------------
            try:
                with trace.stage("execute"):
                    result = await self._execute.run(validated, max_rows=max_rows)
            except QueryTimeout as exc:
                timeouts += 1
                attempt.outcome, attempt.error = "timeout", str(exc)
                if timeouts >= MAX_QUERY_TIMEOUTS:
                    break
                feedback = PromptInput(title, hypothesis, draft.sql, str(exc))
                continue
            except QueryFailed as exc:
                attempt.outcome, attempt.error = "execution_error", f"DuckDB error: {exc}"
                feedback = PromptInput(title, hypothesis, draft.sql, attempt.error)
                continue
            outcome.result = result

            # --- zero-row value check --------------------------------------------------------------
            with trace.stage("value_check"):
                missing = await self._value_check.run(validated, result)
            if missing:
                problem = "The query returned 0 rows because: " + "; ".join(m.describe() for m in missing)
                log.info("zero_row_missing_values", attempt=n, missing=[m.describe() for m in missing])
                attempt.outcome, attempt.error = "zero_rows_missing_value", problem
                feedback = PromptInput(title, hypothesis, draft.sql, problem)
                continue

            # --- explain ---------------------------------------------------------------------------
            with trace.stage("explain"):
                outcome.explanation = await self._explain.run(draft, validated, result, attempts=n)
            attempt.outcome = "ok"
            outcome.status = "succeeded"
            log.info("generation_succeeded", attempts=n, rows=result.total_rows,
                     confidence=outcome.explanation.confidence, hypothesis=truncate(hypothesis))
            return outcome

        last = trace.attempts[-1] if trace.attempts else None
        outcome.error_code = "QUERY_TIMEOUT" if last and last.outcome == "timeout" else "SELF_CORRECTION_EXHAUSTED"
        outcome.error_message = last.error if last else "No attempt was made"
        log.warning("generation_failed", attempts=len(trace.attempts), error_code=outcome.error_code,
                    error=truncate(outcome.error_message or ""))
        return outcome

    @staticmethod
    def _record_usage(attempt: AttemptTrace, usage: LLMUsage | None, latency_ms: int = 0) -> None:
        if usage is not None:
            attempt.input_tokens = usage.billable_input_tokens
            attempt.output_tokens = usage.output_tokens
        attempt.latency_ms = latency_ms
