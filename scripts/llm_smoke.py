"""One real LLM call through the configured gateway, to check credentials and the output contract.

    python scripts/llm_smoke.py                      # uses LLM_PROVIDER from .env
    python scripts/llm_smoke.py --provider claude_code
"""

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.core.logging import configure_logging  # noqa: E402
from app.modules.llm.factory import build_gateway  # noqa: E402
from app.modules.llm.types import LLMRequest  # noqa: E402

SCHEMA = {
    "type": "object",
    "properties": {"sql": {"type": "string"}, "reasoning": {"type": "string"}},
    "required": ["sql", "reasoning"],
    "additionalProperties": False,
}


async def main(provider: str | None) -> int:
    settings = get_settings()
    if provider:
        settings = settings.model_copy(update={"llm_provider": provider})
    configure_logging(settings.log_level)
    gateway = build_gateway(settings)
    try:
        result = await gateway.generate(LLMRequest(
            system="You write DuckDB SQL over a table named cloudtrail(eventName VARCHAR, userIdentitytype VARCHAR).",
            user="Count Root user events per eventName.",
            output_schema=SCHEMA,
        ))
    finally:
        await gateway.aclose()
    print(json.dumps({
        "provider": result.provider, "model": result.model, "latency_ms": result.latency_ms,
        "data": result.data,
        "usage": {**asdict(result.usage), "billable_total": result.usage.billable_total},
        "meta": result.meta,
    }, indent=2))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=["anthropic", "openrouter", "claude_code"])
    sys.exit(asyncio.run(main(parser.parse_args().provider)))
