"""Builds the configured gateway (`LLM_PROVIDER`). Misconfiguration fails at startup, not on the first request."""

from app.core.config import Settings
from app.modules.llm.anthropic_gateway import AnthropicGateway
from app.modules.llm.claude_code_gateway import ClaudeCodeGateway
from app.modules.llm.types import LLMGateway


def build_gateway(settings: Settings) -> LLMGateway:
    if settings.llm_provider == "anthropic":
        api_key = settings.anthropic_api_key.get_secret_value()
        if not api_key:
            raise RuntimeError("LLM_PROVIDER=anthropic needs ANTHROPIC_API_KEY (or set LLM_PROVIDER=claude_code)")
        return AnthropicGateway(
            api_key=api_key, model=settings.llm_model, max_tokens=settings.llm_max_tokens,
            effort=settings.llm_effort, timeout_s=settings.llm_timeout_s,
        )
    return ClaudeCodeGateway(
        cli_path=settings.claude_cli_path, model=settings.llm_model, effort=settings.llm_effort,
        timeout_s=settings.llm_timeout_s, max_concurrency=settings.claude_cli_max_concurrency,
    )
