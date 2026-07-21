"""Unit tests for recommendation scoring + CMS (spec §24, §25, §45)."""

from __future__ import annotations

import pytest

from us_watcher.domain.enums import Horizon, MarketRegime, RecAction
from us_watcher.domain.recommendation.config import (
    ATTENTION_BONUS_MAX,
    CMS_WEIGHTS,
    ETF_APPLICABLE_KEYS,
    HORIZON_WEIGHTS,
    STOCK_APPLICABLE_KEYS,
    WATCH_CONFIDENCE_FLOOR,
)
from us_watcher.domain.recommendation.features import (
    blend_sub_industry_cycle,
    sector_leadership_score,
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


# --- Publishable-edge gate (spec §32): a committed directional call must clear
# 60% CALIBRATED confidence. 50% is a pure coin flip; below the 60% bar the call
# is shown only as WATCH (buy-side) / HOLD (sell-side), never as committed advice.


def test_publish_gate_buy_side_at_the_60_boundary():
    assert decide_action(72.0, confidence=59.9, risk=10.0) == RecAction.WATCH
    assert decide_action(72.0, confidence=60.0, risk=10.0) == RecAction.BUY
    # Accumulate and strong_buy are gated too.
    assert decide_action(60.0, confidence=59.9, risk=10.0) == RecAction.WATCH
    assert decide_action(85.0, confidence=59.9, risk=10.0) == RecAction.WATCH


def test_publish_gate_demotes_sub_60_sell_side_to_hold():
    # Sell-side priors are 43.6/36.8/34.0% (H20/60/120) — well under the 60% bar
    # — so an unconfident REDUCE/SELL/AVOID demotes to HOLD, never published.
    assert decide_action(40.0, confidence=59.9, risk=10.0) == RecAction.HOLD   # was REDUCE
    assert decide_action(30.0, confidence=59.9, risk=10.0) == RecAction.HOLD   # was SELL
    assert decide_action(10.0, confidence=59.9, risk=10.0) == RecAction.HOLD   # was AVOID
    # At or above the floor the sell-side call publishes as committed.
    assert decide_action(40.0, confidence=60.0, risk=10.0) == RecAction.REDUCE
    assert decide_action(30.0, confidence=60.0, risk=10.0) == RecAction.SELL


def test_publish_gate_uses_post_calibration_confidence():
    # Through score_recommendation: a REDUCE-range score whose confidence is
    # dragged below the 60% bar by a low empirical target (sell prior far under
    # it) is demoted to HOLD; the same call without the calibration blend publishes.
    scores = _uniform_scores(40.0, data_quality=50.0)
    plain = score_recommendation(scores, horizon=Horizon.MEDIUM,
                                 applicable_keys=STOCK_APPLICABLE_KEYS)
    calibrated = score_recommendation(scores, horizon=Horizon.MEDIUM,
                                      applicable_keys=STOCK_APPLICABLE_KEYS,
                                      confidence_target=36.8)  # measured H60 sell prior
    assert plain.action == RecAction.REDUCE
    assert calibrated.confidence < WATCH_CONFIDENCE_FLOOR
    assert calibrated.action == RecAction.HOLD


# --- Short-horizon selectivity (measured): only the >=70 score bucket separated
# at 20d in the backtest (+5.7% vs ~+2% below), so short committed buys need
# hi conviction or step down one action level.


def test_short_horizon_buy_below_hi_conviction_steps_down():
    assert decide_action(69.0, confidence=60.0, risk=10.0) == RecAction.BUY
    assert decide_action(69.0, confidence=60.0, risk=10.0,
                         hi_conviction_floor=70.0) == RecAction.ACCUMULATE
    # At/above the floor the committed buy stands.
    assert decide_action(70.0, confidence=60.0, risk=10.0,
                         hi_conviction_floor=70.0) == RecAction.BUY


def test_short_horizon_selectivity_through_scoring():
    scores = _uniform_scores(69.0)
    short = score_recommendation(scores, horizon=Horizon.SHORT,
                                 applicable_keys=STOCK_APPLICABLE_KEYS)
    medium = score_recommendation(scores, horizon=Horizon.MEDIUM,
                                  applicable_keys=STOCK_APPLICABLE_KEYS)
    # Same total score; only the SHORT horizon applies the selectivity gate.
    assert short.total_score == medium.total_score == 69.0
    assert medium.action == RecAction.BUY
    assert short.action == RecAction.ACCUMULATE


def _uniform_scores(level: float, *, data_quality: float = 90.0) -> ComponentScores:
    return ComponentScores(
        technical=level, fundamental_quality=level, valuation=level,
        earnings_revision=level, sector_leadership=level, macro_fit=level,
        news_catalyst=level, capital_migration=level, emerging_theme=level,
        flow_positioning=level, risk=0.0, data_quality=data_quality,
    )


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
    # The keyless tier must express the FULL range, not collapse to one action:
    # a strong ETF commits to a buy; a weak one lands in a non-buy stance. Its
    # committed sell is only published if it clears the 60% publishable-edge bar
    # — below it (56% here) the sell-side call correctly demotes to HOLD.
    strong = score_recommendation(_strong_etf(), horizon=Horizon.SHORT,
                                  regime=MarketRegime.MODERATE_UPTREND, applicable_keys=ETF_APPLICABLE_KEYS)
    weak = score_recommendation(
        ComponentScores(technical=22, flow_positioning=30, sector_leadership=26, macro_fit=35,
                        risk=55, data_quality=68),
        horizon=Horizon.SHORT, regime=MarketRegime.CORRECTION, applicable_keys=ETF_APPLICABLE_KEYS)
    assert strong.action in _BUY_FAMILY
    assert weak.action not in _BUY_FAMILY
    assert weak.action in (RecAction.HOLD, RecAction.WATCH, *_BEARISH)


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


# --- Sub-industry cycle blend (memory downcycle vs logic strength) ------------

def test_sub_industry_cycle_drags_a_name_whose_group_is_rolling_over():
    # A memory name whose OWN 1-month RS is flat (+0%) is pulled down once its
    # sub-industry group's cycle RS is deeply negative (the downcycle), and the
    # resulting sector-leadership score is lower than the un-blended one.
    own = 0.0
    dragged = blend_sub_industry_cycle(own, -0.15)  # group −15% vs market
    assert dragged is not None and dragged < own
    assert sector_leadership_score(dragged) < sector_leadership_score(own)


def test_sub_industry_cycle_lifts_a_lagging_member_of_a_strong_group():
    # A logic name lagging (−3%) is lifted when its group cycle is strongly positive.
    own = -0.03
    lifted = blend_sub_industry_cycle(own, 0.12, group_weight=0.4)
    assert lifted is not None and lifted > own


def test_sub_industry_cycle_untouched_without_group_read():
    # Unclassified names (no group cycle) are returned exactly as-is.
    assert blend_sub_industry_cycle(0.05, None) == 0.05
    assert blend_sub_industry_cycle(None, None) is None


def test_sub_industry_cycle_blend_is_a_weighted_average():
    # Explicit weighting contract: 0.6*own + 0.4*group at the default weight.
    assert blend_sub_industry_cycle(0.10, -0.10, group_weight=0.4) == pytest.approx(0.02)


_ATTN_CS = dict(technical=60, flow_positioning=55, sector_leadership=58, macro_fit=55,
                earnings_revision=57, fundamental_quality=55, valuation=55, news_catalyst=55,
                capital_migration=55, emerging_theme=55, risk=20, data_quality=80)


def test_attention_lifts_short_score_but_is_capped():
    cs = ComponentScores(**_ATTN_CS)
    base = score_recommendation(cs, horizon=Horizon.SHORT).total_score
    hot = score_recommendation(cs, horizon=Horizon.SHORT, attention=100)
    assert hot.total_score > base
    assert hot.total_score - base <= ATTENTION_BONUS_MAX + 0.05  # never more than the cap
    assert hot.contributions.get("attention") == pytest.approx(ATTENTION_BONUS_MAX)


def test_attention_is_half_at_medium_and_ignored_long():
    cs = ComponentScores(**_ATTN_CS)
    d_med = (score_recommendation(cs, horizon=Horizon.MEDIUM, attention=100).total_score
             - score_recommendation(cs, horizon=Horizon.MEDIUM).total_score)
    d_long = (score_recommendation(cs, horizon=Horizon.MEDIUM_LONG, attention=100).total_score
              - score_recommendation(cs, horizon=Horizon.MEDIUM_LONG).total_score)
    assert d_med == pytest.approx(ATTENTION_BONUS_MAX / 2, abs=0.06)
    assert d_long == pytest.approx(0.0, abs=0.01)


def test_attention_alone_cannot_manufacture_a_buy():
    # A firmly-HOLD score plus maxed attention must NOT clear the BUY bar — buzz
    # nudges across a threshold at most, it does not conjure a committed buy.
    cs = ComponentScores(technical=48, flow_positioning=47, sector_leadership=48, macro_fit=48,
                         earnings_revision=47, fundamental_quality=48, news_catalyst=47,
                         risk=20, data_quality=80)
    hot = score_recommendation(cs, horizon=Horizon.SHORT, attention=100)
    assert hot.action not in _BUY_FAMILY


def test_universe_separates_memory_from_logic_semis():
    # The classification the whole cycle signal rests on: Micron/SanDisk are memory,
    # Intel/NVIDIA are logic — never lumped into one undifferentiated "semiconductor".
    from us_watcher.domain.universe import get_universe

    groups = get_universe().sub_industry_members()
    assert {"MU", "SNDK"} <= set(groups.get("memory", []))
    assert {"INTC", "NVDA"} <= set(groups.get("semi_logic", []))
    assert "MU" not in groups.get("semi_logic", [])
    assert "INTC" not in groups.get("memory", [])
