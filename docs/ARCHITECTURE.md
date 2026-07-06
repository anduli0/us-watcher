# Architecture

Status legend: **[Implemented]**, **[Partial]**, **[Planned]**.

## Layers (dependency rule: everything points inward at `domain/`)

```
apps/api/main.py            → FastAPI entrypoint (uvicorn)
apps/web                    → Next.js 15 web app
src/us_watcher/
  domain/                   # pure, no I/O
    analytics/              # indicators, features (returns, MA, RSI, MACD, ATR, vol, drawdown, RS) [Implemented]
    regime/                 # config (weights/bands), score, derive [Implemented]
    recommendation/         # config (weights), scoring, features, schemas [Implemented]
    agents/                 # catalog (23+3), schemas (SpecialistOpinion) [Implemented]
    enums.py time.py money.py universe.py
  infrastructure/
    marketdata/             # base (Protocol), yahoo (keyless), mock, factory (fallback) [Implemented]
    macro/fred.py           # keyless FRED CSV [Implemented]
    news/                   # base, google_rss (defusedxml), mock, factory [Implemented]
    llm/                    # base (LLMProvider), anthropic, mock, factory [Implemented]
    db.py redis_client.py
  db/                       # models (15 tables), types (DecimalString), repositories, seed [Implemented]
  api/                      # app (CORS+security headers), deps (auth+rate limit), routes/ (11 modules) [Implemented]
  agent_service/            # orchestrator, router, recommendation_pipeline [Implemented]
  newsfeed/service.py       # ingest→sanitize→dedup→cluster→importance→persist [Implemented]
  briefing/service.py       # full daily brief EN+KO + What Changed [Implemented]
  accuracy/                 # service (metrics), methodology [Partial: outcome eval scaffolded]
  worker/                   # APScheduler jobs [Planned]
alembic/                    # async env + initial migration [Implemented]
```

## Request flow (read path)

Browser (`apps/web`) → `GET /api/v1/*` → route → `MarketService` /
repositories → providers (Yahoo/FRED, cached TTL) → deterministic analytics →
DTOs with `DataStatus` + `as_of` → JSON. The web renders with KO/EN + Simple/Pro.

## Analysis flow (agent run)

`POST /api/v1/orchestrator/run` → freeze overview snapshot → build evidence pack
→ `router.select_agents` (dynamic, 7–12 of 23; contrarian + auditor always) →
per-agent `SpecialistOpinion` (direction/confidence computed deterministically;
LLM enriches prose only) → adversarial + audit lenses → deterministic weighted
aggregation with same-desk correlation discount → persist `orchestrator_runs` +
`agent_runs` (+ token usage). One agent failing never aborts the run.

## Recommendation flow

`POST /api/v1/pipelines/recommendations` → snapshot + rotation → per-candidate
deterministic component scores (technical, flow proxy, sector leadership, macro
fit; fundamentals/CMS left null in the keyless tier and reweighted out) →
`score_recommendation(horizon, regime)` → `Recommendation` with scenarios, risks,
invalidation, dissent → **append** immutable revision (lineage = ticker:horizon).

## Data status model

`DataStatus`: REAL_TIME · DELAYED · END_OF_DAY · PROXY · ESTIMATED · STALE ·
UNAVAILABLE · MOCK. Yahoo values are `DELAYED` (or `STALE` if old); FRED is
`END_OF_DAY`; offline is `MOCK`. The overview rolls these up to a `data_quality`
of fresh/mixed/stale and surfaces unmeasured regime components.

## Persistence

SQLite (aiosqlite) for local/CI; Postgres (asyncpg) for prod via `DATABASE_URL`.
Dialect-agnostic schema; Alembic owns prod schema. `audit_events` is append-only.

## Caching / performance

In-process TTL cache (90 s) for aggregates keeps within Yahoo's keyless limits.
Web is statically prerendered (App Router) and fetches client-side. Cold overview
(~14 symbols + FRED) ≈ 10–12 s; warm ≈ <100 ms. **[Partial]** ETag/response
caching and server result caching are future work.
