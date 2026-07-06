"""Keyless FRED macro provider (Treasury yields, spreads, macro series).

Uses the public ``fredgraph.csv`` download endpoint, which is keyless. NEVER
raises — returns ``None`` on any failure. Each observation preserves
point-in-time fields (``observation_date``, ``available_at``) so backtests can
honour what was actually known at a historical decision time (spec §3.2). The
keyless CSV serves only the *latest revised* values; vintage/ALFRED support
drops in behind this interface once an API key is configured.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime

import httpx
from pydantic import BaseModel, ConfigDict

from us_watcher.domain.enums import DataStatus
from us_watcher.domain.time import now_utc
from us_watcher.infrastructure.http import new_async_client

_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"


class MacroObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    series_id: str
    observation_date: date
    value: float
    available_at: datetime
    source: str = "fred"
    status: DataStatus = DataStatus.END_OF_DAY


class FredProvider:
    name = "fred"

    def __init__(self, *, timeout: float = 6.0) -> None:
        self._timeout = timeout

    async def get_latest(self, series_id: str) -> MacroObservation | None:
        try:
            async with new_async_client(timeout=self._timeout) as c:
                resp = await c.get(_CSV_URL, params={"id": series_id})
                if resp.status_code != 200:
                    return None
                text = resp.text
        except httpx.HTTPError:
            return None
        latest: tuple[date, float] | None = None
        for line in text.splitlines()[1:]:  # skip header
            parts = line.split(",")
            if len(parts) < 2:
                continue
            raw_date, raw_val = parts[0].strip(), parts[1].strip()
            if not raw_val or raw_val == ".":
                continue
            try:
                d = date.fromisoformat(raw_date)
                v = float(raw_val)
            except ValueError:
                continue
            if latest is None or d > latest[0]:
                latest = (d, v)
        if latest is None:
            return None
        return MacroObservation(
            series_id=series_id,
            observation_date=latest[0],
            value=latest[1],
            available_at=now_utc(),
        )

    async def get_many(self, series_ids: list[str]) -> dict[str, MacroObservation]:
        # Fetch all series concurrently: a sequential loop stacked each series'
        # timeout (e.g. 6 series × 8s ≈ 48s worst case) and was the root cause of
        # the overview/macro endpoints hanging. With gather, the whole batch is
        # bounded by the slowest single request, not their sum.
        results = await asyncio.gather(*(self.get_latest(sid) for sid in series_ids))
        return {sid: obs for sid, obs in zip(series_ids, results, strict=True) if obs is not None}


def _utcnow() -> datetime:  # pragma: no cover - tiny shim kept for clarity
    return datetime.now(tz=UTC)
