"""Seed the ``instruments`` table from the universe config (idempotent)."""

from __future__ import annotations

from us_watcher.db.models import Instrument
from us_watcher.domain.universe import get_universe
from us_watcher.infrastructure.db import get_sessionmaker


async def seed_instruments() -> int:
    universe = get_universe()
    sm = get_sessionmaker()
    added = 0
    async with sm() as session:
        for inst in universe.all_instruments():
            existing = await session.get(Instrument, inst.symbol)
            if existing is not None:
                continue
            session.add(
                Instrument(
                    symbol=inst.symbol,
                    name=inst.name,
                    group=inst.group,
                    asset_type=inst.asset_type,
                    market=inst.market,
                    gics=inst.gics,
                    yahoo_symbol=inst.yahoo_symbol,
                    is_proxy=inst.is_proxy,
                )
            )
            added += 1
        await session.commit()
    return added
