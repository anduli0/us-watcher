"""Deterministic recommendation scoring (spec §24-26).

Pure functions: component scores (0-100) + horizon + regime + risk -> a total
score, an action, and a transparent per-component contribution breakdown. No LLM
math here. Missing features are handled by renormalising over the components that
ARE present (a missing feature never silently scores 0 and drags the total down).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from us_watcher.domain.enums import Horizon, MarketRegime, RecAction
from us_watcher.domain.recommendation.config import (
    ACTION_THRESHOLDS,
    ATTENTION_BONUS_MAX,
    ATTENTION_HORIZON_FACTOR,
    BASE_CONFIDENCE,
    CALIBRATION_BLEND,
    CMS_WEIGHTS,
    HORIZON_WEIGHTS,
    RISK_OFF_BUY_SHIFT,
    RISK_OFF_CONFIDENCE_HAIRCUT,
    RISK_OFF_REGIMES,
    RISK_PENALTY_MAX,
    SHORT_BUY_HI_CONVICTION_FLOOR,
    WATCH_CONFIDENCE_FLOOR,
)


class ComponentScores(BaseModel):
    """0-100 per component; ``None`` means the feature was unavailable."""

    model_config = ConfigDict(extra="forbid")

    technical: float | None = None
    fundamental_quality: float | None = None
    valuation: float | None = None
    earnings_revision: float | None = None
    sector_leadership: float | None = None
    macro_fit: float | None = None
    news_catalyst: float | None = None
    capital_migration: float | None = None
    emerging_theme: float | None = None
    flow_positioning: float | None = None
    risk: float = 0.0  # 0 = safe, 100 = maximally risky (separate deduction)
    data_quality: float = 50.0


class ScoreResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_score: float = Field(ge=0.0, le=100.0)
    raw_weighted: float
    risk_penalty: float
    action: RecAction
    horizon: Horizon
    coverage: float
    contributions: dict[str, float]
    missing: list[str]
    confidence: float


# Regime nudges: in risk-off/bear regimes, defensive tilt — discount the
# weighted score; in expansions, a modest premium. Applied multiplicatively.
_REGIME_FACTOR: dict[MarketRegime, float] = {
    MarketRegime.STRONG_UPTREND: 1.05,
    MarketRegime.MODERATE_UPTREND: 1.02,
    MarketRegime.BROAD_EXPANSION: 1.04,
    MarketRegime.SELECTIVE_BULL: 1.00,
    MarketRegime.ROTATION_EXPANSION: 1.01,
    MarketRegime.OVERHEATED_RALLY: 0.97,
    MarketRegime.NEUTRAL_RANGE: 1.00,
    MarketRegime.CORRECTION: 0.93,
    MarketRegime.RISK_OFF: 0.90,
    MarketRegime.BEAR_MARKET: 0.85,
    MarketRegime.TRANSITION_WATCH: 0.97,
}


def capital_migration_score(components: dict[str, float]) -> tuple[float, float]:
    """Compute the CMS (0-100) from its weighted components (spec §25).

    Returns (score, coverage). Components are 0-100; unavailable ones (absent
    from the dict) are reweighted out so price-momentum-only inputs cannot
    masquerade as a full CMS.
    """
    weighted = 0.0
    wsum = 0.0
    for key, w in CMS_WEIGHTS.items():
        v = components.get(key)
        if v is None:
            continue
        weighted += max(0.0, min(100.0, v)) * w
        wsum += w
    if wsum == 0.0:
        return 0.0, 0.0
    return round(weighted / wsum, 1), round(wsum / sum(CMS_WEIGHTS.values()), 3)


def score_recommendation(
    scores: ComponentScores,
    *,
    horizon: Horizon,
    regime: MarketRegime = MarketRegime.NEUTRAL_RANGE,
    base_confidence: float = BASE_CONFIDENCE,
    applicable_keys: frozenset[str] | set[str] | None = None,
    confidence_target: float | None = None,
    attention: float | None = None,
) -> ScoreResult:
    """Compute the total score, action, and contribution breakdown.

    ``applicable_keys`` — the component keys *knowable for this instrument's data
    tier* (see ``config.ETF_APPLICABLE_KEYS`` / ``STOCK_APPLICABLE_KEYS``). When
    given, confidence coverage is measured against the APPLICABLE weight, not the
    full weight table, so an ETF is never scored as "low confidence" for
    fundamentals it structurally cannot have. The weighted-average renormalisation
    (``raw``) still uses present-component coverage — that math is unchanged.

    ``confidence_target`` — empirical hit-rate target (0-100) from
    ``accuracy.calibration``. When given, the structural confidence is blended
    toward it so displayed confidence tracks MEASURED base rates instead of
    coverage heuristics alone (the realized-accuracy feedback loop).
    """
    weights = HORIZON_WEIGHTS[horizon]
    values = scores.model_dump()

    weighted = 0.0
    wsum = 0.0
    contributions: dict[str, float] = {}
    missing: list[str] = []
    for key, w in weights.items():
        v = values.get(key)
        if v is None:
            missing.append(key)
            continue
        clamped = max(0.0, min(100.0, float(v)))
        contributions[key] = round(clamped * w / 100.0, 2)
        weighted += clamped * w
        wsum += w

    coverage = wsum / sum(weights.values()) if weights else 0.0
    raw = (weighted / wsum) if wsum > 0 else 0.0  # 0-100 normalised over present

    # Confidence coverage: honest, asset-class-aware. Measure present weight
    # against the APPLICABLE weight (not the full table) so an ETF fully covered
    # on its applicable signals reads as well-covered, while a stock missing its
    # expected fundamentals reads as genuinely under-covered.
    if applicable_keys is not None:
        appl_weight = sum(w for k, w in weights.items() if k in applicable_keys)
        present_appl = sum(w for k, w in weights.items() if k in applicable_keys and values.get(k) is not None)
        conf_coverage = (present_appl / appl_weight) if appl_weight > 0 else coverage
    else:
        conf_coverage = coverage
    conf_coverage = max(0.0, min(1.0, conf_coverage))

    # Regime nudge
    adjusted = raw * _REGIME_FACTOR.get(regime, 1.0)

    # Risk penalty (separate deduction, spec §24)
    risk_penalty = round((scores.risk / 100.0) * RISK_PENALTY_MAX, 2)

    # Attention nudge (separate, capped ADDITION — the editorial-heat axis not in any
    # weighted component). Transparent: shown in the contribution breakdown.
    attention_bonus = 0.0
    if attention:
        factor = ATTENTION_HORIZON_FACTOR.get(horizon, 0.0)
        attention_bonus = round((max(0.0, min(100.0, attention)) / 100.0) * ATTENTION_BONUS_MAX * factor, 2)
        if attention_bonus > 0.0:
            contributions["attention"] = attention_bonus

    total = max(0.0, min(100.0, adjusted - risk_penalty + attention_bonus))

    # Confidence blends base confidence, applicable-signal coverage, and data
    # quality. A well-covered call (keyless ETF or fundamentals-backed stock)
    # clears the WATCH floor; thin or partial coverage stays below it.
    confidence = max(0.0, min(95.0,
                              base_confidence * (0.6 + 0.4 * conf_coverage)
                              * (0.75 + 0.25 * scores.data_quality / 100.0)))

    # Risk-off regime gate (config, measured): long edge collapses when the
    # market is below trend, so buy-side actions need a stiffer score bar and
    # confidence takes the measured haircut.
    risk_off = regime in RISK_OFF_REGIMES
    if risk_off:
        confidence = max(0.0, confidence - RISK_OFF_CONFIDENCE_HAIRCUT)

    # Empirical calibration: pull confidence toward the measured hit-rate target.
    if confidence_target is not None:
        confidence = (1.0 - CALIBRATION_BLEND) * confidence + CALIBRATION_BLEND * confidence_target
    confidence = round(confidence, 1)

    action = decide_action(
        total, confidence=confidence, risk=scores.risk,
        buy_shift=RISK_OFF_BUY_SHIFT if risk_off else 0.0,
        # Short-horizon selectivity (measured): only the hi-conviction score
        # bucket separates at 20d, so short committed buys need score >= 70.
        hi_conviction_floor=SHORT_BUY_HI_CONVICTION_FLOOR if horizon is Horizon.SHORT else None,
    )
    return ScoreResult(
        total_score=round(total, 1),
        raw_weighted=round(raw, 1),
        risk_penalty=risk_penalty,
        action=action,
        horizon=horizon,
        coverage=round(coverage, 3),
        contributions=contributions,
        missing=missing,
        confidence=confidence,
    )


def decide_action(
    total: float, *, confidence: float, risk: float, buy_shift: float = 0.0,
    hi_conviction_floor: float | None = None,
) -> RecAction:
    """Map total score -> action with WATCH/AVOID nuance (spec §23).

    Uncertain cases are NOT all forced to HOLD: a promising score held back by
    low confidence becomes WATCH; a structurally unattractive risk/reward becomes
    AVOID rather than SELL. ``buy_shift`` raises the buy-side thresholds (used by
    the risk-off regime gate — a bear-market BUY must clear a stiffer bar).
    ``hi_conviction_floor`` steps a committed buy down one level below it (the
    short-horizon selectivity gate: only the >=70 score bucket separated in the
    20d backtest calibration, +5.7% vs ~+2% for every bucket below).
    """
    t = ACTION_THRESHOLDS
    if risk >= 78.0 and total < t["buy"] + buy_shift:
        base = RecAction.AVOID
    elif total >= t["strong_buy"] + buy_shift:
        base = RecAction.STRONG_BUY
    elif total >= t["buy"] + buy_shift:
        base = RecAction.BUY
    elif total >= t["accumulate"] + buy_shift:
        base = RecAction.ACCUMULATE
    elif total >= t["hold"]:
        base = RecAction.HOLD
    elif total >= t["reduce"]:
        base = RecAction.REDUCE
    elif total >= t["sell"]:
        base = RecAction.SELL
    else:
        base = RecAction.AVOID

    # Measured selectivity: below the hi-conviction floor the forward-return
    # edge is flat, so a committed buy steps down one action level.
    if hi_conviction_floor is not None and total < hi_conviction_floor:
        if base is RecAction.STRONG_BUY:
            base = RecAction.BUY
        elif base is RecAction.BUY:
            base = RecAction.ACCUMULATE

    # Publishable-edge gate (spec §32): a directional call whose CALIBRATED
    # confidence is below the floor (60% — a real margin over the 50% coin flip)
    # lacks a publishable edge and is never shown as committed advice. Promising
    # but under-confirmed buys -> WATCH; an unconfident sell-side call -> HOLD
    # (the ladder's neutral stance — the measured sell priors are far under the bar).
    if confidence < WATCH_CONFIDENCE_FLOOR:
        if base in (RecAction.STRONG_BUY, RecAction.BUY, RecAction.ACCUMULATE):
            return RecAction.WATCH
        if base in (RecAction.REDUCE, RecAction.SELL, RecAction.AVOID):
            return RecAction.HOLD
    return base
