# Operations Runbook

## Services

- **API** — `uvicorn main:app --app-dir apps/api --port 8000` (FastAPI).
- **Web** — `npm run dev` (dev) or `npm run build && npm run start` (prod) in `apps/web`.
- **Worker** — APScheduler jobs **[Planned]**; until then, drive pipelines via the
  protected endpoints (cron/external scheduler hitting them with `x-cron-secret`).

## Scheduled pipelines (America/New_York)

| When (ET) | Action | Endpoint |
|---|---|---|
| 07:00 | Premarket brief | `POST /api/v1/pipelines/daily-brief` |
| 12:30 | Midday update | (same, type=midday) |
| 16:15 | Closing analysis | (same, type=closing) |
| 18:00 | Full daily brief | `POST /api/v1/pipelines/daily-brief` |
| hourly | News sync | `POST /api/v1/pipelines/news-sync` |
| on demand | Orchestrator / recommendations | `/api/v1/orchestrator/run`, `/api/v1/pipelines/recommendations` |

Use a scheduler with IANA-timezone support (handles DST), or a frequent UTC tick
gated by ET local time. Duplicate briefs for the same (date, type, language) are
prevented by an upsert + the unique index; `pipeline_locks` guards concurrent runs.

## Health

`GET /health`, `GET /health/providers` (db/redis/market/macro/news/llm),
`GET /health/pipelines`. Never exposes secrets.

## Common issues

- **"API connection failed" in the web** — API not running, wrong
  `NEXT_PUBLIC_API_BASE_URL`, or the web origin missing from `CORS_ALLOW_ORIGINS`.
- **All values MOCK** — `MARKET_DATA_PROVIDER=mock` or Yahoo unreachable. Check
  `/health/providers`; mock is always labelled.
- **Pipelines 503** — set `ADMIN_API_KEY`/`CRON_SECRET`.
- **Slow first overview (~10–12 s)** — cold Yahoo fetch of ~14 symbols + FRED;
  warm cache (90 s TTL) is sub-second.
- **LLM not used** — needs `AGENT_RUNTIME=llm` + `ANTHROPIC_API_KEY`; otherwise
  deterministic mock (by design).

## Backups

The SQLite file (`us_watcher.db`) or Postgres DB holds immutable recommendation
history and audit events — back it up; never hand-edit recommendation rows.
