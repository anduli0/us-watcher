"""Redis client with an in-memory fakeredis fallback.

If ``REDIS_URL`` is unset we fall back to fakeredis and report that honestly at
``/health`` (never pretend a cache backend exists when it does not).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from us_watcher.config import get_settings


class RedisStatus(BaseModel):
    backend: str
    connected: bool
    detail: str = ""


_client: Any | None = None


async def get_redis_client() -> Any:
    global _client
    if _client is not None:
        return _client
    settings = get_settings()
    if settings.redis_url:
        import redis.asyncio as redis  # lazy import

        _client = redis.from_url(settings.redis_url, decode_responses=True)
    else:
        import fakeredis.aioredis as fakeredis  # lazy import

        _client = fakeredis.FakeRedis(decode_responses=True)
    return _client


async def redis_status() -> RedisStatus:
    settings = get_settings()
    backend = "redis" if settings.redis_url else "fakeredis"
    try:
        client = await get_redis_client()
        await client.ping()
        return RedisStatus(backend=backend, connected=True)
    except Exception as exc:
        return RedisStatus(backend=backend, connected=False, detail=str(exc)[:200])
