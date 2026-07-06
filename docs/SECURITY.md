# Security

## Implemented

- **Secrets server-only** — all keys are Pydantic `SecretStr`; never logged or
  returned in any response. `.env` is git-ignored; `.env.example` has no values.
- **Operational endpoints deny-by-default** — `POST /api/v1/orchestrator/run` and
  `/api/v1/pipelines/*` require `x-admin-key` (== `ADMIN_API_KEY`) or
  `x-cron-secret` (== `CRON_SECRET`). If neither is configured, they return 503
  (disabled), not open. Read endpoints are public.
- **Rate limiting** — coarse in-process per-client fixed-window limiter
  (`rate_limit_per_minute`). Replace with a shared store (Redis) for multi-instance.
- **Secure headers + CSP** — `X-Content-Type-Options`, `X-Frame-Options: DENY`,
  `Referrer-Policy`, `Permissions-Policy`, `Content-Security-Policy: default-src
  'self'; frame-ancestors 'none'` via middleware.
- **CORS** — explicit allow-list (local dev fronts); credentials disabled; methods
  restricted to GET/POST.
- **Prompt-injection defense** (`security/sanitize.py`) — strip HTML, cap length,
  detect injection patterns ("ignore previous instructions", "system prompt",
  secret-exfiltration, role tags); flagged items are logged to
  `data_quality_events`, kept as data, and wrapped via `wrap_untrusted` before any
  LLM prompt. External text can never become an instruction.
- **SSRF protection** (`security/ssrf.py`) — `is_safe_url` blocks non-http(s)
  schemes, private/loopback/link-local/reserved/multicast IPs, `localhost`, and
  the cloud metadata endpoint (169.254.169.254). Use before any external fetch.
- **XML safety** — news RSS parsed with `defusedxml` (XXE-safe).
- **Input validation** — Pydantic v2 `extra="forbid"` on domain/IO models;
  FastAPI validates query/body.
- **SQL injection** — SQLAlchemy parameterized queries only; no string SQL.
- **Money precision** — `Decimal` everywhere for price/money; raw `float` rejected.
- **Audit log** — append-only `audit_events`; no update/delete path in app code.

## Operational guidance

- Set strong random `CRON_SECRET`/`ADMIN_API_KEY` in production.
- Put the API behind TLS (reverse proxy / Tailscale Funnel, as with sibling apps).
- `pip-audit` / `npm audit` in CI for dependency & supply-chain review.

## Never exposed

API keys, internal system prompts, full agent configuration, DB credentials,
internal network details, raw provider secrets, or private chain-of-thought.
