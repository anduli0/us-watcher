"""Market-regime weights and classification thresholds.

Stored as configuration (spec §12: "store weights and thresholds in
configuration") so they can be tuned without touching the scoring logic. These
defaults are an explicit, documented starting point — NOT immutable truth.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from us_watcher.domain.enums import MarketRegime

# Component weights (spec §12). Components for which no data is available are
# dropped and the remaining weights are renormalised, so the composite is always
# computed over only what was actually measured.
DEFAULT_COMPONENT_WEIGHTS: dict[str, float] = {
    "trend": 0.20,
    "breadth": 0.16,
    "volatility": 0.12,
    "liquidity": 0.08,
    "credit": 0.08,
    "earnings": 0.10,
    "macro_surprise": 0.08,
    "valuation": 0.06,
    "positioning": 0.06,
    "cross_asset": 0.06,
}

# Composite-score (-100..+100) -> coarse band classification (spec §12).
# (low_inclusive, high_inclusive, regime, ko_label, en_label)
SCORE_BANDS: list[tuple[float, float, MarketRegime, str, str]] = [
    (35.0, 100.0, MarketRegime.STRONG_UPTREND, "강한 상승추세", "Strong expansion / bull"),
    (10.0, 34.999, MarketRegime.MODERATE_UPTREND, "완만한 상승", "Moderate / selective risk-on"),
    (-9.0, 9.999, MarketRegime.NEUTRAL_RANGE, "중립 / 박스권", "Neutral / range-bound"),
    (-34.0, -9.001, MarketRegime.CORRECTION, "조정 / 위험회피", "Correction / risk-off"),
    (-100.0, -34.001, MarketRegime.BEAR_MARKET, "구조적 약세", "Structural bear / contraction"),
]


class RegimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component_weights: dict[str, float] = DEFAULT_COMPONENT_WEIGHTS
    # Breadth divergence threshold: if cap-weight strongly outpaces equal-weight,
    # a "strong uptrend" is reclassified as a SELECTIVE_BULL (narrow advance).
    selective_breadth_gap: float = 0.04
    # VIX level above which an up-tape is flagged OVERHEATED / fragile.
    overheated_vix: float = 22.0


DEFAULT_REGIME_CONFIG = RegimeConfig()
