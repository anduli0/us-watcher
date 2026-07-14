"""Sub-industry cycle calibration — is the sub-industry CYCLE state predictive of
forward EXCESS return?

Measures, point-in-time and keyless, whether a classified name whose sub-industry
group is rolling over (mean 63-session relative strength of its peers vs SPY < 0)
goes on to UNDER-perform the market over the next 60/120 sessions, versus names
whose group cycle is positive. If the gap is real and material, it justifies an
evidence-sized medium-long cycle handling (the same way the RISK_OFF_* constants in
``recommendation/config.py`` were derived from ``signal_lab.run_diagnosis``); if it
is small, the honest conclusion is that the existing sector-leadership blend already
suffices and no extra knob is warranted.

No look-ahead: the cycle state at entry date d uses only data up to d; the forward
excess uses SPY date-aligned closes. Research CLI — NOT imported at runtime.

Run (venv, cwd=us-watcher):  python -m us_watcher.accuracy.cycle_calibration
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from us_watcher.domain.analytics.series import Bar

if TYPE_CHECKING:
    from datetime import date

    from us_watcher.infrastructure.marketdata.base import AggregateSeries

RS_WINDOW = 63          # ≈3-month cycle read (matches the production blend)
HORIZONS = (60, 120)    # medium / medium-long evaluation windows
REBALANCE = 10
MIN_PEERS = 2           # a group cycle read needs at least this many peers that day
COST = 0.002            # 10bps x2, same as signal_lab


def _rs63_by_date(closes: list[float], dates: list, bench_by_date: dict) -> dict:
    """{date: relative-strength-over-RS_WINDOW vs SPY} for one symbol, point-in-time."""
    out: dict = {}
    for i in range(RS_WINDOW, len(closes)):
        c0, c1 = closes[i - RS_WINDOW], closes[i]
        if c0 <= 0:
            continue
        d0, d1 = dates[i - RS_WINDOW], dates[i]
        b0, b1 = bench_by_date.get(d0), bench_by_date.get(d1)
        if not (b0 and b1 and b0 > 0):
            continue
        out[d1] = (c1 / c0 - 1.0) - (b1 / b0 - 1.0)
    return out


class _Bucket:
    __slots__ = ("n", "sum_exc", "wins")

    def __init__(self) -> None:
        self.n = 0
        self.wins = 0
        self.sum_exc = 0.0

    def add(self, exc: float) -> None:
        self.n += 1
        self.wins += 1 if exc > 0 else 0
        self.sum_exc += exc

    def hit(self) -> float:
        return 100.0 * self.wins / self.n if self.n else 0.0

    def avg_exc(self) -> float:
        return 100.0 * self.sum_exc / self.n if self.n else 0.0


def run_cycle_diagnosis(
    bars_by_symbol: dict[str, list[Bar]], groups: dict[str, list[str]], benchmark_bars: list[Bar]
) -> dict:
    """Bucket forward excess by cycle-ON (group RS63 ≥ 0) vs cycle-OFF (< 0)."""
    bench_by_date = {b.as_of.date(): b.close for b in benchmark_bars}
    # per-symbol point-in-time series + RS63-by-date
    closes_by = {s: [b.close for b in bars] for s, bars in bars_by_symbol.items()}
    dates_by = {s: [b.as_of.date() for b in bars] for s, bars in bars_by_symbol.items()}
    rs_by = {s: _rs63_by_date(closes_by[s], dates_by[s], bench_by_date) for s in bars_by_symbol}

    sym_group = {sym: g for g, syms in groups.items() for sym in syms}

    def group_cycle(group: str, d: date) -> float | None:
        vals = [rs_by[p][d] for p in groups[group] if p in rs_by and d in rs_by[p]]
        return sum(vals) / len(vals) if len(vals) >= MIN_PEERS else None

    out: dict = {h: {"on": _Bucket(), "off": _Bucket()} for h in HORIZONS}
    per_group: dict = {g: {h: {"on": _Bucket(), "off": _Bucket()} for h in HORIZONS} for g in groups}

    for sym in bars_by_symbol:
        group = sym_group.get(sym)
        if group is None:
            continue
        closes, dates = closes_by[sym], dates_by[sym]
        for t in range(RS_WINDOW, len(closes), REBALANCE):
            cyc = group_cycle(group, dates[t])
            if cyc is None:
                continue
            side = "on" if cyc >= 0.0 else "off"
            for h in HORIZONS:
                if t + h >= len(closes) or closes[t] <= 0:
                    continue
                b0, b1 = bench_by_date.get(dates[t]), bench_by_date.get(dates[t + h])
                if not (b0 and b1 and b0 > 0):
                    continue
                fwd = closes[t + h] / closes[t] - 1.0 - COST
                exc = fwd - (b1 / b0 - 1.0)
                out[h][side].add(exc)
                per_group[group][h][side].add(exc)
    return {"overall": out, "per_group": per_group}


async def main() -> None:  # pragma: no cover — research CLI
    from us_watcher.domain.universe import Instrument, get_universe
    from us_watcher.market.service import get_market_service

    svc = get_market_service()
    u = get_universe()
    groups = u.sub_industry_members()
    syms = sorted({s for members in groups.values() for s in members})
    spy = u.by_symbol("SPY")
    provider = svc._provider
    sem = asyncio.Semaphore(6)

    async def fetch(inst: Instrument) -> tuple[str, AggregateSeries | None]:
        async with sem:
            ysym = inst.yahoo_symbol or inst.symbol
            return inst.symbol, await provider.get_aggregates(ysym, range_="5y")

    to_fetch = [i for i in u.stocks if i.symbol in syms] + ([spy] if spy else [])
    fetched = await asyncio.gather(*(fetch(i) for i in to_fetch))
    agg = {sym: s for sym, s in fetched if s is not None and s.bars}
    spy_series = agg.get("SPY")
    if spy_series is None:
        print("SPY unavailable — aborting")
        return
    bars_by = {s: agg[s].bars for s in syms if s in agg}
    print(f"symbols={len(bars_by)} groups={ {g: len(v) for g, v in groups.items()} }")

    res = run_cycle_diagnosis(bars_by, groups, spy_series.bars)
    print("\n=== OVERALL (all classified semis) ===")
    print(f"{'H':>4} | {'cycle-ON  hit  exc%     n':<28} | {'cycle-OFF hit  exc%     n':<28} | gap(on-off) exc%")
    for h, sides in res["overall"].items():
        on, off = sides["on"], sides["off"]
        gap = on.avg_exc() - off.avg_exc()
        print(f"{h:>4} | ON  {on.hit():5.1f} {on.avg_exc():+6.2f} {on.n:6d}    "
              f"| OFF {off.hit():5.1f} {off.avg_exc():+6.2f} {off.n:6d}    | {gap:+6.2f}")
    print("\n=== PER GROUP ===")
    for g, hs in res["per_group"].items():
        for h, sides in hs.items():
            on, off = sides["on"], sides["off"]
            if on.n + off.n == 0:
                continue
            print(f"{g:<14} H{h:<4} ON {on.hit():5.1f}/{on.avg_exc():+6.2f}%/n{on.n:<5} "
                  f"OFF {off.hit():5.1f}/{off.avg_exc():+6.2f}%/n{off.n:<5} gap {on.avg_exc()-off.avg_exc():+6.2f}")


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(main())
