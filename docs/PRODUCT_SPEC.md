# Product Spec

## Purpose

Answer, every day, with transparent evidence: *why* the U.S. market moved,
whether the move was broad or mega-cap-led, where capital is rotating, what regime
we are in, whether macro/rates/credit/earnings/valuation support or oppose the
tape, how policy/geopolitics flow through to industries, what is already priced
in, and what to buy / accumulate / hold / watch / reduce / sell / avoid — across
short, medium, and medium-to-long horizons. Long-term lens: "stand where the money
is going before the crowd fully arrives," interpreted analytically via the Capital
Migration Score (capex, backlog/RPO, flows, policy, moats), never as hype.

## Tabs (web)

U.S. Overview · S&P 500 · Nasdaq · Dow Jones · NYSE · Sector & Rotation ·
Macro & Policy · AI Recommendations · News Scrapbook · Daily Brief ·
Accuracy & Methodology · Agents. Sticky horizontal nav (scrollable on mobile),
Korean/English, Simple/Professional views, dark-first, accessible.

## Market taxonomy

S&P 500 / Nasdaq / Dow / NYSE are **Market & Index Watchers** (not "sectors").
Sector/industry analysis lives under **Sector & Rotation** (11 GICS sectors +
style/factor leadership + rotation quadrants).

## Non-negotiables

Deterministic quant vs LLM interpretation separation · no fabricated live data
(labelled statuses) · point-in-time integrity · immutable recommendation history ·
evidence/confidence/risks/invalidation/dissent on every recommendation · bold but
evidence-based (no guaranteed returns, no fabricated target prices) · bilingual
output stored separately · prompt-injection & SSRF defense · disclaimer & ownership.

## Implemented vs planned

- **Implemented**: all 11 tabs + Agents; overview/regime/cross-assets; four index
  watchers; sector & rotation; macro spine; AI recommendations across **stocks +
  ETFs** (3 horizons, 8 actions, scenarios, dissent, immutable history) driven by
  **real fundamentals/valuation/earnings-revisions + a partial Capital Migration
  Score**; news ingestion/dedup/clustering/importance; daily brief (EN+KO + What
  Changed); agent orchestration (dynamic activation, structured output, contrarian
  + audit, aggregation, persistence, token logging) with **live LLM (Anthropic)
  Chief synthesis**; **accuracy: live outcome tracking + point-in-time backtest**;
  **APScheduler worker** (ET-cron briefs/news/orchestrator/recommendations/eval);
  security layer; Alembic migrations; deterministic analytics with unit tests (63).
  Capital Migration Score now sourced partly from **official SEC EDGAR** capex/R&D
  filings (coverage ~55%); **covered-call ETFs** analyzed with a structural overlay
  (capped upside, NAV erosion, distribution≠total-return); **SSE live committee
  feed** (`/api/v1/agents/stream`) with polling fallback; **Docker** compose drafted.
- **Partial / provider-dependent**: CMS backlog/RPO (need deeper filing parsing —
  reweighted out, not faked); ETag/server result caching; live outcome metrics
  populate as horizons mature; Docker images drafted but not yet verified on a host.
- **Planned**: backlog/RPO XBRL parsing; option-chain-based covered-call depth.
