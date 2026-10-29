"""Brief entry point for the evaluator. The implementation lives in `evaluation/`."""

from evaluation.metrics import compare
from evaluation.scorer import overall, score_response

__all__ = ["compare", "overall", "score_response"]
