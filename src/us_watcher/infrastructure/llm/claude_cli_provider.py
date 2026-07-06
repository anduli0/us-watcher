"""Claude Code CLI-backed LLM provider (subscription auth; zero API credits).

Runs the locally installed ``claude`` CLI headless (``claude -p``) so the LLM
prose (chief house view, brief rewrite) is billed to the owner's Claude
subscription instead of Anthropic API credits. Selected via
``LLM_PROVIDER=claude_cli`` (or ``auto`` with no API key).

Auth precedence inside the child process:
  1. ``CLAUDE_CODE_OAUTH_TOKEN`` from settings (minted ONCE interactively with
     ``claude setup-token`` — long-lived, headless-safe), else
  2. the CLI's own stored login (``~/.claude/.credentials.json``).
Any inherited ``ANTHROPIC_API_KEY`` env var is STRIPPED from the child env so a
dead/exhausted key can never shadow subscription auth (the exact failure that
silently degraded the watchers to mock prose).

Token-usage hygiene: the CLI runs in an empty scratch directory (no CLAUDE.md /
repo context gets loaded), with ``--max-turns 1`` and cheap model aliases
(``sonnet`` prose / ``haiku`` fast) — each call is a single small completion.

Like every provider here it NEVER raises: on any failure (CLI missing, auth
dead, timeout, bad JSON) it degrades to the deterministic mock result, whose
empty text lets callers keep their deterministic fallback prose.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from us_watcher.config import get_settings
from us_watcher.infrastructure.llm.base import LLMResult, StructuredPrompt
from us_watcher.infrastructure.llm.mock import MockLLMProvider
from us_watcher.logging_config import get_logger

log = get_logger(__name__)


class ClaudeCLIProvider:
    name = "claude_cli"
    is_mock = False

    def __init__(self) -> None:
        self._settings = get_settings()
        self._mock = MockLLMProvider()
        self._exe: str | None = None
        # Empty, stable working dir so the CLI never ingests project context.
        self._cwd = Path(tempfile.gettempdir()) / "usw-claude-cli"
        try:
            self._cwd.mkdir(parents=True, exist_ok=True)
        except OSError:
            self._cwd = Path(tempfile.gettempdir())

    def _model_for(self, role: str) -> str:
        return self._settings.llm_cli_fast_model if role == "fast" else self._settings.llm_cli_model

    def _resolve_exe(self) -> str | None:
        if self._exe is None:
            self._exe = shutil.which(self._settings.claude_cli_path)
        return self._exe

    def _child_env(self) -> dict[str, str]:
        env = dict(os.environ)
        # A stale key here poisons CLI auth (401) — subscription OAuth must win.
        # Claude Code session-injected vars are scrubbed too: a child `claude -p`
        # inherits them when the server is launched from inside a session, and
        # they route auth to the (unavailable) host session -> 401.
        for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
                    "CLAUDE_CODE_SDK_HAS_HOST_AUTH_REFRESH", "CLAUDECODE",
                    "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT"):
            env.pop(var, None)
        token = self._settings.claude_code_oauth_token.get_secret_value()
        if token:
            env["CLAUDE_CODE_OAUTH_TOKEN"] = token
        env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
        env["DISABLE_AUTOUPDATER"] = "1"
        return env

    async def _run_cli(self, system: str, user: str, *, role: str) -> dict[str, Any] | None:
        """One headless CLI completion; parsed result JSON or None on failure."""
        exe = self._resolve_exe()
        if exe is None:
            log.warning("claude_cli.not_found", path=self._settings.claude_cli_path)
            return None
        cmd = [
            exe, "-p", "--output-format", "json", "--max-turns", "1",
            "--model", self._model_for(role), "--system-prompt", system,
        ]
        # Windows npm shims are .cmd/.ps1 batch wrappers — route through cmd.exe.
        if exe.lower().endswith((".cmd", ".bat")):
            cmd = ["cmd", "/c", *cmd]

        def _call() -> subprocess.CompletedProcess[str]:
            return subprocess.run(  # noqa: S603 — fixed argv, prompt via stdin
                cmd, input=user, capture_output=True, text=True, encoding="utf-8",
                errors="replace", cwd=str(self._cwd), env=self._child_env(),
                timeout=self._settings.llm_cli_timeout_seconds,
            )

        try:
            proc = await asyncio.to_thread(_call)
        except (subprocess.TimeoutExpired, OSError) as exc:
            log.warning("claude_cli.exec_failed", error=str(exc)[:200])
            return None
        if proc.returncode != 0:
            log.warning("claude_cli.nonzero_exit", code=proc.returncode,
                        stderr=(proc.stderr or "")[:300], stdout=(proc.stdout or "")[:200])
            return None
        out = (proc.stdout or "").strip()
        try:
            data: dict[str, Any] = json.loads(out)
        except json.JSONDecodeError:
            # Tolerate stray warning lines around the JSON payload.
            start, end = out.find("{"), out.rfind("}")
            if start < 0 or end <= start:
                log.warning("claude_cli.bad_output", stdout=out[:300])
                return None
            try:
                data = json.loads(out[start : end + 1])
            except json.JSONDecodeError:
                log.warning("claude_cli.bad_output", stdout=out[:300])
                return None
        if data.get("is_error"):
            log.warning("claude_cli.result_error", subtype=data.get("subtype"),
                        result=str(data.get("result"))[:300])
            return None
        return data

    @staticmethod
    def _usage(data: dict[str, Any]) -> tuple[int, int]:
        usage = data.get("usage") or {}
        return int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0)

    async def generate_text(
        self, system: str, user: str, *, role: str = "editor", max_tokens: int = 1024
    ) -> LLMResult:
        data = await self._run_cli(system, user, role=role)
        text = str((data or {}).get("result") or "").strip()
        if not data or not text:
            return await self._mock.generate_text(system, user, role=role, max_tokens=max_tokens)
        in_tok, out_tok = self._usage(data)
        return LLMResult(
            text=text, model=self._model_for(role), provider=self.name, is_mock=False,
            input_tokens=in_tok, output_tokens=out_tok,
        )

    async def generate_structured(self, prompt: StructuredPrompt, *, role: str = "reasoning") -> LLMResult:
        system = (
            prompt.system
            + "\nRespond with ONLY a single JSON object that conforms to this JSON Schema"
            " — no prose, no code fences:\n"
            + json.dumps(prompt.json_schema, ensure_ascii=False)
        )
        data = await self._run_cli(system, prompt.user, role=role)
        raw = str((data or {}).get("result") or "").strip()
        if data and raw:
            if raw.startswith("```"):
                raw = raw.strip("`\n")
                raw = raw.split("\n", 1)[1] if "\n" in raw else raw
            try:
                start, end = raw.find("{"), raw.rfind("}")
                parsed = json.loads(raw[start : end + 1]) if start >= 0 else None
            except (json.JSONDecodeError, ValueError):
                parsed = None
            if isinstance(parsed, dict):
                in_tok, out_tok = self._usage(data)
                return LLMResult(
                    text="", data=parsed, model=self._model_for(role), provider=self.name,
                    is_mock=False, input_tokens=in_tok, output_tokens=out_tok,
                )
        return await self._mock.generate_structured(prompt, role=role)
