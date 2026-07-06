"""Unit tests for recommendation scoring + CMS (spec §24, §25, §45)."""

from __future__ import annotations

import pytest

from us_watcher.domain.enums import Horizon, MarketRegime, RecAction
from us_watcher.domain.recommendation.config import (
    CMS_WEIGHTS,
    ETF_APPLICABLE_KEYS,
    HORIZON_WEIGHTS,
    STOCK_APPLICABLE_KEYS,
    WATCH_CONFIDENCE_FLOOR,
)
from us_watcher.domain.recommendation.scoring import (
    ComponentScores,
    capital_migration_score,
    decide_action,
    score_recommendation,
)

_BUY_FAMILY = (RecAction.STRONG_BUY, RecAction.BUY, RecAction.ACCUMULATE)
_BEARISH = (RecAction.REDUCE, RecAction.SELL, RecAction.AVOID)


def test_horizon_weights_each_sum_to_100():
    for horizon, weights in HORIZON_WEIGHTS.items():
        assert sum(weights.values()) == pytest.approx(100.0), horizon


def test_cms_weights_sum_to_100():
    assert sum(CMS_WEIGHTS.values()) == pytest.approx(100.0)


def test_strong_scores_yield_buy_family():
    scores = ComponentScores(
        technical=90, fundamental_quality=85, valuation=70, earnings_revision=88,
        sector_leadership=82, macro_fit=75, news_catalyst=80, capital_migration=85,
        emerging_theme=70, flow_positioning=78, risk=10, data_quality=90,
    )
    r = score_recommendation(scores, horizon=Horizon.MEDIUM, regime=MarketRegime.MODERATE_UPTREND)
    assert r.action in (RecAction.STRONG_BUY, RecAction.BUY)
    assert r.total_score > 68


def test_risk_penalty_is_separate_deduction():
    base = ComponentScores(
        technical=70, fundamental_quality=70, valuation=70, earnings_revision=70,
        sector_leadership=70, macro_fit=70, news_catalyst=70, capital_migration=70,
        emerging_theme=70, flow_positioning=70, risk=0, data_quality=90,
    )
    risky = base.model_copy(update={"risk": 100})
    low = score_recommendation(risky, horizon=Horizon.MEDIUM)
    high = score_recommendation(base, horizon=Horizon.MEDIUM)
    assert high.total_score > low.total_score
    assert low.risk_penalty > 0 and high.risk_penalty == 0


def test_missing_features_reweighted_not_zeroed():
    # Only two strong components present; total should reflect those, not be
    # dragged toward 0 by the absent ones.
    scores = ComponentScores(technical=90, news_catalyst=85, risk=10, data_quality=80)
    r = score_recommendation(scores, horizon=Horizon.SHORT)
    assert r.coverage < 1.0
    assert r.total_score > 60  # strong present components dominate
    assert "macro_fit" in r.missing


def test_regime_changes_total():
    scores = ComponentScores(
        technical=70, fundamental_quality=70, valuation=70, earnings_revision=70,
        sector_leadership=70, macro_fit=70, news_catalyst=70, capital_migration=70,
        emerging_theme=70, flow_positioning=70, risk=10, data_quality=80,
    )
    bull = score_recommendation(scores, horizon=Horizon.MEDIUM, regime=MarketRegime.STRONG_UPTREND)
    bear = score_recommendation(scores, horizon=Horizon.MEDIUM, regime=MarketRegime.BEAR_MARKET)
    assert bull.total_score > bear.total_score


def test_horizon_changes_weighting():
    # Capital migration dominates ML; near-zero short weight. A stock strong only
    # on CMS should score much higher at ML than at SHORT.
    scores = ComponentScores(
        technical=20, fundamental_quality=50, valuation=50, earnings_revision=50,
        sector_leadership=50, macro_fit=50, news_catalyst=20, capital_migration=95,
        emerging_theme=90, flow_positioning=20, risk=10, data_quality=85,
    )
    short = score_recommendation(scores, horizon=Horizon.SHORT)
    ml = score_recommendation(scores, horizon=Horizon.MEDIUM_LONG)
    assert ml.total_score > short.total_score


def test_low_confidence_demotes_buy_to_watch():
    # A buy-range total but very low confidence -> WATCH (not a committed buy).
    assert decide_action(70.0, confidence=30.0, risk=10.0) == RecAction.WATCH


def test_high_risk_low_score_is_avoid_not_sell():
    assert decide_action(40.0, confidence=60.0, risk=85.0) == RecAction.AVOID


def test_capital_migration_score_partial_coverage():
    score, coverage = capital_migration_score({"capex_growth": 80, "moat_barriers": 90})
    assert 0 < score <= 100
    assert coverage < 1.0


