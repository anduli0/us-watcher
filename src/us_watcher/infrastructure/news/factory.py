"""News provider factory with mock fallback."""

from __future__ import annotations

from us_watcher.config import get_settings
from us_watcher.infrastructure.news.base import NewsProvider
from us_watcher.infrastructure.news.mock import MockNewsProvider


def get_news_provider() -> NewsProvider:
    settings = get_settings()
    if settings.news_provider == "mock":
        return MockNewsProvider()
    from us_watcher.infrastructure.news.google_rss import GoogleRssProvider

    return GoogleRssProvider()
