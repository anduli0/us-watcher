"""Unit tests for the point-in-time backtester (spec §32.4: no look-ahead)."""

from __future__ import annotations

from datetime import timedelta

from us_watcher.accuracy.backtest import point_in_time_signal, run_backtest
from us_watcher.domain.analytics.series import Bar
from us_watcher.domain.time import now_utc


def _series(closes: list[float]) -> list[Bar]:
    start = now_utc() - timedelta(days=len(closes))
    return [
        Bar(as_of=start + timedelta(days=i), open=c, high=c * 1.01, low=c * 0.99, close=c, volume=1e6)
        for i, c in enumerate(closes)
    ]


def test_signal_no_lookahead():
    """Signal at t must be identical whether or not future bars exist."""
    base = [100.0 + i * 0.3 for i in range(300)]
    extended = [*base, 10.0, 11.0, 12.0]  # wild future bars
    t = 250
    assert point_in_time_signal(base, t) == point_in_time_signal(extended, t)


def test_signal_none_before_warmup():
    assert point_in_time_signal([100.0] * 50, 40) is None


def test_signal_high_in_uptrend_low_in_downtrend():
    up = [100.0 + i for i in range(260)]
    down = [400.0 - i for i in range(260)]
    su = point_in_time_signal(up, 259)
    sd = point_in_time_signal(down, 259)
    assert su is not None and sd is not None and su > sd


def test_backtest_runs_and_is_deterministic():
    up = _series([100.0 + i * 0.5 for i in range(400)])
    bench = _series([100.0 + i * 0.2 for i in range(400)])
    r1 = run_backtest({"UP": up}, bench, horizons=(20, 60))
    r2 = run_backtest({"UP": up}, bench, horizons=(20, 60))
    assert r1 == r2
    assert r1["by_horizon"]["20"]["samples"] > 0


def test_backtest_costs_reduce_returns():
    up = _series([100.0 + i * 0.5 for i in range(400)])
    bench = _series([100.0 + i * 0.2 for i in range(400)])
    cheap = run_backtest({"UP": up}, bench, horizons=(20,), cost_bps=0.0)
    pricey = run_backtest({"UP": up}, bench, horizons=(20,), cost_bps=100.0)
    a = cheap["by_horizon"]["20"]["long_avg_return_pct"]
    b = pricey["by_horizon"]["20"]["long_avg_return_pct"]
    if a is not None and b is not None:
        assert a > b


def test_backtest_uptrend_long_signals_profit():
    up = _series([100.0 * (1.004 ** i) for i in range(400)])  # steady compounding uptrend
    bench = _series([100.0 * (1.001 ** i) for i in range(400)])
    r = run_backtest({"UP": up}, bench, horizons=(20, 60))
    h20 = r["by_horizon"]["20"]
    assert h20["long_signals"] > 0
    assert h20["long_avg_return_pct"] is not None and h20["long_avg_return_pct"] > 0
