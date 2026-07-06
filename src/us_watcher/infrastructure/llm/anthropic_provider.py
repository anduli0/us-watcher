"""Anthropic-backed LLM provider (spec §20).

Used only when ``AGENT_RUNTIME=llm`` and ``ANTHROPIC_API_KEY`` is set. Structured
output is forced via a single tool whose ``input_schema`` is the requested JSON
schema (the model must call it), so we always get schema-valid data. On ANY error
it degrades to the deterministic mock provider — the pipeline never crashes and
never blocks on a provider outage.
"""

from __future__ import annotations

from typing import Any

from us_watcher.config import get_settings
from us_watcher.infrastructure.llm.base import LLMResult, StructuredPrompt
from us_watcher.infrastructure.llm.mock import MockLLMProvider

_ROLE_MODEL_ATTR = {
    "fast": "llm_fast_model",
    "reasoning": "llm_reasoning_model",
    "critic": "llm_critic_model",
    "editor": "llm_editor_model",
}


class AnthropicProvider:
    name = "anthropic"
    is_mock = False

    def __init__(self) -> None:
        self._settings = get_settings()
        self._mock = MockLLMProvider()
        self._client: Any | None = None

    def _model_for(self, role: str) -> str:
        attr = _ROLE_MODEL_ATTR.get(role, "llm_reasoning_model")
        return str(getattr(self._settings, attr))

    async def _get_client(self) -> Any | None:
        if self._client is not None:
            return self._client
        try:
            from anthropic import AsyncAnthropic  # lazy: optional [llm] extra

            self._client = AsyncAnthropic(api_key=self._settings.anthropic_api_key.get_secret_value())
            return self._client
        except Exception:
            return None

    async def generate_structured(self, prompt: StructuredPrompt, *, role: str = "reasoning") -> LLMResult:
        client = await self._get_client()
        if client is None:
            return await self._mock.generate_structured(prompt, role=role)
        model = self._model_for(role)
        try:
            resp = await client.messages.create(
                model=model,
                max_tokens=prompt.max_tokens,
                system=prompt.system,
                tools=[{
                    "name": "emit",
                    "description": "Emit the structured analysis result.",
                    "input_schema": prompt.json_schema,
                }],
                tool_choice={"type": "tool", "name": "emit"},
                messages=[{"role": "user", "content": prompt.user}],
            )
            data: dict[str, Any] = {}
            for block in resp.content:
                if getattr(block, "type", None) == "tool_use":
                    data = dict(block.input)
                    break
            usage = getattr(resp, "usage", None)
            return LLMResult(
                text="", data=data, model=model, provider=self.name, is_mock=False,
                input_tokens=getattr(usage, "input_tokens", 0) if usage else 0,
                output_tokens=getattr(usage, "output_tokens", 0) if usage else 0,
            )
        except Exception:
            return await self._mock.generate_structured(prompt, role=role)

    async def generate_text(
        self, system: str, user: str, *, role: str = "editor", max_tokens: int = 1024
    ) -> LLMResult:
        client = await self._get_client()
        if client is None:
            return await self._mock.generate_text(system, user, role=role, max_tokens=max_tokens)
        model = self._model_for(role)
        try:
            resp = await client.messages.create(
                model=model, max_tokens=max_tokens, system=system,
                messages=[{"role": "user", "content": user}],
            )
            text = "".join(getattr(b, "text", "") for b in resp.content)
            usage = getattr(resp, "usage", None)
            return LLMResult(
                text=text, model=model, provider=self.name, is_mock=False,
                input_tokens=getattr(usage, "input_tokens", 0) if usage else 0,
                output_tokens=getattr(usage, "output_tokens", 0) if usage else 0,
            )
        except Exception:
            return await self._mock.generate_text(system, user, role=role, max_tokens=max_tokens)
