"""Alembic environment (async-aware).

The DB URL comes from the app Settings (DATABASE_URL), so migrations target the
same SQLite/Postgres backend as the app. Models import registers all tables on
``Base.metadata`` for autogenerate.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from us_watcher.config import get_settings
from us_watcher.db import models  # noqa: F401 - register tables on Base.metadata
from us_watcher.infrastructure.db import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _url() -> str:
    return get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_url(), target_metadata=target_metadata, literal_binds=True,
        dialect_opts={"paramstyle": "named"}, render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_url(), future=True)
    async with engine.connect() as connection:
        await connection.run_sync(_do_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
