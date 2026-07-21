"""Static methodology document served at /api/v1/methodology (spec §32).

Describes the regime engine, scoring, horizons, benchmarks, metrics, and the
bias-prevention rules. Kept in code (not an LLM output) so it is authoritative
and versioned with the implementation.
"""

from __future__ import annotations

METHODOLOGY: dict = {
    "version": "0.1.0",
    "regime_engine": {
        "summary": "Deterministic composite score in [-100, +100] over weighted components; "
        "components with no data are excluded and remaining weights renormalised.",
        "components": [
            "trend", "breadth", "volatility", "liquidity", "credit", "earnings",
            "macro_surprise", "valuation", "positioning", "cross_asset",
        ],
        "bands": [
            {"range": "+35..+100", "label": "Strong expansion / bull"},
            {"range": "+10..+34", "label": "Moderate / selective risk-on"},
            {"range": "-9..+9", "label": "Neutral / range-bound"},
            {"range": "-34..-10", "label": "Correction / risk-off"},
            {"range": "-100..-35", "label": "Structural bear / contraction"},
        ],
    },
    "recommendation_scoring": {
        "scores": [
            "technical", "fundamental_quality", "valuation", "earnings_revision",
            "sector_leadership", "macro_fit", "news_catalyst", "capital_migration",
            "flow_positioning", "risk", "data_quality",
        ],
        "weights_vary_by": ["market_regime", "horizon"],
        "actions": ["strong_buy", "buy", "accumulate", "hold", "watch", "reduce", "sell", "avoid"],
        "no_target_price_unless": "a defined valuation model, available inputs, shown assumptions, "
        "stated horizon, a range, and explicit uncertainty all exist.",
    },
    "evaluation": {
        "horizons_trading_days": [1, 5, 20, 60, 120, 252],
        "benchmarks": {
            "large_cap": "SPY", "nasdaq_growth": "QQQ", "small_cap": "IWM", "mid_cap": "MDY",
            "sector": "sector ETF", "covered_call_etf": "underlying + income benchmark",
        },
        "metrics": [
            "absolute_return", "excess_return", "hit_rate", "precision", "recall",
            "avg_gain", "avg_loss", "max_drawdown", "risk_adjusted_return", "turnover",
            "transaction_cost_adjusted", "calibration", "brier_score",
        ],
    },
    "confidence_calibration": {
        "summary": "Displayed confidence is anchored to MEASURED base rates, not coverage "
        "heuristics alone: 5-year point-in-time priors (hit rate by horizon, conviction "
        "tier, and market-regime side; embargoed train/test study, reproducible via "
        "signal_lab) blended with live recommendation outcomes as they mature "
        "(sample-size-weighted, so the system's own track record gradually dominates).",
        "early_evidence": "Matured short-window LIVE outcomes feed calibration early at an "
        "explicit discount: 5-day outcomes count toward the 20d bucket at 0.25x their sample "
        "size (a 5d window covers a quarter of the horizon), so tiny samples barely move the "
        "prior while a real track record eventually dominates. 1-day outcomes are excluded — "
        "single-day direction is noise-dominated (measured live: 45.7% hit with positive "
        "expectancy, avg gain +1.41% vs avg loss -1.03%).",
        "publishable_edge_gate": "A directional call must clear 60% CALIBRATED confidence "
        "to be published as committed advice (50% is a pure coin flip; the bar sits a real "
        "margin above it). Below 60% the call is shown only as WATCH (buy-side) or HOLD "
        "(sell-side). Measured sell-side priors are 43.6/36.8/34.0% at H20/60/120 — well "
        "under the bar — so unconfident sells are the biggest leak this gate closes.",
        "short_horizon_selectivity": "Backtest calibration buckets show only the 70-100 "
        "score bucket separates at 20d (+5.7% avg forward return vs ~+2% for every bucket "
        "below); a short-horizon committed buy below score 70 steps down one action level.",
        "regime_gate": "Measured: with the S&P below its 200-DMA, long-signal hit rates "
        "fell to 43-52% (vs 55-65% risk-on) with negative benchmark excess at every "
        "horizon — so in risk-off regimes buy actions need a higher score bar and "
        "confidence takes the measured haircut.",
        "signal_variants_tested": "Slope-aware trend, momentum consistency, 52w-proximity, "
        "overheat penalty, and volatility dampening were tested on embargoed 5y splits and "
        "did NOT beat the baseline signal out-of-sample — the formula was kept unchanged "
        "(documented in signal_lab results).",
    },
    "bias_prevention": [
        "No look-ahead: features use only data available at decision time.",
        "No survivorship bias; delisted securities retained.",
        "Point-in-time macro vintages; never overwrite history with revisions only.",
        "Non-zero transaction costs in performance.",
        "Failed recommendations are never deleted or retroactively modified.",
    ],
    "data_integrity": {
        "principle": "Facts, deterministic calculations, and AI interpretation are kept separate.",
        "llm_never_computes": [
            "returns", "moving averages", "RSI", "MACD", "ATR", "volatility",
            "correlations", "drawdowns", "breadth", "relative strength", "backtests",
        ],
        "statuses": ["REAL_TIME", "DELAYED", "END_OF_DAY", "PROXY", "ESTIMATED", "STALE", "UNAVAILABLE", "MOCK"],
    },
}
