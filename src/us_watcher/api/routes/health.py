"""Health endpoints. Never expose secrets (spec §47)."""

from __future__ import annotations

from fastapi import APIRouter

from us_watcher.config import get_settings
from us_watcher.domain.time import now_utc, session_status
from us_watcher.infrastructure.db import check_database
from us_watcher.infrastructure.redis_client import redis_status

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        "time_utc": now_utc().isoformat(),
        "session": session_status(),
        "market_data_provider": settings.market_data_provider,
        "news_provider": settings.news_provider,
        "agent_runtime": settings.agent_runtime,
        "llm_enabled": settings.llm_enabled,
    }


@router.get("/health/providers")
async def providers_health() -> dict:
    settings = get_settings()
    redis = await redis_status()
    return {
        "database": "ok" if await check_database() else "down",
        "redis": redis.model_dump(),
        "market_data": settings.market_data_provider,
        "macro": "fred-keyless" if not settings.fred_keyed else "fred-keyed",
        "news": settings.news_provider,
        "llm": "configured" if settings.llm_enabled else "mock",
    }


@router.get("/health/pipelines")
async def pipelines_health() -> dict:
    return {"status": "ok", "note": "Pipeline run history at /api/v1/agents/runs."}
