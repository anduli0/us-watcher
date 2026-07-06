# US·WATCHER — United States Equity Market Intelligence

An operational, AI-driven U.S. stock-market analysis platform: market data,
macro & policy, index and sector/rotation analysis, multi-agent investment
research, evidence-based recommendations (short / medium / medium-to-long),
recommendation tracking, and bilingual (Korean + English) reporting.

> AI-generated analysis for information, research, and education only — **not**
> investment advice. Data may be delayed or inaccurate. See `docs/LEGAL_AND_DISCLAIMER.md`.

## Architecture (at a glance)

- **Backend** — Python ≥3.13, FastAPI, SQLAlchemy 2 (async), Alembic, Pydantic v2.
  `src/`-layout DDD: `domain/` (pure analytics, regime, recommendation, agents),
  `infrastructure/` (market data, macro, news, LLM, db, redis), `api/`,
  `agent_service/`, `newsfeed/`, `briefing/`, `accuracy/`, `worker/`.
- **Web** — Next.js 15 / React 19 App Router (`apps/web`), Tailwind, lucide.
  11 tabs, Korean/English, Simple/Professional views, dark-first, responsive.
- **Data (keyless by default)** — Yahoo Finance (quotes/aggregates), FRED
  (yields/macro CSV), Google News RSS. Each has a labelled mock fallback; the app
  is fully usable offline in `mock` mode and never presents mock data as live.
- **Deterministic quant engine** — all numbers (returns, RSI/MACD/ATR, vol,
  drawdown, breadth, relative strength, market-regime score, recommendation
  scores, Capital Migration Score) are computed in code, never by an LLM.
- **Multi-agent research** — a pool of 23 specialist roles + 3 supervisory roles;
  the orchestrator dynamically activates ~7–12 per run, with adversarial
  (contrarian) review and an evidence audit, then deterministic aggregation.

## Quick start (dockerless, Windows PowerShell)

```powershell
# 1. Backend
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\python -m alembic upgrade head
.\.venv\Scripts\python -m uvicorn main:app --app-dir apps/api --port 8000
#   API docs at http://localhost:8000/docs

# 2. Web (separate terminal)
cd apps/web
npm install
npm run dev        # http://localhost:3000  (set NEXT_PUBLIC_API_BASE_URL if API ≠ :8000)

# 3. Generate content (protected; set CRON_SECRET first, pass header x-cron-secret)
#   POST /api/v1/orchestrator/run
#   POST /api/v1/pipelines/recommendations
#   POST /api/v1/pipelines/news-sync
#   POST /api/v1/pipelines/daily-brief
```

## Environment

Copy `.env.example` → `.env`. The system runs with **zero** keys (mock/keyless).
Optional: `FRED_API_KEY` (ALFRED vintages), `ANTHROPIC_API_KEY` + `AGENT_RUNTIME=llm`
(LLM agents), `CRON_SECRET`/`ADMIN_API_KEY` (operational endpoints),
`TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` (push).

## Quality gates

```powershell
.\.venv\Scripts\python -m ruff check .
.\.venv\Scripts\python -m mypy
.\.venv\Scripts\python -m pytest -q
cd apps/web; npm run lint; npm run typecheck; npm run build
```

## Documentation

See `docs/` — ULTRAPLAN, PRODUCT_SPEC, ARCHITECTURE, AGENT_DESIGN, DATA_DICTIONARY,
DATA_SOURCES_AND_LICENSES, RECOMMENDATION_METHODOLOGY, MARKET_REGIME_METHODOLOGY,
SECURITY, THREAT_MODEL, LEGAL_AND_DISCLAIMER, OPERATIONS_RUNBOOK, DEPLOYMENT.

---

US·WATCHER — Designed, owned, and operated by Minkyu An · 안민규. © 2026 Minkyu An.
All rights reserved. ID-2026-MA-USW-01.
