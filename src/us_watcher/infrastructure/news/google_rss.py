"""Keyless Google News RSS provider (spec §14, §28).

Parses RSS with :mod:`defusedxml` (XXE-safe). NEVER raises — returns ``[]`` on
any error. Stores only title + link + metadata (no full-text scraping), so it
stays within fair-use/lead-only territory (spec §14.4, §28.5).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote_plus

import httpx
from defusedxml import ElementTree

from us_watcher.infrastructure.http import new_async_client
from us_watcher.infrastructure.news.base import RawNewsItem

_URL = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
_UA = "Mozilla/5.0 (compatible; US-WATCHER/0.1; +https://localhost)"


class GoogleRssProvider:
    name = "google"

    def __init__(self, *, timeout: float = 8.0) -> None:
        self._timeout = timeout

    async def fetch(self, topic: str) -> Sequence[RawNewsItem]:
        url = _URL.format(q=quote_plus(topic))
        try:
            async with new_async_client(timeout=self._timeout, headers={"User-Agent": _UA}) as c:
                resp = await c.get(url)
                if resp.status_code != 200:
                    return []
                root = ElementTree.fromstring(resp.text)
        except (httpx.HTTPError, ElementTree.ParseError, ValueError):
            return []
        items: list[RawNewsItem] = []
        for item in root.iter("item"):
            title = _text(item, "title")
            link = _text(item, "link")
            if not title or not link:
                continue
            pub = _parse_date(_text(item, "pubDate"))
            source = _text(item, "source") or "Google News"
            items.append(RawNewsItem(
                title=title.strip(), url=link.strip(), publisher=source.strip(),
                published_at=pub, topic=topic, language="en",
            ))
        return items


def _text(item: Any, tag: str) -> str | None:
    el = item.find(tag)
    return el.text if el is not None else None


def _parse_date(raw: str | None) -> datetime:
    if not raw:
        return datetime.now(tz=UTC)
    try:
        dt = parsedate_to_datetime(raw)
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return datetime.now(tz=UTC)
