"""Renders the cached schema card (built by data-prep, stored in `_meta`) as compact text for the prompt.

Kept slim because it is sent on every LLM call: value names without counts, and only a few examples for
opaque ID columns no hypothesis filters on by value. The stored card keeps every value and count, so the
zero-row value check is unaffected. Data conventions and query rules live in the prompt files (D27).
"""

from typing import Any

MAX_VALUE_CHARS = 120
EXAMPLES = 3
OPAQUE_ID_COLUMNS = frozenset({"userIdentityprincipalId", "userIdentityaccessKeyId", "userIdentityaccountId"})


def _fmt(value: str) -> str:
    v = value if len(value) <= MAX_VALUE_CHARS else value[:MAX_VALUE_CHARS] + "…"
    return "'" + v.replace("'", "''") + "'"


def render_schema_card(card: dict[str, Any]) -> str:
    lines = [f"Table `{card['table']}` ({card['row_count']:,} rows). Every column is VARCHAR; empty = NULL.", ""]
    for c in card["columns"]:
        header = f"- {c['name']}: {c['distinct']:,} distinct, {c['null_rate']:.1%} NULL"
        values = ", ".join(_fmt(v["value"]) for v in c["values"])
        if c["kind"] == "timestamp":
            lines.append(f"{header}. ISO-8601 UTC text, from {_fmt(c['min'])} to {_fmt(c['max'])}")
        elif c["kind"] == "identifier" or c["name"] in OPAQUE_ID_COLUMNS:
            lines.append(f"{header}. Opaque identifier, e.g. "
                         + ", ".join(_fmt(v["value"]) for v in c["values"][:EXAMPLES]))
        elif c["kind"] == "categorical":
            lines.append(f"{header}. All values: {values}")
        else:
            lines.append(f"{header}. Most frequent first: {values}")
    return "\n".join(lines)
