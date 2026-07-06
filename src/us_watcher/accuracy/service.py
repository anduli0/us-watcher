"""Accuracy summary service (spec §32).

Combines (1) live recommendation-outcome metrics — empty/pending until horizons
mature — and (2) a reproducible point-in-time backtest of the deterministic
signal, which has real numbers immediately. Failed recommendations are always
included (never dropped) so the hit rate is not survivorship-inflated.
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import select

from us_watcher.accuracy.backtest import run_backtest
from us_watcher.db.models import RecommendationOutcome
from us_watcher.infrastructure.db import get_sessionmaker
from us_watcher.market.service import get_market_service

_BT_CACHE: dict[str, Any] = {"ts": 0.0, "data": None}


async def backtest_summary() -> dict:
    """Run (or return cached, 10-min TTL) the point-in-time signal backtest."""
    now = time.monotonic()
    cached = _BT_CACHE["data"]
    if isinstance(cached, dict) and now - _BT_CACHE["ts"] < 600:
        return cached
    svc = get_market_service()
    u = svc._universe
    spy = u.by_symbol("SPY")
    universe = [*u.stocks, *u.sectors]
    fetch = [*universe] + ([spy] if spy else [])
    agg = await svc._fetch_many(fetch)
    spy_series = agg.get("SPY")
    if spy_series is None or not spy_series.bars:
        return {"available": False, "note": "Benchmark (SPY) unavailable; backtest skipped."}
    bars_by = {}
    for i in universe:
        srow = agg.get(i.symbol)
        if srow is not None:
            bars_by[i.symbol] = srow.bars
    data = run_backtest(bars_by, spy_series.bars)
    data["available"] = True
    data["universe_size"] = len(bars_by)
    _BT_CACHE["ts"] = now
    _BT_CACHE["data"] = data
    return data


async def accuracy_summary() -> dict:
    sm = get_sessionmaker()
    async with sm() as s:
        rows = (await s.execute(select(RecommendationOutcome))).scalars().all()

    evaluated = [r for r in rows if r.status == "evaluated" and r.abs_return_pct is not None]
    by_horizon: dict[int, dict] = {}
    for hd in sorted({r.horizon_days for r in evaluated}):
        bucket = [r for r in evaluated if r.horizon_days == hd]
        returns = [r.abs_return_pct for r in bucket if r.abs_return_pct is not None]
        excess = [r.excess_return_pct for r in bucket if r.excess_return_pct is not None]
        wins = [x for x in returns if x > 0]
        losses = [x for x in returns if x <= 0]
        by_horizon[hd] = {
            "n": len(bucket),
            "hit_rate": round(len(wins) / len(returns), 3) if returns else None,
            "avg_return_pct": round(sum(returns) / len(returns), 2) if returns else None,
            "avg_excess_pct": round(sum(excess) / len(excess), 2) if excess else None,
            "avg_gain_pct": round(sum(wins) / len(wins), 2) if wins else None,
            "avg_loss_pct": round(sum(losses) / len(losses), 2) if losses else None,
        }

    live_note = None if evaluated else (
        "No live outcomes matured yet. Recommendations are tracked at 1/5/20/60/120/252 "
        "trading days; metrics appear here as horizons mature. The backtest below validates "
        "the signal methodology on history now."
    )
    from us_watcher.accuracy.calibration import calibration_summary, live_hit_rates

    return {
        "live_outcomes": {
            "evaluated_count": len(evaluated),
            "pending_count": len([r for r in rows if r.status == "pending"]),
            "by_horizon": by_horizon,
            "note": live_note,
        },
        "confidence_calibration": calibration_summary(await live_hit_rates()),
        "backtest": await backtest_summary(),
        # backwards-compatible top-level fields (older UI)
        "evaluated_count": len(evaluated),
        "pending_count": len([r for r in rows if r.status == "pending"]),
        "by_horizon": by_horizon,
        "note": live_note,
    }
