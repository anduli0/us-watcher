"""ClaudeCLIProvider — subscription-billed CLI path: env hygiene, parsing,
and graceful degradation to the deterministic mock (never raises)."""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

from us_watcher.infrastructure.llm import claude_cli_provider as mod
from us_watcher.infrastructure.llm.base import StructuredPrompt
from us_watcher.infrastructure.llm.claude_cli_provider import ClaudeCLIProvider


def _cli_json(result: str, *, is_error: bool = False) -> str:
    return json.dumps({
        "type": "result", "subtype": "success", "is_error": is_error,
        "result": result, "usage": {"input_tokens": 11, "output_tokens": 7},
    })


@pytest.fixture
def provider(monkeypatch) -> ClaudeCLIProvider:
    p = ClaudeCLIProvider()
    monkeypatch.setattr(p, "_resolve_exe", lambda: r"C:\fake\claude.cmd")
    return p


def _capture_run(monkeypatch, stdout: str, *, returncode: int = 0) -> dict:
    seen: dict = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        seen["kwargs"] = kwargs
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    return seen


async def test_generate_text_parses_result_and_usage(provider, monkeypatch):
    seen = _capture_run(monkeypatch, _cli_json("House view prose."))
    res = await provider.generate_text("sys", "user", role="editor")
    assert res.text == "House view prose."
    assert (res.input_tokens, res.output_tokens) == (11, 7)
    assert res.provider == "claude_cli" and res.is_mock is False
    # The exe is invoked directly, never wrapped in ["cmd", "/c", ...]: CMD
    # metacharacters (&, |, ") in the system-prompt arg would otherwise break
    # (e.g. "S&P 500" runs "P 500"). A .cmd shim is handled via shell=True.
    assert seen["cmd"][0] == r"C:\fake\claude.cmd"
    assert seen["cmd"][:2] != ["cmd", "/c"]
    assert seen["kwargs"].get("shell") is (mod.sys.platform == "win32")
    assert "--max-turns" in seen["cmd"] and "-p" in seen["cmd"]
    # Prompt travels via stdin (no argv length/quoting hazards).
    assert seen["kwargs"]["input"] == "user"


async def test_child_env_strips_dead_key_and_session_vars(provider, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-dead")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://session-proxy")
    monkeypatch.setenv("CLAUDE_CODE_SDK_HAS_HOST_AUTH_REFRESH", "1")
    env = provider._child_env()
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "CLAUDE_CODE_SDK_HAS_HOST_AUTH_REFRESH"):
        assert var not in env


async def test_cli_error_result_degrades_to_mock(provider, monkeypatch):
    _capture_run(monkeypatch, _cli_json("401 auth failed", is_error=True))
    res = await provider.generate_text("sys", "user")
    assert res.is_mock is True and res.text == ""


async def test_nonzero_exit_degrades_to_mock(provider, monkeypatch):
    _capture_run(monkeypatch, "boom", returncode=1)
    res = await provider.generate_text("sys", "user")
    assert res.is_mock is True and res.text == ""


async def test_timeout_degrades_to_mock(provider, monkeypatch):
    def raise_timeout(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd="claude", timeout=1)

    monkeypatch.setattr(mod.subprocess, "run", raise_timeout)
    res = await provider.generate_text("sys", "user")
    assert res.is_mock is True


async def test_missing_cli_degrades_to_mock(monkeypatch):
    p = ClaudeCLIProvider()
    monkeypatch.setattr(p, "_resolve_exe", lambda: None)
    res = await p.generate_text("sys", "user")
    assert res.is_mock is True


async def test_generate_structured_parses_json(provider, monkeypatch):
    _capture_run(monkeypatch, _cli_json('{"direction": 0.4}'))
    prompt = StructuredPrompt(system="s", user="u", json_schema={"type": "object"})
    res = await provider.generate_structured(prompt)
    assert res.data == {"direction": 0.4} and res.is_mock is False


async def test_generate_structured_bad_json_degrades_to_mock(provider, monkeypatch):
    _capture_run(monkeypatch, _cli_json("not json at all"))
    prompt = StructuredPrompt(system="s", user="u SEED= {}", json_schema={"type": "object"})
    res = await provider.generate_structured(prompt)
    assert res.is_mock is True


def test_factory_selects_cli_provider(monkeypatch):
    from us_watcher.config import get_settings
    from us_watcher.infrastructure.llm.factory import get_llm_provider

    settings = get_settings()
    monkeypatch.setattr(settings.__class__, "agent_runtime", "llm", raising=False)
    monkeypatch.setattr(settings.__class__, "llm_provider", "claude_cli", raising=False)
    assert get_llm_provider().name == "claude_cli"
