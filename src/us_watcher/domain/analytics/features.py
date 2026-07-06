"""Assemble a deterministic :class:`FeatureSet` from a price series.

This is the single place that turns raw bars into the summarised quantitative
features that get sent to LLM agents (spec §19 step 3: compute features before
invoking any LLM; never send raw time series when a summary suffices). Every
field is either a real computed value or ``None`` (explicit unavailable).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from us_watcher.domain.analytics import indicators as ind
from us_watcher.domain.analytics.series import Bar, closes

# Standard return lookbacks (trading days), spec §12.
RETURN_LOOKBACKS = {"r1": 1, "r5": 5, "r20": 20, "r60": 60, "r120": 120, "r252": 252}
MA_WINDOWS = {"ma20": 20, "ma50": 50, "ma100": 100, "ma200": 200}


class FeatureSet(BaseModel):
    """Deterministic features for a single instrument as of ``as_of``."""

    model_config = ConfigDict(extra="forbid")

    symbol: str
    as_of: datetime
    n_bars: int
    last_close: float | None

    returns: dict[str, float | None]
    moving_averages: dict[str, float | None]
    ma200_slope: float | None
    rsi14: float | None
    macd_hist: float | None
    atr14: float | None
    realized_vol_20: float | None
    max_drawdown: float | None
    distance_from_52w_high: float | None
    above_ma50: bool | None
    above_ma200: bool | None

    def availability(self) -> float:
        """Fraction of headline features that are non-null (a data-quality cue)."""
        checks = [
            self.last_close,
            self.returns.get("r20"),
            self.moving_averages.get("ma50"),
            self.rsi14,
            self.realized_vol_20,
            self.distance_from_52w_high,
        ]
        present = sum(1 for c in checks if c is not None)
        return present / len(checks)


def build_features(symbol: str, bars: list[Bar], as_of: datetime) -> FeatureSet:
    """Build a :class:`FeatureSet` from an oldest->newest bar list."""
    cs = closes(bars)
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]

    macd_tuple = ind.macd(cs)
    return FeatureSet(
        symbol=symbol,
        as_of=as_of,
        n_bars=len(bars),
        last_close=cs[-1] if cs else None,
        returns={k: ind.simple_return(cs, lb) for k, lb in RETURN_LOOKBACKS.items()},
        moving_averages={k: ind.sma(cs, w) for k, w in MA_WINDOWS.items()},
        ma200_slope=ind.ma_slope(cs, 200, lookback=20),
        rsi14=ind.rsi(cs, 14),
        macd_hist=macd_tuple[2] if macd_tuple else None,
        atr14=ind.atr(highs, lows, cs, 14),
        realized_vol_20=ind.realized_volatility(cs, 20),
        max_drawdown=ind.max_drawdown(cs),
        distance_from_52w_high=ind.distance_from_high(cs, 252),
        above_ma50=ind.pct_above_ma(cs, 50),
        above_ma200=ind.pct_above_ma(cs, 200),
    )
