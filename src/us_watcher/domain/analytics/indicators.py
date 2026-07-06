"""Deterministic technical indicators (spec §3.1, §12).

Every function is pure and reproducible: same input -> same output, no clocks,
no randomness, no network. When there is not enough data to compute an
indicator honestly, the function returns ``None`` (an explicit *unavailable*
state) rather than fabricating a value. No look-ahead: an indicator at the end
of a series uses only observations up to and including the last bar.

These are computed *features*, so ``float`` is the right type here; money and
prices that get persisted use Decimal at the boundary.
"""

from __future__ import annotations

import math
from collections.abc import Sequence


def _validate(values: Sequence[float], window: int) -> bool:
    return window > 0 and len(values) >= window


def simple_return(values: Sequence[float], lookback: int) -> float | None:
    """Total return over ``lookback`` bars, as a fraction (0.05 == +5%)."""
    if lookback <= 0 or len(values) <= lookback:
        return None
    past = values[-1 - lookback]
    if past == 0:
        return None
    return values[-1] / past - 1.0


def sma(values: Sequence[float], window: int) -> float | None:
    """Simple moving average of the last ``window`` observations."""
    if not _validate(values, window):
        return None
    return sum(values[-window:]) / window


def ema(values: Sequence[float], window: int) -> float | None:
    """Exponential moving average (seeded with the first SMA)."""
    if not _validate(values, window):
        return None
    k = 2.0 / (window + 1.0)
    seed = sum(values[:window]) / window
    e = seed
    for v in values[window:]:
        e = v * k + e * (1.0 - k)
    return e


def ma_slope(values: Sequence[float], window: int, lookback: int = 20) -> float | None:
    """Slope of the moving average over ``lookback`` bars, normalised to the
    current MA level (so it is comparable across instruments). Positive == the
    average is rising."""
    if len(values) < window + lookback:
        return None
    cur = sma(values, window)
    prev = sma(values[: len(values) - lookback], window)
    if cur is None or prev is None or cur == 0:
        return None
    return (cur - prev) / cur


def rsi(values: Sequence[float], window: int = 14) -> float | None:
    """Wilder's RSI in [0, 100]."""
    if len(values) <= window:
        return None
    gains = 0.0
    losses = 0.0
    for i in range(1, window + 1):
        delta = values[i] - values[i - 1]
        if delta >= 0:
            gains += delta
        else:
            losses -= delta
    avg_gain = gains / window
    avg_loss = losses / window
    for i in range(window + 1, len(values)):
        delta = values[i] - values[i - 1]
        gain = max(delta, 0.0)
        loss = max(-delta, 0.0)
        avg_gain = (avg_gain * (window - 1) + gain) / window
        avg_loss = (avg_loss * (window - 1) + loss) / window
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def macd(
    values: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[float, float, float] | None:
    """MACD line, signal line, histogram. Returns ``None`` if insufficient data."""
    if len(values) < slow + signal:
        return None
    macd_series: list[float] = []
    for end in range(slow, len(values) + 1):
        window = values[:end]
        ef = ema(window, fast)
        es = ema(window, slow)
        if ef is None or es is None:
            return None
        macd_series.append(ef - es)
    sig = ema(macd_series, signal)
    if sig is None:
        return None
    line = macd_series[-1]
    return line, sig, line - sig


def true_range(high: float, low: float, prev_close: float) -> float:
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


def atr(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], window: int = 14) -> float | None:
    """Average True Range over ``window`` bars (Wilder smoothing)."""
    n = len(closes)
    if n <= window or len(highs) != n or len(lows) != n:
        return None
    trs = [true_range(highs[i], lows[i], closes[i - 1]) for i in range(1, n)]
    if len(trs) < window:
        return None
    a = sum(trs[:window]) / window
    for tr in trs[window:]:
        a = (a * (window - 1) + tr) / window
    return a


def realized_volatility(values: Sequence[float], window: int = 20, annualize: bool = True) -> float | None:
    """Annualised realised volatility from daily log returns over ``window``."""
    if len(values) <= window:
        return None
    rets = []
    for i in range(len(values) - window, len(values)):
        if i == 0 or values[i - 1] <= 0 or values[i] <= 0:
            continue
        rets.append(math.log(values[i] / values[i - 1]))
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    vol = math.sqrt(var)
    return vol * math.sqrt(252.0) if annualize else vol


def max_drawdown(values: Sequence[float]) -> float | None:
    """Maximum peak-to-trough drawdown as a negative fraction (-0.20 == -20%)."""
    if len(values) < 2:
        return None
    peak = values[0]
    mdd = 0.0
    for v in values:
        peak = max(peak, v)
        if peak > 0:
            mdd = min(mdd, v / peak - 1.0)
    return mdd


def distance_from_high(values: Sequence[float], window: int = 252) -> float | None:
    """Distance below the rolling ``window`` high, as a non-positive fraction."""
    if len(values) < 2:
        return None
    w = values[-window:] if len(values) >= window else values
    hi = max(w)
    if hi <= 0:
        return None
    return values[-1] / hi - 1.0


def pct_above_ma(values: Sequence[float], window: int) -> bool | None:
    """Whether the latest close is above its ``window``-day SMA."""
    m = sma(values, window)
    if m is None:
        return None
    return values[-1] > m


def relative_strength(asset: Sequence[float], bench: Sequence[float], lookback: int) -> float | None:
    """Relative return of ``asset`` vs ``bench`` over ``lookback`` bars
    (asset_return - bench_return)."""
    a = simple_return(asset, lookback)
    b = simple_return(bench, lookback)
    if a is None or b is None:
        return None
    return a - b
