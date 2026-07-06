"""Market-data provider factory + resilient fallback.

``get_provider()`` returns the configured provider. :class:`FallbackProvider`
wraps a primary (live) provider and a mock so that a per-symbol live miss is
backfilled with explicitly-labelled mock data — the system stays usable with
partial data (spec §3.3) and the UI can always tell the two apart by ``source``
and ``status``.
"""

from __future__ import annotations

from collections.abc import Sequence

from us_watcher.config import get_settings
from us_watcher.infrastructure.marketdata.base import AggregateSeries, MarketDataProvider, Quote
from us_watcher.infrastructure.marketdata.mock import MockProvider
from us_watcher.infrastructure.marketdata.yahoo import YahooProvider


class FallbackProvider:
    """Try ``primary`` first; on a miss, return labelled mock data."""

    name = "yahoo+mock"

    def __init__(self, primary: MarketDataProvider, mock: MarketDataProvider) -> None:
        self._primary = primary
        self._mock = mock

    async def get_quote(self, symbol: str) -> Quote | None:
        q = await self._primary.get_quote(symbol)
        return q if q is not None else await self._mock.get_quote(symbol)

    async def get_quotes(self, symbols: Sequence[str]) -> dict[str, Quote]:
        out = await self._primary.get_quotes(symbols)
        missing = [s for s in symbols if s not in out]
        if missing:
            out.update(await self._mock.get_quotes(missing))
        return out

    async def get_aggregates(
        self, symbol: str, *, range_: str = "2y", interval: str = "1d"
    ) -> AggregateSeries | None:
        s = await self._primary.get_aggregates(symbol, range_=range_, interval=interval)
        return s if s is not None else await self._mock.get_aggregates(symbol, range_=range_, interval=interval)


def get_provider() -> MarketDataProvider:
    settings = get_settings()
    if settings.market_data_provider == "mock":
        return MockProvider()
    return FallbackProvider(YahooProvider(user_agent=settings.market_data_user_agent), MockProvider())
