"""LLM provider abstraction (spec §20).

Roles (fast / reasoning / critic / editor) are configured centrally; model names
are never hardcoded across the codebase. The system MUST run with zero providers
configured — in that case the mock provider returns deterministic structured
output so the whole pipeline still works offline.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel


class LLMResult(BaseModel):
    text: str
    data: dict[str, Any] | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    provider: str = ""
    is_mock: bool = True


class StructuredPrompt(BaseModel):
    system: str
    user: str
    json_schema: dict[str, Any]
    max_tokens: int = 2048


@runtime_checkable
class LLMProvider(Protocol):
    """Generate text or schema-constrained structured output. Never raises;
    degrades to a deterministic mock result on any error."""

    name: str
    is_mock: bool

    async def generate_structured(self, prompt: StructuredPrompt, *, role: str = "reasoning") -> LLMResult: ...

    async def generate_text(
        self, system: str, user: str, *, role: str = "editor", max_tokens: int = 1024
    ) -> LLMResult: ...
