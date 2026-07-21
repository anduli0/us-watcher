"""Unit tests for the sub-industry cycle calibration harness (no network)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from us_watcher.accuracy.cycle_calibration import run_cycle_diagnosis
from us_watcher.domain.analytics.series import Bar
from us_watcher.domain.recommendation.config import CYCLICAL_SUB_INDUSTRIES


def _bars(closes: list[float]) -> list[Bar]:
    start = datetime(2020, 1, 1, tzinfo=UTC)
    return [Bar(as_of=start + timedelta(days=i), open=c, high=c, low=c, close=c) for i, c in enumerate(closes)]


def test_cyclical_set_includes_memory_and_excludes_secular_logic():
    # The calibration outcome: cyclical groups get the blend, secular ones do not.
    assert "memory" in CYCLICAL_SUB_INDUSTRIES
    assert "semi_equip" in CYCLICAL_SUB_INDUSTRIES
    assert "semi_logic" not in CYCLICAL_SUB_INDUSTRIES  # mean-reverting → excluded
    assert "semi_eda" not in CYCLICAL_SUB_INDUSTRIES


def test_cycle_on_names_bucket_positive_excess_no_lookahead():
    n = 260
    spy = _bars([100.0] * n)                                   # flat benchmark
    up = _bars([100.0 * (1.0 + 0.002 * i) for i in range(n)])  # steadily outperforming
    groups = {"memory": ["A", "B"]}
    res = run_cycle_diagnosis({"A": up, "B": up}, groups, spy)
    on = res["overall"][120]["on"]
    off = res["overall"][120]["off"]
    # A rising group vs a flat SPY is always cycle-ON, with positive forward excess.
    assert on.n > 0 and off.n == 0
    assert on.avg_exc() > 0.0


def test_group_below_min_peers_is_skipped():
    # A single-name group has no reliable cycle read (MIN_PEERS=2) → no samples.
    n = 260
    spy = _bars([100.0] * n)
    up = _bars([100.0 * (1.0 + 0.002 * i) for i in range(n)])
    res = run_cycle_diagnosis({"A": up}, {"solo": ["A"]}, spy)
    assert res["overall"][120]["on"].n == 0
    assert res["overall"][120]["off"].n == 0
