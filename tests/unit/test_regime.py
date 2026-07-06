"""Unit tests for the market-regime engine (spec §12, §45)."""

from __future__ import annotations

from us_watcher.domain.enums import MarketRegime
from us_watcher.domain.regime.score import RegimeComponents, compute_regime


def test_strong_bull_classification():
    r = compute_regime(RegimeComponents(trend=0.9, breadth=0.8, volatility=0.7, cross_asset=0.6))
    assert r.score >= 35
    assert r.regime in (MarketRegime.STRONG_UPTREND, MarketRegime.OVERHEATED_RALLY, MarketRegime.SELECTIVE_BULL)


def test_bear_classification():
    r = compute_regime(RegimeComponents(trend=-0.9, breadth=-0.8, volatility=-0.7, cross_asset=-0.6))
    assert r.score <= -35
    assert r.regime == MarketRegime.BEAR_MARKET


def test_neutral_band():
    r = compute_regime(RegimeComponents(trend=0.0, breadth=0.0, volatility=0.0, cross_asset=0.0))
    assert -9 <= r.score <= 9
    assert r.regime == MarketRegime.NEUTRAL_RANGE


def test_missing_components_are_reweighted_not_zeroed():
    # Only trend present and strongly positive -> should score clearly positive,
    # NOT be dragged to ~0 by treating missing components as zero.
    r = compute_regime(RegimeComponents(trend=0.8))
    assert r.score > 30
    assert r.coverage < 0.5
    assert set(r.unavailable) >= {"breadth", "volatility", "credit"}
    assert r.available == ["trend"]


def test_no_components_is_transition_watch():
    r = compute_regime(RegimeComponents())
    assert r.regime == MarketRegime.TRANSITION_WATCH
    assert r.confidence == 0.0
    assert r.coverage == 0.0


def test_confidence_scales_with_coverage():
    full = compute_regime(
        RegimeComponents(trend=0.8, breadth=0.8, volatility=0.8, liquidity=0.8, credit=0.8,
                         earnings=0.8, macro_surprise=0.8, valuation=0.8, positioning=0.8, cross_asset=0.8)
    )
    sparse = compute_regime(RegimeComponents(trend=0.8))
    assert full.confidence > sparse.confidence  # same conviction, more coverage -> more confidence


def test_selective_bull_overlay_on_narrow_breadth():
    # Strong tape but cap-weight far outruns equal-weight -> selective/narrow.
    r = compute_regime(
        RegimeComponents(trend=0.9, breadth=0.6, volatility=0.5, cross_asset=0.4),
        cap_minus_equal_weight=0.06,
    )
    assert r.regime == MarketRegime.SELECTIVE_BULL


def test_score_clamped_to_range():
    r = compute_regime(
        RegimeComponents(trend=5.0, breadth=5.0, volatility=5.0, cross_asset=5.0)  # over-range inputs
    )
    assert -100 <= r.score <= 100


def test_deterministic():
    c = RegimeComponents(trend=0.3, breadth=-0.2, volatility=0.1)
    assert compute_regime(c).score == compute_regime(c).score
