"""Versioned prompt files (D27): prompts/<version>/{system,user_template,retry_template}.md.

Loaded once at startup. Missing files or placeholders fail fast. The content hash ties every stored result
to the exact prompt text that produced it. `PromptRegistry` is the seam for a Langfuse-backed registry later.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"
HASH_CHARS = 12

REQUIRED: dict[str, tuple[str, ...]] = {
    "system": ("schema_card",),
    "user_template": ("title", "hypothesis"),
    "retry_template": ("title", "hypothesis", "previous_sql", "error"),
}


def _fill(template: str, **values: str) -> str:
    # Plain replacement, not str.format: prompt text may legitimately contain braces (SQL, JSON).
    for key, value in values.items():
        template = template.replace("{" + key + "}", value)
    return template


@dataclass(frozen=True, slots=True)
class PromptSet:
    version: str
    hash: str
    system: str
    user_template: str
    retry_template: str

    def render_system(self, schema_card: str) -> str:
        return _fill(self.system, schema_card=schema_card)

    def render_user(self, *, title: str, hypothesis: str) -> str:
        return _fill(self.user_template, title=title, hypothesis=hypothesis)

    def render_retry(self, *, title: str, hypothesis: str, previous_sql: str, error: str) -> str:
        return _fill(self.retry_template, title=title, hypothesis=hypothesis, previous_sql=previous_sql, error=error)


class PromptRegistry(Protocol):
    def get(self, version: str) -> PromptSet: ...


class FilePromptRegistry:
    def __init__(self, root: Path = PROMPTS_DIR) -> None:
        self._root = root

    def get(self, version: str) -> PromptSet:
        folder = self._root / version
        if not folder.is_dir():
            raise RuntimeError(f"Prompt version '{version}' not found in {self._root}")
        texts: dict[str, str] = {}
        digest = hashlib.sha256()
        for name, placeholders in REQUIRED.items():
            path = folder / f"{name}.md"
            if not path.exists():
                raise RuntimeError(f"Prompt file missing: {path}")
            text = path.read_text(encoding="utf-8")
            missing = [p for p in placeholders if "{" + p + "}" not in text]
            if missing:
                raise RuntimeError(f"{path} is missing placeholders: {', '.join(missing)}")
            texts[name] = text
            digest.update(name.encode() + b"\0" + text.encode() + b"\0")
        return PromptSet(version=version, hash=digest.hexdigest()[:HASH_CHARS], **texts)
