"""Shared API dependencies: DB session, admin/cron auth, basic rate limiting.

Protected operational endpoints (POST /pipelines/*, /admin/*) require either the
admin API key or the cron secret. When neither secret is configured, protected
endpoints are refused (deny-by-default) rather than left open.
"""

from __future__ import annotations

import time
from collections import defaultdict

from fastapi import Header, HTTPException, Request, status

from us_watcher.config import get_settings


async def require_operator(
    x_admin_key: str | None = Header(default=None),
    x_cron_secret: str | None = Header(default=None),
) -> str:
    """Authorise an operator request. Returns the principal label or 403/503."""
    settings = get_settings()
    admin = settings.admin_api_key.get_secret_value()
    cron = settings.cron_secret.get_secret_value()
    if not admin and not cron:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Operational endpoints are disabled: set ADMIN_API_KEY or CRON_SECRET.",
        )
    if admin and x_admin_key == admin:
        return "admin"
    if cron and x_cron_secret == cron:
        return "cron"
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid or missing operator credential.")


_BUCKET: dict[str, list[float]] = defaultdict(list)


async def rate_limit(request: Request) -> None:
    """Coarse in-process fixed-window limiter (per client host)."""
    settings = get_settings()
    limit = settings.rate_limit_per_minute
    now = time.monotonic()
    key = request.client.host if request.client else "unknown"
    window = [t for t in _BUCKET[key] if now - t < 60.0]
    if len(window) >= limit:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Rate limit exceeded.")
    window.append(now)
    _BUCKET[key] = window
