# Deployment

## Local / dockerless (default)

See README "Quick start". SQLite + fakeredis, keyless providers, mock LLM — zero
external dependencies.

## Production

1. **Database** — provision Postgres; set `DATABASE_URL=postgresql+asyncpg://…`.
   Install the prod extra: `pip install -e ".[prod]"` (asyncpg). Run
   `alembic upgrade head` on deploy.
2. **API** — run uvicorn (optionally multiple workers behind a process manager)
   on an internal port; terminate TLS at a reverse proxy. The sibling Watchers
   publish via **Tailscale Funnel** — the same pattern works here.
3. **Web** — `npm run build && npm run start`; set
   `NEXT_PUBLIC_API_BASE_URL` to the public API origin at build time. Add that
   origin to `CORS_ALLOW_ORIGINS`.
4. **Secrets** — set `ADMIN_API_KEY`, `CRON_SECRET`, and (optional)
   `FRED_API_KEY`, `ANTHROPIC_API_KEY` + `AGENT_RUNTIME=llm`,
   `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`. Never commit `.env`.
5. **Caching/state** — set `REDIS_URL` for a shared cache and a cross-instance
   rate limiter (the in-process limiter is per-process).
6. **Scheduling** — point an external scheduler (or the planned worker) at the
   pipeline endpoints with the cron secret, on the ET schedule in the runbook.

## CI gates (recommended)

`ruff check .` · `mypy` · `pytest -q` · `alembic upgrade head` (+ `downgrade base`)
· `npm run lint|typecheck|build` · `pip-audit` · `npm audit`.

## Notes

- `docker-compose.yml`/Dockerfiles are **[Planned]** (sibling repos ship them as
  drafts; treat as review-only until validated on a Docker host).
- Health checks for orchestration: `GET /health` (liveness),
  `GET /health/providers` (readiness signal — does not fail closed on a degraded
  optional provider).
