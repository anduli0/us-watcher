# ULTRAPLAN — build plan & decisions

## Key decision: fork kospi-watcher's stack (not a TS monorepo)

The spec's TS/Prisma snippets are "similar to" suggestions; the overriding mandate
is to reuse the existing Watcher architecture. All sibling Watchers (kospi/krw/fed)
are Python+FastAPI; **kospi-watcher** is the most advanced (clean `src/` DDD +
Next.js 15 web, deterministic synthesizer, mock/LLM dual runtime, keyless Yahoo +
Google News). US·WATCHER forks that: Zod→Pydantic, Prisma/Drizzle→SQLAlchemy+
Alembic, KRW/KOSPI→US universe, Korea up=red→**US up=green**. Max reuse, real
working system, lowest risk.

## Phase map (spec §44) and status

- **Phase 0 Audit** — done (kospi/krw inspected; reusable patterns identified).
- **Phase 1 Foundation** — config/env, enums/time/money, DataStatus, universe,
  provider interfaces, DB models (15) + DecimalString, audit log, Alembic. ✅
- **Phase 2 Deterministic analytics** — indicators, features, regime (score +
  derive + config), recommendation scoring + CMS, data-quality; unit tests. ✅
- **Phase 3 Core UI** — 11 tabs + Agents, overview, watchers, rotation, macro,
  recommendations, news, brief, methodology; KO/EN; Simple/Pro; states;
  responsive; prod build. ✅
- **Phase 4 Agent orchestration** — registry/router/evidence/dynamic activation/
  structured output/contrarian+audit/aggregation/persistence/token logging. ✅
- **Phase 5 Recommendation engine** — 3 horizons, 8 actions, ETFs/covered-call,
  scenarios, invalidation, dissent, immutable history. ✅
- **Phase 6 News & briefing** — ingest/dedup/cluster/importance, daily brief
  EN+KO + What Changed, duplicate prevention, injection tests. ✅
- **Phase 7 Accuracy & backtesting** — outcome model + accuracy summary +
  methodology; **outcome evaluator/backtester job [Partial]**.
- **Phase 8 Security/reliability/deployment** — secure headers/CORS/rate limit/
  operator auth/SSRF/injection/audit; gates green; docs. ✅ (worker [Planned]).

## Verification

ruff clean · mypy clean (83 files) · 48 unit tests pass · Alembic upgrade/
downgrade/upgrade clean · web typecheck/lint/build pass · all 11 API surfaces and
4 pipelines verified with live Yahoo/FRED/Google data · Overview renders 16 live
cards in-browser · mobile responsive confirmed.
