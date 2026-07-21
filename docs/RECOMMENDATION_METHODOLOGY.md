# Recommendation Methodology

Deterministic scoring; LLMs never compute scores. Code:
`domain/recommendation/{config,scoring,features,schemas}.py`.

## Component scores (0–100)

`technical, fundamental_quality, valuation, earnings_revision, sector_leadership,
macro_fit, news_catalyst, capital_migration, emerging_theme, flow_positioning`,
plus `risk` (0 safe … 100 risky, a **separate deduction**) and `data_quality`.

**Keyless-tier honesty:** technical, flow (OBV-style up/down-volume proxy),
sector leadership (relative strength), and macro fit are computed from real data.
Fundamentals, valuation, earnings revision, capital migration, and emerging theme
are left **null** (no keyless source) and reweighted out — we never proxy capital
migration from price momentum (spec §25). They activate when feeds are added.

## Horizon weights (`HORIZON_WEIGHTS`, each sums to 100)

- **Short** — Technical 25, News 20, Flow 15, Sector 15, Macro 10, Earnings 10, Fundamental 5.
- **Medium** — Earnings 20, Sector 15, Fundamental 15, Technical 15, Macro 15, Valuation 10, News 10.
- **Medium-long** — Capital Migration 25, Fundamental 20, Earnings 15, Sector 10,
  Valuation 10, Emerging Theme 10, Macro 5, Technical 5.

`total = clamp(regime_factor × Σ(present weighted)/Σ(present weights) − risk_penalty, 0, 100)`.
Regime nudges the score (e.g. bear ×0.85, strong-bull ×1.05). Missing components
are reweighted, not zeroed (`tests/unit/test_recommendation.py`).

## Actions (8) and the WATCH/AVOID nuance

`strong_buy ≥80, buy ≥68, accumulate ≥58, hold ≥45, reduce ≥35, sell ≥22, else avoid`.
A buy-range score with **low confidence** is demoted to **WATCH** (not forced to
HOLD). High risk with a sub-buy score → **AVOID** (not SELL). Korean labels:
강한 매수/매수/분할매수/보유/관망/비중축소/매도/회피.

**Publishable-edge gate**: a directional call must clear **60%** *calibrated*
confidence to be published as committed advice — 50% is a pure coin flip, so the
bar sits a real margin above it. Below 60% the call is shown only as WATCH
(buy-side) or HOLD (sell-side) (`WATCH_CONFIDENCE_FLOOR`). **Short-horizon selectivity**
(measured): in the point-in-time backtest only the 70–100 score bucket separates
at 20d (+5.7% avg forward vs ~+2% below), so a short-horizon committed buy below
score 70 steps down one action level (`SHORT_BUY_HI_CONVICTION_FLOOR`).

## Capital Migration Score (CMS, 0–100)

`capital_migration_score(components)` over weighted inputs (capex growth, backlog/
RPO/adoption, revenue acceleration/revisions, institutional/ETF flows, private
capital, govt policy, hiring/R&D/patents, supply bottleneck/pricing, moat/
barriers, valuation upside). Partial coverage is reweighted. Guards against
treating momentum/media as capital migration, TAM hand-waving, look-ahead, and
confusing CAPEX spenders with CAPEX beneficiaries.

## Scenarios, evidence, dissent

Each recommendation has bull/base/bear scenarios (probabilities sized from score
& volatility; **no target price** unless a valuation model exists — `target_range`
stays null to avoid false precision), 2–4 reasons, catalysts, risks,
invalidation conditions, a dissenting view, component scores, and `data_freshness`.

## History & evaluation (spec §32)

Recommendations are **immutable**: `recommendations.lineage_id` + `revision` +
`change_type` (initial/upgrade/downgrade/reaffirm/withdraw/expire/invalidate).
Failed recommendations are never deleted. `recommendation_outcomes` tracks
results at 1/5/20/60/120/252 trading days vs a context-appropriate benchmark
(SPY/QQQ). Two surfaces at `/api/v1/accuracy`: (1) **live outcome tracking**
(`accuracy/evaluate.py` + daily worker job + `POST /pipelines/evaluate-
recommendations`) scores recs as horizons mature (failed recs kept; populates
over real time); (2) **point-in-time backtest** (`accuracy/backtest.py`)
validates the deterministic signal over ~2y with NO look-ahead (signal at t uses
only bars[:t+1]), transaction costs, SPY excess, and a calibration table — honestly
labelled in-sample methodology validation, NOT a live tradeable track record.
