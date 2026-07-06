"""Deterministic mock LLM provider.

Returns structured output by extracting the deterministic numeric hints the
caller embeds in ``StructuredPrompt.user`` (e.g. a ``direction``/``confidence``
seed computed by the quant engine). It never invents financial numbers — it only
echoes/structures what the deterministic layer already computed, and prose is
clearly generic. Stamped ``is_mock=True`` so it can never be mistaken for an LLM.
"""

from __future__ import annotations

import json

from us_watcher.infrastructure.llm.base import LLMResult, StructuredPrompt


class MockLLMProvider:
    name = "mock"
    is_mock = True

    async def generate_structured(self, prompt: StructuredPrompt, *, role: str = "reasoning") -> LLMResult:
        # The caller passes a JSON "seed" block in the user prompt after the
        # marker SEED=. We parse and return it as the structured payload so the
        # mock pipeline is deterministic and never fabricates numbers.
        data: dict = {}
        marker = "SEED="
        if marker in prompt.user:
            try:
                data = json.loads(prompt.user.split(marker, 1)[1].strip())
            except (json.JSONDecodeError, ValueError):
                data = {}
        return LLMResult(text="", data=data, model="deterministic-mock", provider="mock", is_mock=True)

    async def generate_text(
        self, system: str, user: str, *, role: str = "editor", max_tokens: int = 1024
    ) -> LLMResult:
        return LLMResult(text="", model="deterministic-mock", provider="mock", is_mock=True)
