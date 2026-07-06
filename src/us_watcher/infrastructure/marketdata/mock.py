"""Deterministic offline market-data provider (labelled MOCK).

Produces a reproducible synthetic series from a per-symbol seed so the app is
fully usable with zero network/credentials — but EVERY value is stamped
``DataStatus.MOCK`` and ``source="mock"`` so it can never be mistaken for live
data (spec §3.3). No randomness: same symbol -> same series every run.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from datetime import timedelta

from us_watcher.domain.analytics.series import Bar
from us_watcher.domain.enums import DataStatus
from us_watcher.domain.money import to_decimal
from us_watcher.domain.time import now_utc
from us_watcher.infrastructure.marketdata.base import AggregateSeries, Quote


def _seed(symbol: str) -> int:
    return int(hashlib.sha256(symbol.encode()).hexdigest()[:8], 16)


# Symbols whose natural level lives far outside the generic 50..5050 band.
# Keyed by the **yahoo_symbol** actually passed to the provider (see
# config/universe.yml). Without these, the hash-based fallback renders e.g. the
# volatility index at ~2030 — obviously broken — whenever the live provider is
# briefly unavailable and we degrade to MOCK. Values are rough, plausible levels;
# the deterministic drift/wave still varies them per symbol.
_SPECIAL_BASES: dict[str, float] = {
    "^VIX": 16.5,        # volatility index (~12-30), not a price
    "^GSPC": 5800.0,     # S&P 500
    "^NDX": 20500.0,     # Nasdaq-100
    "^IXIC": 19000.0,    # Nasdaq Composite
    "^DJI": 43000.0,     # Dow Jones Industrial Avg
    "^NYA": 19000.0,     # NYSE Composite
    "^RUT": 2300.0,      # Russell 2000
    "DX-Y.NYB": 104.0,   # US dollar index
    "CL=F": 72.0,        # WTI crude
    "GC=F": 2600.0,      # gold
    "BTC-USD": 95000.0,  # bitcoin
}


def _base_price(symbol: str) -> float:
    special = _SPECIAL_BASES.get(symbol)
    if special is not None:
        return special
    # Stable, plausible-looking base level per symbol (50 .. ~5050).
    return 50.0 + (_seed(symbol) % 5000)


class MockProvider:
    name = "mock"

    def _series(self, symbol: str, n: int) -> list[float]:
        seed = _seed(symbol)
        base = _base_price(symbol)
        # Gentle deterministic drift. Kept small so the cumulative move over the
        # ~504-bar series stays within ~±15% — otherwise the latest close drifts
        # so far from _base_price that level-sensitive symbols (VIX, the dollar
        # index) land at implausible values.
        drift = ((seed % 7) - 3) * 0.0001
        amp = 0.04 + (seed % 5) * 0.01
        period = 30 + (seed % 40)
        out: list[float] = []
        for i in range(n):
            wave = math.sin(2 * math.pi * i / period) * amp
            out.append(round(base * (1.0 + drift * i + wave), 4))
        return out

    async def get_aggregates(
        self, symbol: str, *, range_: str = "2y", interval: str = "1d"
    ) -> AggregateSeries | None:
        n = 504  # ~2 trading years
        closes = self._series(symbol, n)
        now = now_utc()
        bars: list[Bar] = []
        for i, c in enumerate(closes):
            span = c * 0.01
            bars.append(
                Bar(
                    as_of=now - timedelta(days=(n - 1 - i)),
                    open=round(c - span * 0.3, 4),
                    high=round(c + span, 4),
                    low=round(c - span, 4),
                    close=c,
                    volume=1_000_000.0 + (_seed(symbol) % 500_000),
                )
            )
        return AggregateSeries(
            symbol=symbol, bars=bars, source=self.name, status=DataStatus.MOCK, as_of=bars[-1].as_of
        )

    async def get_quote(self, symbol: str) -> Quote | None:
        closes = self._series(symbol, 2)
        price, prev = closes[-1], closes[-2]
        change = (price / prev - 1.0) * 100.0 if prev else None
        return Quote(
            symbol=symbol,
            price=to_decimal(round(price, 4)),
            previous_close=to_decimal(round(prev, 4)),
            change_pct=change,
            as_of=now_utc(),
            source=self.name,
            status=DataStatus.MOCK,
        )

    async def get_quotes(self, symbols: Sequence[str]) -> dict[str, Quote]:
        out: dict[str, Quote] = {}
        for s in symbols:
            q = await self.get_quote(s)
            if q is not None:
                out[s] = q
        return out
