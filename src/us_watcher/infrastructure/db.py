"""Async SQLAlchemy engine/session factory.

A single ``DATABASE_URL`` selects SQLite (aiosqlite, local/CI) or Postgres
(asyncpg, prod). The ORM ``Base`` lives here so models and Alembic share it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from us_watcher.config import get_settings


class Base(DeclarativeBase):
    """Declarative base shared by all ORM models and Alembic migrations."""


@lru_cache
def get_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(settings.database_url, future=True, pool_pre_ping=True)


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncIterator[AsyncSession]:
    sm = get_sessionmaker()
    async with sm() as session:
        yield session


async def check_database() -> bool:
    """Lightweight connectivity check for /health. Never raises."""
    from sqlalchemy import text

    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def create_all() -> None:
    """Create tables from ORM metadata (dev convenience; prod uses Alembic)."""
    from us_watcher.db import models  # noqa: F401 - ensure models are registered

    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
