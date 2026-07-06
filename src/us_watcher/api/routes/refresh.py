"""Public refresh trigger — the website's "update now" button (mobile included).

``POST /refresh`` kicks a full analysis cycle (orchestrator house view +
recommendations) as a background task and returns immediately; the browser
polls ``GET /refresh/status`` until it finishes. Deliberately public — a phone
browser cannot hold operator secrets — but bounded:

* zero request input ever reaches a prompt (fixed objective/trigger),
* a server-side cooldown (``REFRESH_COOLDOWN_MINUTES``) caps LLM spend,
* at most one run is in flight (in-process lock),
* the shared per-host rate limiter still applies.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi import APIRouter, Depends

from us_watcher.api.deps import rate_limit
from us_watcher.config import get_settings
from us_watcher.domain.time import now_utc
from us_watcher.logging_config import get_logger

log = get_logger(__name__)

router = APIRouter(tags=["refresh"], dependencies=[Depends(rate_limit)])

_state: dict[str, Any] = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "ok": None,
    "detail": "",
    "last_success_at": None,
}
_last_start_mono: float | None = None
_lock = asyncio.Lock()


def _cooldown_remaining() -> int:
    if _last_start_mono is None:
        return 0
    budget = get_settings().refresh_cooldown_minutes * 60
    return max(0, int(budget - (time.monotonic() - _last_start_mono)))


def _public_state() -> dict[str, Any]:
    settings = get_settings()
    return {
        **_state,
        "cooldown_remaining_seconds": 0 if _state["running"] else _cooldown_remaining(),
        "llm": settings.llm_provider_resolved if settings.llm_enabled else "mock",
    }


async def _do_refresh() -> None:
    from us_watcher.agent_service.orchestrator import run_orchestrator
    from us_watcher.agent_service.recommendation_pipeline import generate_recommendations

    try:
        run = await run_orchestrator(objective="market_overview", trigger="manual")
        recs = await generate_recommendations()
        chief = (run or {}).get("chief") or {}
        _state.update(
            ok=True,
            detail=f"model={chief.get('model')} mock={chief.get('is_mock')} "
                   f"recs={(recs or {}).get('generated')}",
            last_success_at=now_utc().isoformat(),
        )
        log.info("refresh.done", model=chief.get("model"), is_mock=chief.get("is_mock"))
    except Exception as exc:  # surfaced via status; never crashes the API
        _state.update(ok=False, detail=str(exc)[:200])
        log.error("refresh.failed", error=str(exc)[:300])
    finally:
        _state.update(running=False, finished_at=now_utc().isoformat())


@router.post("/refresh")
async def trigger_refresh() -> dict[str, Any]:
    global _last_start_mono
    async with _lock:
        if _state["running"]:
            return {"status": "running", **_public_state()}
        remaining = _cooldown_remaining()
        if remaining > 0:
            return {"status": "cooldown", "retry_after_seconds": remaining, **_public_state()}
        _last_start_mono = time.monotonic()
        _state.update(
            running=True, started_at=now_utc().isoformat(),
            finished_at=None, ok=None, detail="",
        )
        task = asyncio.create_task(_do_refresh())
        task.add_done_callback(lambda t: t.exception())  # retrieve to avoid warnings
    return {"status": "started", **_public_state()}


@router.get("/refresh/status")
async def refresh_status() -> dict[str, Any]:
    return _public_state()
