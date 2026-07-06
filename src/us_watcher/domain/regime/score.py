"""Deterministic Market Regime Score (spec §12).

Each component is a sub-score in [-1, +1] (bullish positive). The composite is a
weighted average over the components that are *available*, rescaled to
[-100, +100]. Components with no data are excluded and the remaining weights are
renormalised — so a missing credit feed never silently pulls the score to zero,
it simply isn't counted (and is reported in ``unavailable``).

The composite then maps to one of the 11 regime labels. A broad up-tape that is
actually narrow (cap-weight >> equal-weight) is reclassified SELECTIVE_BULL; a
strong tape with an elevated VIX is flagged OVERHEATED_RALLY (spec §6.1).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from us_watcher.domain.enums import MarketRegime
from us_watcher.domain.regime.config import DEFAULT_REGIME_CONFIG, SCORE_BANDS, RegimeConfig


class RegimeComponents(BaseModel):
    """Each field is a sub-score in [-1, 1], or ``None`` when unavailable."""

    model_config = ConfigDict(extra="forbid")

    trend: float | None = None
    breadth: float | None = None
    volatility: float | None = None
    liquidity: float | None = None
    credit: float | None = None
    earnings: float | None = None
    macro_surprise: float | None = None
    valuation: float | None = None
    positioning: float | None = None
    cross_asset: float | None = None


class RegimeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: float  # -100 .. +100
    regime: MarketRegime
    regime_ko: str
    regime_en: str
    confidence: float  # 0 .. 100
    components: RegimeComponents
    available: list[str]
    unavailable: list[str]
    coverage: float  # fraction of weight that was measurable


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _classify_band(score: float) -> tuple[MarketRegime, str, str]:
    for lo, hi, regime, ko, en in SCORE_BANDS:
        if lo <= score <= hi:
            return regime, ko, en
    return MarketRegime.NEUTRAL_RANGE, "중립 / 박스권", "Neutral / range-bound"


def compute_regime(
    components: RegimeComponents,
    *,
    cap_minus_equal_weight: float | None = None,
    vix_level: float | None = None,
    config: RegimeConfig = DEFAULT_REGIME_CONFIG,
) -> RegimeResult:
    """Aggregate component sub-scores into a composite regime classification."""
    weights = config.component_weights
    values = components.model_dump()

    available: list[str] = []
    unavailable: list[str] = []
    weighted_sum = 0.0
    weight_total = 0.0
    for name, w in weights.items():
        v = values.get(name)
        if v is None:
            unavailable.append(name)
            continue
        available.append(name)
        weighted_sum += _clamp(float(v), -1.0, 1.0) * w
        weight_total += w

    coverage = weight_total / sum(weights.values()) if weights else 0.0
    if weight_total == 0.0:
        return RegimeResult(
            score=0.0,
            regime=MarketRegime.TRANSITION_WATCH,
            regime_ko="데이터 불확실",
            regime_en="Insufficient data",
            confidence=0.0,
            components=components,
            available=available,
            unavailable=unavailable,
            coverage=0.0,
        )

    norm = weighted_sum / weight_total  # -1 .. 1
    score = round(_clamp(norm * 100.0, -100.0, 100.0), 1)

    regime, ko, en = _classify_band(score)

    # --- Nuance overlays (spec §6.1, §6.4) ---
    gap = config.selective_breadth_gap
    if regime in (MarketRegime.STRONG_UPTREND, MarketRegime.MODERATE_UPTREND):
        if cap_minus_equal_weight is not None and cap_minus_equal_weight >= gap:
            regime, ko, en = (
                MarketRegime.SELECTIVE_BULL,
                "선별적 강세 (대형주 주도)",
                "Selective mega-cap-led advance",
            )
        elif vix_level is not None and vix_level >= config.overheated_vix and score >= 35.0:
            regime, ko, en = (
                MarketRegime.OVERHEATED_RALLY,
                "과열 랠리",
                "Overheated rally",
            )

    # Confidence scales with both conviction (|score|) and data coverage, so a
    # high score computed from few components is reported with humility.
    confidence = round(_clamp((40.0 + abs(score) * 0.6) * (0.5 + 0.5 * coverage), 0.0, 95.0), 1)

    return RegimeResult(
        score=score,
        regime=regime,
        regime_ko=ko,
        regime_en=en,
        confidence=confidence,
        components=components,
        available=available,
        unavailable=unavailable,
        coverage=round(coverage, 3),
    )
