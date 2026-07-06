# Threat Model

Scope: a read-mostly analytics service with optional LLM calls, public read APIs,
and protected operational endpoints. No order execution, no money movement.

| Threat | Vector | Mitigation |
|---|---|---|
| Prompt injection | Malicious text in a news title/article reaching an LLM | `security/sanitize.py` detection + `wrap_untrusted` (data, not instructions); deterministic numbers regardless of LLM; injection logged to `data_quality_events`. |
| SSRF | Article/URL triggers internal fetch | `security/ssrf.py` blocks private/loopback/link-local/metadata; non-http(s) schemes rejected. |
| XXE | Malicious RSS XML | `defusedxml`. |
| Secret leakage | Logs / responses | `SecretStr`; never logged or serialized; `.env` git-ignored. |
| Unauthorized pipeline trigger | Hitting `/orchestrator/run`, `/pipelines/*` | Admin key / cron secret; deny-by-default when unset; audit log. |
| DoS / cost blow-up | Flooding endpoints or LLM | Rate limiter; per-run token budget; dynamic agent activation; TTL caches; LLM degrades to mock on error. |
| Data poisoning | Provider returns garbage | Pydantic validation; never-raise providers; explicit UNAVAILABLE/STALE; mock fallback labelled. |
| Look-ahead / survivorship bias | Backtests | Point-in-time fields; immutable recommendation history; failed recs retained. |
| Fabricated data presented as live | Mock leaking into UI as real | Every item carries `DataStatus`; MOCK/PROXY always labelled; rollup `data_quality`. |
| XSS | Stored article HTML rendered | `strip_html` at ingest; React escaping; CSP. |
| Supply chain | Malicious dependency | `pip-audit`/`npm audit` in CI; pinned ranges. |

## Trust boundaries

Untrusted: all provider responses, news content, any external URL. Trusted:
in-repo deterministic code and config. The LLM is treated as an *untrusted
transformer* — its output is schema-validated and never grants authority.
