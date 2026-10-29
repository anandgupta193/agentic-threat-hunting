"""Deterministic confidence (D34): start at 1.0, subtract for objective risk signals, list every reason.

The LLM never rates itself. Same inputs always give the same score.
"""

from dataclasses import dataclass

from app.core.config import Settings


@dataclass(frozen=True, slots=True)
class ConfidenceSignals:
    attempts: int          # LLM calls used (1 = first try)
    zero_rows: bool        # ran fine, values verified, but nothing matched
    assumptions: int
    truncated: bool
    shape_mismatch: bool   # output_kind contradicts the SQL (e.g. "aggregate" without GROUP BY)


def score_confidence(s: ConfidenceSignals, settings: Settings) -> tuple[float, list[str]]:
    score = 1.0
    reasons: list[str] = []

    retries = max(0, s.attempts - 1)
    if retries:
        penalty = settings.confidence_penalty_retry * retries
        score -= penalty
        reasons.append(f"needed {retries} self-correction(s) (-{penalty:.2f})")
    else:
        reasons.append("valid on first attempt")

    if s.zero_rows:
        score -= settings.confidence_penalty_zero_rows
        reasons.append(f"query returned 0 rows (-{settings.confidence_penalty_zero_rows:.2f})")

    if s.assumptions:
        penalty = min(settings.confidence_penalty_assumption * s.assumptions,
                      settings.confidence_penalty_assumption_max)
        score -= penalty
        reasons.append(f"{s.assumptions} assumption(s) made (-{penalty:.2f})")
    else:
        reasons.append("no assumptions needed")

    if s.truncated:
        score -= settings.confidence_penalty_truncated
        reasons.append(f"result truncated (-{settings.confidence_penalty_truncated:.2f})")

    if s.shape_mismatch:
        penalty = settings.confidence_penalty_shape_mismatch
        score -= penalty
        reasons.append(f"declared output kind does not match the SQL (-{penalty:.2f})")

    return round(min(1.0, max(0.0, score)), 2), reasons
