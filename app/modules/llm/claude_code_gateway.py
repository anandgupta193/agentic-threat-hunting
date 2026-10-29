"""Claude via the local Claude Code CLI in headless mode, using the developer's own Claude subscription login.

For local development only, on a machine where `claude` is installed and logged in; evaluators use the
Anthropic API gateway. Each call runs `claude -p` as a subprocess:

- `--json-schema` gives schema-validated `structured_output`, the same contract as the API gateway
- `--tools ""`, `--strict-mcp-config`, `--setting-sources ""` and an empty working directory keep the
  call a single plain model completion: no tools, MCP servers, hooks, settings or CLAUDE.md
- `ANTHROPIC_API_KEY` is removed from the child environment so the subscription login is used
- token usage comes from the CLI's JSON `usage` block and is billed exactly like API usage (D9)
"""

import asyncio
import json
import os
import shutil
import tempfile
import time
from typing import Any

from app.core.logging import get_logger
from app.modules.llm.types import LLMError, LLMOutputError, LLMRequest, LLMResult, LLMTimeoutError, LLMUsage

log = get_logger(__name__)

MAX_STDERR_LOG_CHARS = 500


def _usage(raw: dict[str, Any] | None) -> LLMUsage:
    raw = raw or {}
    return LLMUsage(
        input_tokens=int(raw.get("input_tokens") or 0),
        output_tokens=int(raw.get("output_tokens") or 0),
        cache_creation_input_tokens=int(raw.get("cache_creation_input_tokens") or 0),
        cache_read_input_tokens=int(raw.get("cache_read_input_tokens") or 0),
    )


class ClaudeCodeGateway:
    provider = "claude_code"

    def __init__(self, *, cli_path: str, model: str, effort: str, timeout_s: float, max_concurrency: int) -> None:
        resolved = shutil.which(cli_path)
        if resolved is None:
            raise RuntimeError(f"Claude Code CLI not found ('{cli_path}'); install it or use LLM_PROVIDER=anthropic")
        self.model = model
        self._cli = resolved
        self._effort = effort
        self._timeout_s = timeout_s
        self._slots = asyncio.Semaphore(max_concurrency)
        self._workdir = tempfile.mkdtemp(prefix="claude-gw-")
        self._env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}

    def _argv(self, request: LLMRequest) -> list[str]:
        return [
            self._cli, "-p",
            "--output-format", "json",
            "--model", self.model,
            "--effort", self._effort,
            "--system-prompt", request.system,
            "--json-schema", json.dumps(request.output_schema),
            "--tools", "",
            "--strict-mcp-config",
            "--setting-sources", "",
            "--no-session-persistence",
        ]

    async def generate(self, request: LLMRequest) -> LLMResult:
        async with self._slots:
            t0 = time.perf_counter()
            proc = await asyncio.create_subprocess_exec(
                *self._argv(request),
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                cwd=self._workdir, env=self._env,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(request.user.encode()), self._timeout_s)
            except TimeoutError as exc:
                proc.kill()
                await proc.wait()
                log.error("llm_timeout", provider=self.provider, model=self.model, timeout_s=self._timeout_s)
                raise LLMTimeoutError("LLM call timed out") from exc
            latency_ms = int((time.perf_counter() - t0) * 1000)

        try:
            out = json.loads(stdout)
        except json.JSONDecodeError as exc:
            log.error("llm_cli_failed", provider=self.provider, exit_code=proc.returncode,
                      stderr=stderr.decode(errors="replace")[:MAX_STDERR_LOG_CHARS])
            raise LLMError("Claude Code CLI failed", details={"exit_code": proc.returncode}) from exc

        usage = _usage(out.get("usage"))
        if out.get("is_error") or out.get("subtype") != "success":
            log.error("llm_cli_error", provider=self.provider, subtype=out.get("subtype"),
                      api_status=out.get("api_error_status"), result=str(out.get("result"))[:MAX_STDERR_LOG_CHARS])
            raise LLMError("Claude Code CLI returned an error", usage=usage,
                           details={"subtype": out.get("subtype"), "status": out.get("api_error_status")})

        data = out.get("structured_output")
        if not isinstance(data, dict):
            log.error("llm_no_structured_output", provider=self.provider, stop_reason=out.get("stop_reason"))
            raise LLMOutputError("LLM did not return structured output", usage=usage)

        model = next(iter(out.get("modelUsage") or {}), self.model)
        return LLMResult(data=data, usage=usage, model=model, latency_ms=latency_ms, provider=self.provider,
                         meta={"session_id": out.get("session_id"), "cost_usd": out.get("total_cost_usd")})

    async def aclose(self) -> None:
        shutil.rmtree(self._workdir, ignore_errors=True)
