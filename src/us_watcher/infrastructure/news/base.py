"""News provider interface (spec §28). Providers never raise (return [])."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict


class RawNewsItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    url: str
    publisher: str
    published_at: datetime
    topic: str
    summary: str | None = None
    language: str = "en"


@runtime_checkable
class NewsProvider(Protocol):
    name: str

    async def fetch(self, topic: str) -> Sequence[RawNewsItem]: ...
