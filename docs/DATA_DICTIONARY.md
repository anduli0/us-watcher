# Data Dictionary

ORM models in `src/us_watcher/db/models.py`. Timestamps are tz-aware UTC.
Decimals stored as TEXT via `DecimalString`. JSON columns hold structured payloads.

| Table | Purpose | Key columns |
|---|---|---|
| `instruments` | Tracked universe (seeded from `config/universe.yml`) | symbol (PK), name, group, asset_type, market, gics, yahoo_symbol, is_proxy |
| `macro_observations` | Point-in-time macro series | series_id, observation_date, value, **vintage_date**, **available_at**, source, ingested_at |
| `regime_snapshots` | Persisted regime computations | as_of, score, regime, confidence, coverage, payload |
| `news_articles` | Deduped news leads (titles+metadata only) | id=content_hash (PK), title, url, publisher, published_at, importance, reliability, cluster_id, related(JSON) |
| `news_clusters` | Event clusters | id (PK), headline, importance, article_count, last_seen, related(JSON) |
| `orchestrator_runs` | Agent runs (supervisory) | id (PK), objective, trigger, status, selected_agents(JSON), runtime, token_usage, cost_usd, payload |
| `agent_runs` | Per-specialist output | id (PK), orchestrator_run_id (FK), agent_id, status, direction, confidence, model_name, token_usage, output(JSON), error |
| `recommendations` | **Immutable** rec revisions | id (PK), lineage_id, revision, change_type, ticker, asset_type, horizon, action, total_score, confidence, as_of, expires_at, data_freshness, payload(JSON) |
| `recommendation_outcomes` | Evaluation vs benchmark | recommendation_id (FK), lineage_id, horizon_days, entry/exit price, abs/excess return, benchmark, status |
| `daily_briefings` | Briefs (KO+EN stored separately) | (briefing_date, briefing_type, language) **unique**, headline, payload(JSON), generated_by |
| `pipeline_runs` | Pipeline executions | id (PK), pipeline, status, started/finished, detail(JSON) |
| `pipeline_locks` | Duplicate-run prevention | key (PK), holder, acquired_at, expires_at |
| `model_usage` | Token/cost ledger | run_id, provider, model, role, input/output tokens, cost_usd |
| `audit_events` | **Append-only** audit | action, entity_type, entity_id, summary, payload(JSON), created_at |
| `data_quality_events` | Stale/unavailable/mock/injection | kind, symbol, detail, created_at |

## Key enums (`domain/enums.py`)

`MarketDirection, Horizon (short|medium|medium_long), Impact, MarketCode,
MarketRegime (11), DataStatus (8), DataQuality (fresh|mixed|stale),
RotationQuadrant (4), StyleFactor, RecAction (8), AssetType, Language (ko|en),
BriefingType`.

## Point-in-time fields (spec §3.2)

`observed_at / available_at / as_of / published_at / ingested_at / vintage_date /
provider / source_url / content_hash` are used where applicable so backtests can
honour what was actually known at a historical decision time.
