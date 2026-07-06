"""Recommendation outcome tracking (spec §32.1, §32.5).

For each live recommendation, once a standard horizon (1/5/20/60/120/252 trading
days) has elapsed since ``as_of``, score the realized return vs a
context-appropriate benchmark and append a ``recommendation_outcomes`` row.
Outcomes are never overwritten; failed recommendations are kept. Newly-created
recs simply have nothing matured yet (reported as pending) — honest, not zero-filled.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select

from us_watcher.db.models import Recommendation, RecommendationOutcome
from us_watcher.db.repositories import add_audit_event
from us_watcher.domain.analytics.series import Bar
from us_watcher.domain.time import now_utc
from us_watcher.infrastructure.db import get_sessionmaker
from us_watcher.market.service import get_market_service

EVAL_HORIZONS = [1, 5, 20, 60, 120, 252]


def _close_on_or_after(bars: list[Bar], target_date: date) -> tuple[int, float] | None:
    for i, b in enumerate(bars):
        if b.as_of.date() >= target_date:
            return i, b.close
    return None


async def evaluate_recommendations() -> dict:
    svc = get_market_service()
    u = svc._universe
    sm = get_sessionmaker()

    # latest revision per lineage
    async with sm() as s:
        rows = (await s.execute(select(Recommendation))).scalars().all()
        done = {
            (o.recommendation_id, o.horizon_days)
            for o in (await s.execute(select(RecommendationOutcome))).scalars().all()
        }
    latest: dict[str, Recommendation] = {}
    for r in rows:
        cur = latest.get(r.lineage_id)
        if cur is None or r.revision > cur.revision:
            latest[r.lineage_id] = r

    evaluated = 0
    pending = 0
    inst_by_ticker = {i.symbol: i for i in u.all_instruments()}
    # benchmark bars (SPY/QQQ) cached
    bench_bars: dict[str, list[Bar]] = {}
    for bsym in ("SPY", "QQQ"):
        inst = u.by_symbol(bsym)
        series = await svc._aggregates(inst) if inst else None
        bench_bars[bsym] = series.bars if series else []

    new_rows: list[RecommendationOutcome] = []
    for r in latest.values():
        inst = inst_by_ticker.get(r.ticker)
        if inst is None:
            continue
        series = await svc._aggregates(inst)
        if series is None or not series.bars:
            continue
        bars = series.bars
        entry = _close_on_or_after(bars, r.as_of.date())
        if entry is None:
            continue
        entry_idx, entry_px = entry
        bench_sym = str((inst.extra or {}).get("benchmark", "SPY")) if inst.group == "stock" else "SPY"
        bbars = bench_bars.get(bench_sym) or bench_bars.get("SPY") or []
        bench_entry = _close_on_or_after(bbars, r.as_of.date())
        for h in EVAL_HORIZONS:
            if (r.id, h) in done:
                continue
            exit_idx = entry_idx + h
            if exit_idx >= len(bars):
                pending += 1
                continue
            exit_px = bars[exit_idx].close
            abs_ret = (exit_px / entry_px - 1.0) * 100.0 if entry_px else None
            excess = None
            if bench_entry is not None:
                b_idx, b_entry_px = bench_entry
                if b_idx + h < len(bbars) and b_entry_px:
                    bench_ret = (bbars[b_idx + h].close / b_entry_px - 1.0) * 100.0
                    excess = abs_ret - bench_ret if abs_ret is not None else None
            new_rows.append(RecommendationOutcome(
                recommendation_id=r.id, lineage_id=r.lineage_id, horizon_days=h,
                abs_return_pct=round(abs_ret, 2) if abs_ret is not None else None,
                benchmark=bench_sym,
                excess_return_pct=round(excess, 2) if excess is not None else None,
                evaluated_at=now_utc(), status="evaluated"))
            evaluated += 1

    if new_rows:
        async with sm() as s:
            for row in new_rows:
                s.add(row)
            await s.commit()
    await add_audit_event("recommendations.evaluated",
                          f"Evaluated {evaluated} outcomes ({pending} pending maturity)",
                          payload={"evaluated": evaluated, "pending": pending})
    return {"evaluated": evaluated, "pending": pending, "lineages": len(latest),
            "as_of": now_utc().isoformat()}
