"""Confidence calibration + risk-off regime gate (accuracy feedback loop)."""

from __future__ import annotations

from us_watcher.accuracy.calibration import (
    HORIZON_DAYS,
    action_side,
    calibration_summary,
    confidence_target_pct,
)
from us_watcher.domain.enums import Horizon, MarketRegime, RecAction
from us_watcher.domain.recommendation.config import STOCK_APPLICABLE_KEYS
from us_watcher.domain.recommendation.scoring import ComponentScores, score_recommendation


def _full_scores(level: float, *, risk: float = 10.0) -> ComponentScores:
    return ComponentScores(
        technical=level, fundamental_quality=level, valuation=level,
        earnings_revision=level, sector_leadership=level, macro_fit=level,
        news_catalyst=level, capital_migration=level, emerging_theme=level,
        flow_positioning=level, risk=risk, data_quality=90.0,
    )


# ---- empirical targets ----

def test_targets_reflect_measured_skill_ordering():
    # Skill rises with horizon (measured): H120 buy target > H20 buy target.
    t20 = confidence_target_pct(20, 72.0, "buy", risk_on=True)
    t120 = confidence_target_pct(120, 72.0, "buy", risk_on=True)
    assert t20 is not None and t120 is not None and t120 > t20
    # Higher conviction tier -> higher target at the same horizon.
    assert confidence_target_pct(120, 72.0, "buy", risk_on=True) > \
        confidence_target_pct(120, 58.0, "buy", risk_on=True)
    # Long-horizon sells were wrong most often in the 5y sample -> lowest target.
    t_sell = confidence_target_pct(120, 30.0, "sell", risk_on=True)
    assert t_sell is not None and t_sell < t120 and t_sell < 45.0


def test_risk_off_lowers_buy_target():
    on = confidence_target_pct(60, 65.0, "buy", risk_on=True)
    off = confidence_target_pct(60, 65.0, "buy", risk_on=False)
    assert on is not None and off is not None and off < on


def test_neutral_side_and_unknown_horizon_return_none():
    assert confidence_target_pct(60, 50.0, "neutral", risk_on=True) is None
    assert confidence_target_pct(7, 65.0, "buy", risk_on=True) is None


def test_live_rates_shrinkage():
    base = confidence_target_pct(20, 72.0, "buy", risk_on=True)
    small = confidence_target_pct(20, 72.0, "buy", risk_on=True,
                                  live_rates={(20, "buy"): (0.90, 10)})
    large = confidence_target_pct(20, 72.0, "buy", risk_on=True,
                                  live_rates={(20, "buy"): (0.90, 3000)})
    assert base is not None and small is not None and large is not None
    assert small - base < 2.0  # 10 live samples barely move a 300-strong prior
    assert large > 80.0  # 3000 live samples dominate it


def test_early_evidence_h5_discounted_into_h20():
    # Matured 5d live outcomes count toward the 20d bucket at 0.25x their n.
    base = confidence_target_pct(20, 72.0, "buy", risk_on=True)
    tiny = confidence_target_pct(20, 72.0, "buy", risk_on=True,
                                 live_rates={(5, "buy"): (1.0, 12)})
    big = confidence_target_pct(20, 72.0, "buy", risk_on=True,
                                live_rates={(5, "buy"): (0.90, 8000)})
    assert base is not None and tiny is not None and big is not None
    # 12 h5 samples = 3 effective vs the 300-strong prior: barely a nudge, even
    # at a perfect 100% hit rate — small n must not swing confidence.
    assert tiny >= base and tiny - base < 1.0
    # 8000 h5 samples = 2000 effective: the live track record rightly dominates.
    assert big > 80.0


def test_early_evidence_applies_to_sell_side_too():
    base = confidence_target_pct(20, 30.0, "sell", risk_on=True)
    nudged = confidence_target_pct(20, 30.0, "sell", risk_on=True,
                                   live_rates={(5, "sell"): (1.0, 12)})
    assert base is not None and nudged is not None
    assert nudged >= base and nudged - base < 1.0


