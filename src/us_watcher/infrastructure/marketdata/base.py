"""Market-data provider interface (spec §14.2).

A provider NEVER raises: on failure it returns ``None`` / empty so a single bad
symbol or a provider outage degrades gracefully into an explicit *unavailable*
state instead of crashing an analysis run. Every value carries a
:class:`DataStatus` so the UI can label provenance honestly (spec §3.3, §14.3).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from us_watcher.domain.analytics.series import Bar
from us_watcher.domain.enums import DataStatus
from us_watcher.domain.money import DecimalNoFloat


class Quote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    price: DecimalNoFloat
    previous_close: DecimalNoFloat | None = None
    change_pct: float | None = None
    currency: str = "USD"
    as_of: datetime
    source: str               # "yahoo" | "mock" | provider name
    status: DataStatus
    is_proxy: bool = False


class AggregateSeries(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    symbol: str
    bars: list[Bar]
    source: str
    status: DataStatus
    as_of: datetime


@runtime_checkable
class MarketDataProvider(Protocol):
    """Keyless or keyed quote/aggregate source. Implementations never raise."""

    name: str

    async def get_quote(self, symbol: str) -> Quote | None: ...

    async def get_quotes(self, symbols: Sequence[str]) -> dict[str, Quote]: ...

    async def get_aggregates(
        self, symbol: str, *, range_: str = "2y", interval: str = "1d"
    ) -> AggregateSeries | None: ...
