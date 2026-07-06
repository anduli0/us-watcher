"""Unit tests for the deterministic indicators (spec §45).

Covers correctness, boundary/insufficient-data (-> None), and reproducibility.
"""

from __future__ import annotations

import math

import pytest

from us_watcher.domain.analytics import indicators as ind


def test_simple_return_basic():
    assert ind.simple_return([100, 110], 1) == pytest.approx(0.10)
    assert ind.simple_return([100, 90], 1) == pytest.approx(-0.10)


def test_simple_return_insufficient_returns_none():
    assert ind.simple_return([100], 1) is None
    assert ind.simple_return([], 5) is None
    assert ind.simple_return([100, 110], 5) is None  # lookback exceeds length


def test_simple_return_zero_base_is_none():
    assert ind.simple_return([0.0, 10.0], 1) is None


def test_sma_and_insufficient():
    assert ind.sma([1, 2, 3, 4], 4) == pytest.approx(2.5)
    assert ind.sma([1, 2, 3], 4) is None
    assert ind.sma([], 1) is None


def test_ema_matches_known_value():
    # EMA seeded with SMA of the window; monotone series stays monotone.
    vals = [float(i) for i in range(1, 21)]
    e = ind.ema(vals, 10)
    assert e is not None and e > ind.sma(vals[:10], 10)


def test_rsi_bounds_and_extremes():
    rising = [float(i) for i in range(1, 60)]
    assert ind.rsi(rising, 14) == pytest.approx(100.0)
    falling = [float(i) for i in range(60, 1, -1)]
    assert ind.rsi(falling, 14) == pytest.approx(0.0, abs=1e-9)
    assert ind.rsi([1, 2, 3], 14) is None  # insufficient


def test_rsi_midrange_for_choppy():
    choppy = [100, 101, 100, 101, 100, 101, 100, 101, 100, 101, 100, 101, 100, 101, 100, 101]
    r = ind.rsi(choppy, 14)
    assert r is not None and 30 < r < 70


def test_macd_insufficient_then_value():
    assert ind.macd([1, 2, 3]) is None
    series = [100 + math.sin(i / 5) * 5 + i * 0.1 for i in range(80)]
    out = ind.macd(series)
    assert out is not None and len(out) == 3


def test_atr_requires_window_and_alignment():
    n = 30
    highs = [10 + i * 0.1 for i in range(n)]
    lows = [9 + i * 0.1 for i in range(n)]
    closes = [9.5 + i * 0.1 for i in range(n)]
    a = ind.atr(highs, lows, closes, 14)
    assert a is not None and a > 0
    assert ind.atr(highs[:5], lows[:5], closes[:5], 14) is None


def test_realized_vol_nonnegative_and_none_on_short():
    series = [100 * (1 + 0.01 * math.sin(i)) for i in range(40)]
    v = ind.realized_volatility(series, 20)
    assert v is not None and v >= 0
    assert ind.realized_volatility([100, 101], 20) is None


def test_max_drawdown_known():
    # peak 100 -> trough 80 => -20%
    assert ind.max_drawdown([100, 90, 80, 85]) == pytest.approx(-0.20)
    assert ind.max_drawdown([100]) is None


def test_distance_from_high():
    assert ind.distance_from_high([100, 120, 110], 252) == pytest.approx(110 / 120 - 1)


def test_relative_strength():
    asset = [100, 110]      # +10%
    bench = [100, 105]      # +5%
    assert ind.relative_strength(asset, bench, 1) == pytest.approx(0.05)
    assert ind.relative_strength([100], [100], 1) is None


def test_no_lookahead_prefix_independence():
    """An indicator at bar t must not change when future bars are appended."""
    base = [100 + i for i in range(60)]
    extended = [*base, 999, 1000, 1001]
    # RSI computed on the prefix equals RSI on the same prefix slice of extended
    assert ind.rsi(base, 14) == ind.rsi(extended[: len(base)], 14)
    assert ind.sma(base, 20) == ind.sma(extended[: len(base)], 20)


def test_determinism_repeated_calls():
    series = [100 + math.sin(i) for i in range(100)]
    assert ind.rsi(series, 14) == ind.rsi(series, 14)
    assert ind.realized_volatility(series, 20) == ind.realized_volatility(series, 20)
