"""The generation stages (§8). Each has one async `run()` with typed input/output and no HTTP or credit logic."""

from collections import Counter
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError
from sqlglot import exp

from app.core.config import Settings
from app.modules.harness.confidence import ConfidenceSignals, score_confidence
from app.modules.llm.prompt_registry import PromptSet
from app.modules.llm.types import LLMGateway, LLMOutputError, LLMRequest, LLMResult
from app.modules.query_engine.executor import DuckDBExecutor, QueryResult
from app.modules.query_engine.validator import ValidatedSql, validate
from app.modules.query_engine.value_check import MissingValue, ValueChecker

SUMMARY_MAX_COLUMNS = 3
TIME_COLUMN = "eventTime"


class GenerationDraft(BaseModel):
    """What the LLM must return (enforced by the JSON schema sent with every call)."""

    interpretation: str
    reasoning: str
    assumptions: list[str] = Field(default_factory=list)
    sql: str
    output_kind: Literal["rows", "aggregate"]


DRAFT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "interpretation": {"type": "string"},
        "reasoning": {"type": "string"},
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "sql": {"type": "string"},
        "output_kind": {"type": "string", "enum": ["rows", "aggregate"]},
    },
    "required": ["interpretation", "reasoning", "assumptions", "sql", "output_kind"],
    "additionalProperties": False,
}


@dataclass(frozen=True, slots=True)
class PromptInput:
    title: str
    hypothesis: str
    previous_sql: str | None = None
    error: str | None = None


class BuildPrompt:
    def __init__(self, prompts: PromptSet, schema_card_text: str) -> None:
        # Rendered once: the system prompt (rules + schema card) is identical for every call, so it caches.
        self._system = prompts.render_system(schema_card_text)
        self._prompts = prompts

    async def run(self, p: PromptInput) -> LLMRequest:
        if p.error is None:
            user = self._prompts.render_user(title=p.title, hypothesis=p.hypothesis)
        else:
            user = self._prompts.render_retry(title=p.title, hypothesis=p.hypothesis,
                                              previous_sql=p.previous_sql or "(none)", error=p.error)
        return LLMRequest(system=self._system, user=user, output_schema=DRAFT_SCHEMA)


class Generate:
    def __init__(self, llm: LLMGateway) -> None:
        self._llm = llm

    async def run(self, request: LLMRequest) -> tuple[GenerationDraft, LLMResult]:
        result = await self._llm.generate(request)
        try:
            return GenerationDraft.model_validate(result.data), result
        except ValidationError as exc:
            raise LLMOutputError("LLM output did not match the required fields", usage=result.usage,
                                 details={"errors": exc.errors(include_url=False)[:3]}) from exc


class Validate:
    async def run(self, sql: str, *, max_rows: int) -> ValidatedSql:
        return validate(sql, max_rows=max_rows)


class Execute:
    def __init__(self, executor: DuckDBExecutor) -> None:
        self._executor = executor

    async def run(self, validated: ValidatedSql, *, max_rows: int) -> QueryResult:
        return await self._executor.run(validated, max_rows=max_rows)


class ValueCheck:
    def __init__(self, checker: ValueChecker, enabled: bool) -> None:
        self._checker = checker
        self._enabled = enabled

    async def run(self, validated: ValidatedSql, result: QueryResult) -> list[MissingValue]:
        if not self._enabled or result.total_rows > 0:
            return []
        return await self._checker.missing_values(validated.ast)


@dataclass(frozen=True, slots=True)
class Explanation:
    confidence: float
    confidence_reasons: list[str]
    result_summary: str


def is_aggregate(tree: exp.Expr) -> bool:
    outer = tree.find(exp.Select)
    if outer is None:
        return False
    if outer.args.get("group"):
        return True
    return any(e.find(exp.AggFunc) and not e.find(exp.Window) for e in outer.expressions)


def summarize(result: QueryResult) -> str:
    """Deterministic one-line description of what was found."""
    parts = [f"{result.total_rows:,} rows" + (f" (first {result.row_count:,} shown; stats below cover those)"
                                              if result.truncated else "")]
    text_cols = [i for i, c in enumerate(result.columns) if c != TIME_COLUMN
                 and all(isinstance(r[i], str) or r[i] is None for r in result.rows)]
    shown = 0
    for i in text_cols:
        values = Counter(r[i] for r in result.rows if r[i] is not None)
        if values and len(values) < result.row_count:  # skip all-unique columns (ids): they say nothing
            parts.append(f"{len(values):,} distinct {result.columns[i]}")
            shown += 1
        if shown == SUMMARY_MAX_COLUMNS:
            break
    if TIME_COLUMN in result.columns:
        i = result.columns.index(TIME_COLUMN)
        times = sorted(r[i] for r in result.rows if isinstance(r[i], str))
        if times:
            parts.append(f"{TIME_COLUMN} {times[0][:10]} → {times[-1][:10]}")
    return " · ".join(parts)


class Explain:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def run(self, draft: GenerationDraft, validated: ValidatedSql, result: QueryResult,
                  attempts: int) -> Explanation:
        signals = ConfidenceSignals(
            attempts=attempts,
            zero_rows=result.total_rows == 0,
            assumptions=len(draft.assumptions),
            truncated=result.truncated,
            shape_mismatch=(draft.output_kind == "aggregate") != is_aggregate(validated.ast),
        )
        confidence, reasons = score_confidence(signals, self._settings)
        return Explanation(confidence=confidence, confidence_reasons=reasons, result_summary=summarize(result))
