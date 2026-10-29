"""Renders the cached schema card (built by data-prep, stored in `_meta`) as compact text for the prompt.

Data conventions and query rules live in the versioned prompt files (D27); this is only the data description.
"""

from typing import Any

MAX_VALUE_CHARS = 120


def _fmt(value: str) -> str:
    v = value if len(value) <= MAX_VALUE_CHARS else value[:MAX_VALUE_CHARS] + "…"
    return "'" + v.replace("'", "''") + "'"


def render_schema_card(card: dict[str, Any]) -> str:
    lines = [f"Table `{card['table']}` ({card['row_count']:,} rows). Every column is VARCHAR; empty = NULL.", ""]
    for c in card["columns"]:
        header = f"- {c['name']}: {c['distinct']:,} distinct, {c['null_rate']:.1%} NULL"
        values = ", ".join(f"{_fmt(v['value'])} ({v['count']:,})" for v in c["values"])
        if c["kind"] == "timestamp":
            lines.append(f"{header}. ISO-8601 UTC text, from {_fmt(c['min'])} to {_fmt(c['max'])}")
        elif c["kind"] == "categorical":
            lines.append(f"{header}. All values: {values}")
        elif c["kind"] == "identifier":
            lines.append(f"{header}. Unique identifier, e.g. {', '.join(_fmt(v['value']) for v in c['values'])}")
        else:
            lines.append(f"{header}. Most frequent: {values}")
    return "\n".join(lines)
