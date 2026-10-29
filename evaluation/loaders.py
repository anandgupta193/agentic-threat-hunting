"""Inputs: the hypotheses and the answer key. The answer key is read only through the brief's `utils.py`."""

import json
from dataclasses import dataclass
from pathlib import Path

from evaluation.normalizers import Table
from utils import load_hypotheses_outcomes

ROOT = Path(__file__).resolve().parents[1]
HYPOTHESES_PATH = ROOT / "hypotheses.json"
OUTCOMES_PATH = ROOT / "hypotheses_outcomes.json"
NOTES_PATH = Path(__file__).resolve().parent / "notes.json"


@dataclass(frozen=True, slots=True)
class Hypothesis:
    id: str
    name: str
    text: str


def load_hypotheses(path: Path = HYPOTHESES_PATH) -> list[Hypothesis]:
    items = json.loads(path.read_text(encoding="utf-8"))
    return [Hypothesis(id=str(h["id"]), name=h["name"], text=h["hypothesis"]) for h in items]


def load_expected(path: Path = OUTCOMES_PATH) -> dict[str, Table]:
    frames = load_hypotheses_outcomes(str(path))
    return {hid: Table.build(list(df.columns), df.itertuples(index=False, name=None)) for hid, df in frames.items()}


def load_notes(path: Path = NOTES_PATH) -> dict[str, str]:
    """Engineer notes on answer-key scoping (D35), keyed by hypothesis id. Report text only, never scored."""
    if not path.exists():
        return {}
    notes: dict[str, str] = json.loads(path.read_text(encoding="utf-8"))
    return {k: v for k, v in notes.items() if not k.startswith("_")}