def test_capital_migration_empty_is_zero():
    score, coverage = capital_migration_score({})
    assert score == 0.0 and coverage == 0.0


def test_total_score_bounded():
    scores = ComponentScores(technical=100, news_catalyst=100, flow_positioning=100,
                             sector_leadership=100, macro_fit=100, earnings_revision=100,
                             fundamental_quality=100, risk=0, data_quality=100)
    r = score_recommendation(scores, horizon=Horizon.SHORT, regime=MarketRegime.STRONG_UPTREND)
    assert 0 <= r.total_score <= 100


def test_deterministic():
    scores = ComponentScores(technical=55, news_catalyst=60, risk=20, data_quality=70)
    a = score_recommendation(scores, horizon=Horizon.SHORT)
    b = score_recommendation(scores, horizon=Horizon.SHORT)
    assert a.model_dump() == b.model_dump()


# --- Regression: the "all 관망 (watch)" masking bug -------------------------------
# A keyless ETF in a clean uptrend scored into BUY/ACCUMULATE territory was being
# silently demoted to WATCH because confidence — measured against a weight table
# that includes fundamentals an ETF cannot have — could never reach the WATCH
# floor. Confidence must be ASSET-CLASS-AWARE so a well-covered ETF call commits.


def _strong_etf() -> ComponentScores:
    return ComponentScores(technical=80, flow_positioning=74, sector_leadership=78,
                           macro_fit=70, risk=22, data_quality=68)


def test_keyless_etf_strong_uptrend_is_buy_not_watch():
    etf = _strong_etf()
    for horizon in Horizon:
        r = score_recommendation(etf, horizon=horizon, regime=MarketRegime.MODERATE_UPTREND,
                                 applicable_keys=ETF_APPLICABLE_KEYS)
        assert r.action in _BUY_FAMILY, (horizon, r.action, r.total_score, r.confidence)
        assert r.action is not RecAction.WATCH


def test_watch_confidence_floor_is_reachable_for_full_coverage():
    # The sentinel test that would have caught the bug: a fully applicable-covered
    # ETF MUST be able to exceed the WATCH floor. If a future recalibration pushes
    # the achievable confidence back below the floor, every buy collapses to WATCH
    # again — and this fails loudly.
    etf = _strong_etf()
    best = max(
        score_recommendation(etf, horizon=h, regime=MarketRegime.MODERATE_UPTREND,
                             applicable_keys=ETF_APPLICABLE_KEYS).confidence
        for h in Horizon
    )
    assert best > WATCH_CONFIDENCE_FLOOR, best


def test_applicable_coverage_lifts_etf_confidence_above_absolute():
    # Same ETF: scored WITH its applicable keys reads more confident than scored
    # against the full (stock) weight table, because it isn't penalised for the
    # fundamentals it structurally cannot have.
    etf = _strong_etf()
    with_appl = score_recommendation(etf, horizon=Horizon.MEDIUM_LONG,
                                     applicable_keys=ETF_APPLICABLE_KEYS).confidence
    absolute = score_recommendation(etf, horizon=Horizon.MEDIUM_LONG).confidence
    assert with_appl > absolute
    assert with_appl >= WATCH_CONFIDENCE_FLOOR


def test_keyless_etf_tier_spans_action_space():
    # The keyless tier must express the FULL range, not collapse to one action.
    strong = score_recommendation(_strong_etf(), horizon=Horizon.SHORT,
                                  regime=MarketRegime.MODERATE_UPTREND, applicable_keys=ETF_APPLICABLE_KEYS)
    weak = score_recommendation(
        ComponentScores(technical=22, flow_positioning=30, sector_leadership=26, macro_fit=35,
                        risk=55, data_quality=68),
        horizon=Horizon.SHORT, regime=MarketRegime.CORRECTION, applicable_keys=ETF_APPLICABLE_KEYS)
    assert strong.action in _BUY_FAMILY
    assert weak.action in _BEARISH


def test_missing_fundamentals_lowers_stock_confidence():
    # A stock missing its EXPECTED fundamentals is honestly less confident than the
    # same name with them (stocks ARE held to the full applicable set).
    tech_only = dict(technical=76, flow_positioning=70, sector_leadership=72, macro_fit=66,
                     risk=22, data_quality=68)
    full = dict(tech_only, fundamental_quality=80, valuation=62, earnings_revision=78,
                capital_migration=72, emerging_theme=70, data_quality=96)
    c_partial = score_recommendation(ComponentScores(**tech_only), horizon=Horizon.MEDIUM,
                                     applicable_keys=STOCK_APPLICABLE_KEYS).confidence
    c_full = score_recommendation(ComponentScores(**full), horizon=Horizon.MEDIUM,
                                  applicable_keys=STOCK_APPLICABLE_KEYS).confidence
    assert c_full > c_partial
