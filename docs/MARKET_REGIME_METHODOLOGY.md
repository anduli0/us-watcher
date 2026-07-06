# Market Regime Methodology

Deterministic, reproducible, config-driven. Code: `domain/regime/`.

## Composite score (−100 … +100)

Ten components, each a sub-score in [−1, +1] (bullish positive):
`trend, breadth, volatility, liquidity, credit, earnings, macro_surprise,
valuation, positioning, cross_asset`. Default weights in
`domain/regime/config.py::DEFAULT_COMPONENT_WEIGHTS` (tunable).

**Partial-data handling (key property):** components with no data are *excluded*
and the remaining weights are **renormalised** — a missing credit feed never
silently drags the score to zero; it is reported in `unavailable` and lowers
`coverage`. The composite = `100 × Σ(wᵢ·sᵢ)/Σwᵢ` over present components.

## Classification bands (`SCORE_BANDS`, not immutable)

| Score | Regime |
|---|---|
| +35 … +100 | Strong expansion / bull |
| +10 … +34 | Moderate / selective risk-on |
| −9 … +9 | Neutral / range-bound |
| −34 … −10 | Correction / risk-off |
| −100 … −35 | Structural bear / contraction |

**Nuance overlays:** a strong tape where cap-weight (SPY) far outruns
equal-weight (RSP) is reclassified **Selective bull (mega-cap-led)**; a strong
tape with elevated VIX → **Overheated rally**. With no measurable components →
**Transition Watch** (confidence 0).

## Confidence

`confidence = clamp((40 + |score|·0.6) · (0.5 + 0.5·coverage), 0, 95)` — scales
with conviction **and** data coverage, so a high score from few inputs is
reported with humility.

## Component derivation (keyless tier) — `domain/regime/derive.py`

- **trend** — index 20/60-day returns, above-50/200-DMA, 200-DMA slope.
- **breadth** — cap-weight vs equal-weight 20-day divergence (proxy; true
  advance-decline/new-high-low feeds are not keyless and return unavailable).
- **volatility** — VIX level (≈16 neutral, lower supportive, higher a drag).
- **cross_asset** — 2s10s curve and 20-day dollar move.
- liquidity / credit / earnings / macro_surprise / valuation / positioning —
  **unavailable** in the keyless tier (reweighted out; drop in behind the same
  interface when feeds are configured).

## Required quantitative features (computed, never LLM)

Returns (1/5/20/60/120/252d), SMA(20/50/100/200), MA slope, distance from 52w
high, realized volatility, ATR, max drawdown, relative strength. Breadth features
return an explicit unavailable state when the data is not present.

## Tests

`tests/unit/test_regime.py` covers band classification, reweighting (missing
components not zeroed), confidence-vs-coverage, the selective-bull overlay,
score clamping, and determinism.