def test_h1_outcomes_never_reach_calibration():
    # 1d direction is noise-dominated (live: 45.7% hit, positive expectancy) —
    # even a huge h1 sample must have ZERO effect on any target.
    base = confidence_target_pct(20, 72.0, "buy", risk_on=True)
    with_h1 = confidence_target_pct(20, 72.0, "buy", risk_on=True,
                                    live_rates={(1, "buy"): (1.0, 5000)})
    assert with_h1 == base


def test_early_evidence_stacks_with_matured_same_horizon_outcomes():
    # Both sources blend: matured 20d at full weight + 5d at the 0.25 discount.
    only_20 = confidence_target_pct(20, 72.0, "buy", risk_on=True,
                                    live_rates={(20, "buy"): (0.9, 200)})
    both = confidence_target_pct(20, 72.0, "buy", risk_on=True,
                                 live_rates={(20, "buy"): (0.9, 200),
                                             (5, "buy"): (0.9, 200)})
    assert only_20 is not None and both is not None and both > only_20


def test_action_side_mapping():
    assert action_side(RecAction.STRONG_BUY) == "buy"
    assert action_side(RecAction.ACCUMULATE) == "buy"
    assert action_side(RecAction.SELL) == "sell"
    assert action_side(RecAction.AVOID) == "sell"
    assert action_side(RecAction.HOLD) == "neutral"
    assert action_side(RecAction.WATCH) == "neutral"


def test_horizon_days_covers_all_display_horizons():
    assert set(HORIZON_DAYS) == set(Horizon)


def test_calibration_summary_is_transparent():
    s = calibration_summary({(20, "buy"): (0.6, 42), (5, "buy"): (0.75, 12)})
    assert "buy_hit_priors" in s and "regime_hit_at_conviction" in s
    assert s["live_blend"]["h20_buy"] == {"hit": 0.6, "n": 42}
    # Early evidence is surfaced: raw 5d rates + the documented discount.
    assert s["live_blend"]["h5_buy"] == {"hit": 0.75, "n": 12}
    assert s["early_evidence"]["discounts"] == {"h20_from_h5": 0.25}


# ---- scoring integration ----

def test_confidence_target_blends_into_confidence():
    scores = _full_scores(70.0)
    plain = score_recommendation(scores, horizon=Horizon.SHORT,
                                 applicable_keys=STOCK_APPLICABLE_KEYS)
    calibrated = score_recommendation(scores, horizon=Horizon.SHORT,
                                      applicable_keys=STOCK_APPLICABLE_KEYS,
                                      confidence_target=54.0)
    assert calibrated.confidence < plain.confidence
    # Blend lands between the structural confidence and the target.
    assert 54.0 <= calibrated.confidence <= plain.confidence


def test_risk_off_gate_demotes_borderline_buy_and_cuts_confidence():
    scores = _full_scores(66.0)  # lands just above the BUY bar in neutral regime
    neutral = score_recommendation(scores, horizon=Horizon.MEDIUM,
                                   regime=MarketRegime.NEUTRAL_RANGE,
                                   applicable_keys=STOCK_APPLICABLE_KEYS)
    bear = score_recommendation(scores, horizon=Horizon.MEDIUM,
                                regime=MarketRegime.BEAR_MARKET,
                                applicable_keys=STOCK_APPLICABLE_KEYS)
    buy_rank = {RecAction.STRONG_BUY: 3, RecAction.BUY: 2, RecAction.ACCUMULATE: 1}
    # The bear-regime action is strictly less aggressive than the neutral one
    # (regime factor already lowers the score; the gate raises the buy bar too).
    assert buy_rank.get(bear.action, 0) < buy_rank.get(neutral.action, 0)
    assert bear.confidence < neutral.confidence


def test_risk_on_behaviour_unchanged_without_target():
    # Regression guard: in a non-risk-off regime with no calibration target the
    # result is identical to the pre-calibration formula.
    scores = _full_scores(70.0)
    r = score_recommendation(scores, horizon=Horizon.MEDIUM,
                             regime=MarketRegime.MODERATE_UPTREND,
                             applicable_keys=STOCK_APPLICABLE_KEYS)
    assert r.action in (RecAction.BUY, RecAction.STRONG_BUY)
    assert r.confidence > 60.0
