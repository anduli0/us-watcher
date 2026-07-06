"""Recommendation scoring weights & thresholds (spec §24, §25).

Weights vary by horizon and are nudged by market regime. Stored as config so
they can be tuned without touching the scoring logic. Each horizon's weights sum
to 100 (verified by unit tests); the Risk score is a SEPARATE deduction, not part
of the weighted sum.
"""

from __future__ import annotations

from us_watcher.domain.enums import Horizon, MarketRegime

# Score component keys (0-100 each), spec §24.
SCORE_KEYS = (
    "technical",
    "fundamental_quality",
    "valuation",
    "earnings_revision",
    "sector_leadership",
    "macro_fit",
    "news_catalyst",
    "capital_migration",
    "emerging_theme",
    "flow_positioning",
)

# Horizon weight tables (must each sum to 100). Risk is deducted separately.
HORIZON_WEIGHTS: dict[Horizon, dict[str, float]] = {
    Horizon.SHORT: {
        "technical": 25, "news_catalyst": 20, "flow_positioning": 15,
        "sector_leadership": 15, "macro_fit": 10, "earnings_revision": 10,
        "fundamental_quality": 5,
    },
    Horizon.MEDIUM: {
        "earnings_revision": 20, "sector_leadership": 15, "fundamental_quality": 15,
        "technical": 15, "macro_fit": 15, "valuation": 10, "news_catalyst": 10,
    },
    Horizon.MEDIUM_LONG: {
        "capital_migration": 25, "fundamental_quality": 20, "earnings_revision": 15,
        "sector_leadership": 10, "valuation": 10, "emerging_theme": 10,
        "macro_fit": 5, "technical": 5,
    },
}

# Capital Migration Score components (must sum to 100), spec §25.
CMS_WEIGHTS: dict[str, float] = {
    "capex_growth": 15,
    "backlog_rpo_adoption": 15,
    "revenue_accel_revisions": 15,
    "institutional_etf_flows": 10,
    "private_capital": 10,
    "govt_policy": 10,
    "hiring_rnd_patents": 5,
    "supply_bottleneck_pricing": 5,
    "moat_barriers": 10,
    "valuation_upside": 5,
}

# Action thresholds on the regime/horizon-adjusted total score (0-100).
ACTION_THRESHOLDS = {
    "strong_buy": 80.0,
    "buy": 68.0,
    "accumulate": 58.0,
    "hold": 45.0,
    "reduce": 35.0,
    "sell": 22.0,
    # below sell -> avoid
}

# Risk penalty: risk score (0-100, higher=riskier) scaled into points subtracted.
RISK_PENALTY_MAX = 22.0
# Confidence floor below which a would-be BUY is demoted to WATCH (spec §23).
WATCH_CONFIDENCE_FLOOR = 45.0

# Base confidence anchor for a fully-covered, good-data call (before coverage &
# data-quality scaling). Tuned so a WELL-COVERED keyless ETF call clears the
# WATCH floor — a clean trend with all its applicable technical/flow/sector/macro
# signals present IS a confident technical call — while genuinely thin or partial
# coverage still lands below the floor and is demoted to WATCH.
BASE_CONFIDENCE = 72.0

# --- Risk-off regime gate (measured, spec §32) -------------------------------
# Evidence (signal_lab, 2026-07-05: 5y point-in-time, 185 symbols, embargoed):
# with the S&P 500 below its 200-DMA, long signals LOSE their edge at every
# horizon — hit rate 43.0/45.3/51.7% (H20/H60/H120) vs 55.3/58.4/65.4% risk-on,
# with negative benchmark excess throughout. So in risk-off regimes a buy-side
# action must clear a stiffer score bar, and its confidence takes a haircut.
RISK_OFF_REGIMES: frozenset[MarketRegime] = frozenset(
    {MarketRegime.CORRECTION, MarketRegime.RISK_OFF, MarketRegime.BEAR_MARKET}
)
# Added to the strong_buy/buy/accumulate thresholds when the regime is risk-off.
RISK_OFF_BUY_SHIFT = 6.0
# Confidence points deducted in risk-off (≈ the measured hit-rate drop).
RISK_OFF_CONFIDENCE_HAIRCUT = 10.0

# Weight of the empirical hit-rate target when blending into the structural
# confidence (0 = ignore evidence, 1 = pure empirical). The realized-accuracy
# feedback loop: confidence should converge toward the measured base rates.
CALIBRATION_BLEND = 0.55

# Component keys that are *knowable* for each data tier, used to measure
# confidence coverage HONESTLY. An ETF has no bottom-up fundamentals, earnings
# revisions, or filing-based capital-migration evidence, so it must NOT be scored
# as "low confidence" for components it structurally cannot have — only genuinely
# absent APPLICABLE signals should depress confidence. (Without this, a fully
# covered ETF tops out around 0.2-0.65 coverage and can never clear the WATCH
# floor, silently masking every BUY/ACCUMULATE as WATCH — the "all 관망" bug.)
ETF_APPLICABLE_KEYS: frozenset[str] = frozenset(
    {"technical", "flow_positioning", "sector_leadership", "macro_fit"}
)
# Stocks can in principle carry every component; missing fundamentals for a stock
# IS a real gap and should lower confidence (it's expected data we didn't get).
STOCK_APPLICABLE_KEYS: frozenset[str] = frozenset(SCORE_KEYS)
