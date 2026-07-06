"""Price-series primitives shared by the analytics calculators.

A :class:`Bar` is one OHLCV observation with its own ``as_of`` timestamp so the
analytics layer can reason about freshness and never silently mix vintages.
Series are ordered oldest -> newest. Calculators operate on plain ``float``
closes (computed statistical features, not money), while persisted prices use
:data:`us_watcher.domain.money.DecimalNoFloat`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Bar:
    """One OHLCV bar. ``as_of`` is the bar's close timestamp (tz-aware UTC)."""

    as_of: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None


def closes(bars: list[Bar]) -> list[float]:
    return [b.close for b in bars]


def is_sufficient(bars: list[Bar] | list[float], window: int) -> bool:
    """True when there are at least ``window`` observations available."""
    return len(bars) >= window and window > 0
