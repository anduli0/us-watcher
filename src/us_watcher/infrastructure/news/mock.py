"""Deterministic offline news provider (labelled). Used when NEWS_PROVIDER=mock
or as a fallback so the News tab is demonstrable without network."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from us_watcher.infrastructure.news.base import RawNewsItem

_TEMPLATES = [
    ("[MOCK] {t}: megacap leadership narrows as breadth lags", "MockWire"),
    ("[MOCK] {t}: Treasury yields steady ahead of data", "MockTimes"),
    ("[MOCK] {t}: semiconductor demand outlook in focus", "MockDaily"),
]


class MockNewsProvider:
    name = "mock"

    async def fetch(self, topic: str) -> Sequence[RawNewsItem]:
        seed = int(hashlib.sha256(topic.encode()).hexdigest()[:6], 16)
        now = datetime.now(tz=UTC)
        out: list[RawNewsItem] = []
        for i, (tmpl, pub) in enumerate(_TEMPLATES):
            out.append(RawNewsItem(
                title=tmpl.format(t=topic),
                url=f"https://example.com/mock/{seed}/{i}",
                publisher=pub,
                published_at=now - timedelta(hours=i * 3 + (seed % 5)),
                topic=topic, summary="Sample MOCK item — not a real article.", language="en",
            ))
        return out
