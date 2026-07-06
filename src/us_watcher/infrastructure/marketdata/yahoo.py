"""Keyless Yahoo Finance market-data provider.

Uses the public chart endpoint (``/v8/finance/chart``) which returns both the
latest quote (``meta``) and the daily OHLCV history in one call. NEVER raises —
on any network/parse error it returns ``None`` so callers fall back to an
explicit unavailable/mock state.

We do not redistribute or persist raw index licensing data beyond derived
features; this is a best-effort public endpoint and every value it produces is
labelled ``DELAYED`` (or ``STALE``), never ``REAL_TIME`` (spec §14.4).
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from us_watcher.domain.analytics.series import Bar
from us_watcher.domain.enums import DataStatus
from us_watcher.domain.money import to_decimal
from us_watcher.domain.time import now_utc
from us_watcher.infrastructure.http import new_async_client
from us_watcher.infrastructure.marketdata.base import AggregateSeries, Quote

_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
# Status codes worth retrying: the keyless endpoint rate-limits bursts (429) and
# occasionally 5xx's. WITHOUT a retry a single transient 429 silently degraded
# that symbol to MOCK for the whole run — and a universe-wide burst degraded the
# ENTIRE recommendation set to mock (the "all 관망 / all avoid on fake prices"
# incident). A small bounded backoff recovers these without a retry storm
# (the SSL context is shared per process, so a retry is cheap).
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class YahooProvider:
    name = "yahoo"

    def __init__(
        self, *, user_agent: str = _DEFAULT_UA, timeout: float = 6.0, max_attempts: int = 3
    ) -> None:
        self._ua = user_agent
        self._timeout = timeout
        self._max_attempts = max(1, max_attempts)

    @staticmethod
    def _backoff_seconds(attempt: int) -> float:
        """Exponential backoff with jitter: ~0.4-0.7s, then ~0.8-1.3s. Jitter
        de-synchronises the ~200-symbol fan-out so retries don't thunder back in
        lockstep and re-trip the rate limit."""
        return 0.4 * (2.0 ** attempt) + random.uniform(0.0, 0.3)  # noqa: S311 (jitter, not crypto)

    async def _fetch_chart(self, symbol: str, range_: str, interval: str) -> dict | None:
        params = {"range": range_, "interval": interval, "includePrePost": "false"}
        for attempt in range(self._max_attempts):
            retryable = False
            try:
                async with new_async_client(timeout=self._timeout, headers={"User-Agent": self._ua}) as c:
                    resp = await c.get(_CHART_URL.format(symbol=symbol), params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    result = data["chart"]["result"]
                    if not result or not isinstance(result[0], dict):
                        return None
                    first: dict = result[0]
                    return first
                # Non-200: retry transient rate-limit / server errors, give up on the rest.
                retryable = resp.status_code in _RETRYABLE_STATUS
            except (httpx.TimeoutException, httpx.TransportError):
                retryable = True  # transient network blip
            except (httpx.HTTPError, KeyError, TypeError, IndexError, ValueError):
                return None  # malformed response — retrying won't help
            if retryable and attempt < self._max_attempts - 1:
                await asyncio.sleep(self._backoff_seconds(attempt))
                continue
            return None
        return None

    @staticmethod
    def _status_for(as_of: datetime) -> DataStatus:
        age = now_utc() - as_of
        if age > timedelta(days=4):
            return DataStatus.STALE
        return DataStatus.DELAYED

    async def get_quote(self, symbol: str) -> Quote | None:
        result = await self._fetch_chart(symbol, "5d", "1d")
        if result is None:
            return None
        meta = result.get("meta") or {}
        price = meta.get("regularMarketPrice")
        if price is None:
            return None
        prev = meta.get("chartPreviousClose") or meta.get("previousClose")
        ts = meta.get("regularMarketTime")
        as_of = datetime.fromtimestamp(ts, tz=UTC) if ts else now_utc()
        change_pct = None
        if prev:
            try:
                change_pct = (float(price) / float(prev) - 1.0) * 100.0
            except (ZeroDivisionError, ValueError):
                change_pct = None
        return Quote(
            symbol=symbol,
            price=to_decimal(price),
            previous_close=to_decimal(prev) if prev is not None else None,
            change_pct=change_pct,
            currency=meta.get("currency", "USD"),
            as_of=as_of,
            source=self.name,
            status=self._status_for(as_of),
        )

    async def get_quotes(self, symbols: Sequence[str]) -> dict[str, Quote]:
        out: dict[str, Quote] = {}
        for s in symbols:
            q = await self.get_quote(s)
            if q is not None:
                out[s] = q
        return out

    async def get_aggregates(
        self, symbol: str, *, range_: str = "2y", interval: str = "1d"
    ) -> AggregateSeries | None:
        result = await self._fetch_chart(symbol, range_, interval)
        if result is None:
            return None
        timestamps = result.get("timestamp") or []
        quote_block = (result.get("indicators", {}).get("quote") or [{}])[0]
        opens = quote_block.get("open") or []
        highs = quote_block.get("high") or []
        lows = quote_block.get("low") or []
        closes_ = quote_block.get("close") or []
        volumes = quote_block.get("volume") or []
        bars: list[Bar] = []
        for i, ts in enumerate(timestamps):
            o, h, low, c = (
                _at(opens, i),
                _at(highs, i),
                _at(lows, i),
                _at(closes_, i),
            )
            if c is None or h is None or low is None:
                continue
            bars.append(
                Bar(
                    as_of=datetime.fromtimestamp(ts, tz=UTC),
                    open=float(o if o is not None else c),
                    high=float(h),
                    low=float(low),
                    close=float(c),
                    volume=float(_at(volumes, i) or 0.0),
                )
            )
        if not bars:
            return None
        return AggregateSeries(
            symbol=symbol,
            bars=bars,
            source=self.name,
            status=self._status_for(bars[-1].as_of),
            as_of=bars[-1].as_of,
        )


def _at(seq: list[Any], i: int) -> Any:
    return seq[i] if i < len(seq) else None
