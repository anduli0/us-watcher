"""LLM provider factory. Mock unless ``AGENT_RUNTIME=llm`` and a concrete
provider is available — Anthropic API (credits) or the local Claude Code CLI
(subscription-billed). ``LLM_PROVIDER`` picks explicitly; ``auto`` prefers the
API key when set, else the CLI."""

from __future__ import annotations

from us_watcher.config import get_settings
from us_watcher.infrastructure.llm.base import LLMProvider
from us_watcher.infrastructure.llm.mock import MockLLMProvider


def get_llm_provider() -> LLMProvider:
    settings = get_settings()
    if not settings.llm_enabled:
        return MockLLMProvider()
    resolved = settings.llm_provider_resolved
    if resolved == "claude_cli":
        from us_watcher.infrastructure.llm.claude_cli_provider import ClaudeCLIProvider

        return ClaudeCLIProvider()
    if resolved == "anthropic":
        from us_watcher.infrastructure.llm.anthropic_provider import AnthropicProvider

        return AnthropicProvider()
    return MockLLMProvider()
