# Data Sources & Licenses

The provider-adapter architecture (`infrastructure/marketdata|macro|news`,
`infrastructure/llm`) keeps the app loosely coupled. Default tier is **keyless**.

| Source | Use | Status label | Notes / licensing |
|---|---|---|---|
| Yahoo Finance chart endpoint | Index/ETF/cross-asset quotes & daily OHLCV | `DELAYED` / `STALE` | Public best-effort endpoint. Treated as **delayed**, never real-time. We store derived features, not redistributed raw index data. Swap for a licensed provider (Polygon/Finnhub/Tiingo/Twelve Data) behind `MarketDataProvider`. |
| FRED (`fredgraph.csv`) | Treasury yields, curve, fed funds, breakevens, real yields | `END_OF_DAY` | Keyless CSV serves latest revised values. With `FRED_API_KEY`, the JSON/ALFRED API unlocks **vintage** (point-in-time) data. |
| Yahoo quoteSummary (crumb flow) | Stock fundamentals: margins, growth, ROE, FCF, fwd P/E, PEG, EPS-revisions, analyst targets, distribution yield | n/a | Keyless via cookie+crumb. Powers stock recommendation scores; analyst targets stored as **third-party consensus** (attributed), never our own target. |
| **SEC EDGAR** (`data.sec.gov` XBRL `companyconcept`) | Official capital expenditure & R&D (annual 10-K) → CMS `capex_growth` / `hiring_rnd_patents` | `END_OF_DAY` | Keyless official primary source; requires a declared User-Agent. The literal "where the money is going" signal — never proxied from price. |
| Google News RSS | News leads (title + link + metadata) | n/a | **Lead-only**: we store titles + metadata + short summaries, never full article text. Parsed with `defusedxml`. |
| Anthropic | LLM interpretation/critique/editing (optional) | n/a | Only when `AGENT_RUNTIME=llm` + `ANTHROPIC_API_KEY`. Degrades to deterministic mock otherwise. |
| Mock providers | Offline/fallback | `MOCK` | Deterministic, always labelled; never presented as live. |

## Prohibited practices (enforced by design)

- No paywall bypass; no storing full copyrighted articles; no unauthorized
  scraping as the production source of truth; no redistributing unlicensed
  real-time index data; no presenting unofficial data as official.
- No current-constituents-in-historical-backtests without point-in-time
  correction (backtester is point-in-time aware by construction).

## Status taxonomy

`REAL_TIME · DELAYED · END_OF_DAY · PROXY · ESTIMATED · STALE · UNAVAILABLE · MOCK`
— attached to every data item and surfaced in the UI when material.

## Proxies

NYSE/Nasdaq composite *breadth* internals are not keyless; we use explicitly
labelled equal-weight / small-cap participation proxies and never fabricate
advance-decline or new-high/low series (they return `UNAVAILABLE`).
