"""Signal research lab — offline, embargoed train/test comparison of candidate
technical-signal variants (spec §32 methodology-improvement loop).

Purpose: find variants of the deterministic technical signal that IMPROVE
forward-return skill, without look-ahead and without in-sample self-deception:

* Signals at t use only ``closes[:t+1]`` (point-in-time).
* The calendar is split train/test with an EMBARGO: a train sample's exit
  (t+h) must fall before the cutoff; a test sample's entry (t) must fall after
  it. Variants are picked on train and must CONFIRM on test.

Run (venv, cwd=us-watcher):  python -m us_watcher.accuracy.signal_lab
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from us_watcher.domain.analytics.indicators import (
    ma_slope,
    realized_volatility,
    rsi,
    simple_return,
    sma,
)
from us_watcher.domain.analytics.series import Bar

WARMUP = 260  # 200-DMA + slope lookback + 52w window headroom
HORIZONS = (20, 60, 120)
LONG_THRESHOLD = 55.0
REBALANCE = 10
TRAIN_FRACTION = 0.6


def _clamp(x: float) -> float:
    return max(0.0, min(100.0, x))


@dataclass
class Primitives:
    """Point-in-time inputs shared by every variant (computed once per (symbol, t))."""

    last: float
    above200: bool | None
    above50: bool | None
    slope200: float | None
    r20: float | None
    r60: float | None
    r120: float | None
    rsi14: float | None
    ext100: float | None  # last/sma100 - 1 (extension above the 100-DMA)
    dist252: float | None  # last/max(52w) - 1 (<= 0)
    vol20: float | None  # annualised


def compute_primitives(closes: list[float], t: int) -> Primitives | None:
    window = closes[: t + 1]
    if len(window) < WARMUP or window[-1] <= 0:
        return None
    last = window[-1]
    m200, m100, m50 = sma(window, 200), sma(window, 100), sma(window, 50)
    hi52 = max(window[-252:])
    return Primitives(
        last=last,
        above200=(last > m200) if m200 is not None else None,
        above50=(last > m50) if m50 is not None else None,
        slope200=ma_slope(window, 200, lookback=20),
        r20=simple_return(window, 20),
        r60=simple_return(window, 60),
        r120=simple_return(window, 120),
        rsi14=rsi(window, 14),
        ext100=(last / m100 - 1.0) if m100 else None,
        dist252=(last / hi52 - 1.0) if hi52 > 0 else None,
        vol20=realized_volatility(window, 20),
    )


# ---- signal parts (each returns a 0-100 part or None) ----

def _part_ma200_binary(p: Primitives) -> float | None:
    if p.above200 is None:
        return None
    return 70.0 if p.above200 else 30.0


def _part_ma200_slope(p: Primitives) -> float | None:
    """Trend-quality upgrade: a rising 200-DMA distinguishes a healthy uptrend
    from a stale one; a falling 200-DMA under price flags dead-cat bounces."""
    if p.above200 is None:
        return None
    if p.slope200 is None:
        return 70.0 if p.above200 else 30.0
    rising = p.slope200 > 0
    if p.above200:
        return 74.0 if rising else 56.0
    return 44.0 if rising else 26.0


def _part_ma50(p: Primitives) -> float | None:
    if p.above50 is None:
        return None
    return 62.0 if p.above50 else 38.0


def _part_r20(p: Primitives) -> float | None:
    return _clamp(50.0 + p.r20 * 400.0) if p.r20 is not None else None


def _part_r60(p: Primitives) -> float | None:
    return _clamp(50.0 + p.r60 * 180.0) if p.r60 is not None else None


def _part_rsi(p: Primitives) -> float | None:
    if p.rsi14 is None:
        return None
    r = p.rsi14
    if r > 80:
        return 40.0
    if r < 25:
        return 30.0
    return _clamp(50.0 + (r - 50.0) * 0.8)


def _part_momentum_consistency(p: Primitives) -> float | None:
    """Multi-horizon momentum agreement (r20/r60/r120 signs)."""
    rs = [r for r in (p.r20, p.r60, p.r120) if r is not None]
    if len(rs) < 2:
        return None
    pos = sum(1 for r in rs if r > 0)
    frac = pos / len(rs)
    if frac >= 0.99:
        return 72.0
    if frac >= 0.66:
        return 58.0
    if frac >= 0.33:
        return 42.0
    return 28.0


def _part_52w_proximity(p: Primitives) -> float | None:
    if p.dist252 is None:
        return None
    return _clamp(72.0 + p.dist252 * 140.0)


def _overheat_penalty(p: Primitives) -> float:
    """Points subtracted when price is stretched far above its 100-DMA
    (mean-reversion guard; the kospi-watcher analogue used the 120-DMA)."""
    if p.ext100 is None or p.ext100 <= 0.15:
        return 0.0
    return min(18.0, (p.ext100 - 0.15) * 90.0)


def _vol_dampen(score: float, p: Primitives) -> float:
    """Shrink conviction toward 50 when realized vol is extreme."""
    if p.vol20 is None or p.vol20 <= 0.35:
        return score
    k = max(0.6, 1.0 - (p.vol20 - 0.35) * 1.2)
    return 50.0 + (score - 50.0) * k


def _avg(parts: list[float | None]) -> float | None:
    vals = [v for v in parts if v is not None]
    return sum(vals) / len(vals) if vals else None


# ---- variants ----

def v0_baseline(p: Primitives) -> float | None:
    return _avg([_part_ma200_binary(p), _part_ma50(p), _part_r20(p), _part_r60(p), _part_rsi(p)])


def v1_overheat(p: Primitives) -> float | None:
    s = v0_baseline(p)
    return None if s is None else _clamp(s - _overheat_penalty(p))


def v2_slope(p: Primitives) -> float | None:
    return _avg([_part_ma200_slope(p), _part_ma50(p), _part_r20(p), _part_r60(p), _part_rsi(p)])


def v3_consistency(p: Primitives) -> float | None:
    return _avg([_part_ma200_binary(p), _part_ma50(p), _part_r20(p), _part_r60(p), _part_rsi(p),
                 _part_momentum_consistency(p)])


def v4_52w(p: Primitives) -> float | None:
    return _avg([_part_ma200_binary(p), _part_ma50(p), _part_r20(p), _part_r60(p), _part_rsi(p),
                 _part_52w_proximity(p)])


def v5_voldamp(p: Primitives) -> float | None:
    s = v0_baseline(p)
    return None if s is None else _vol_dampen(s, p)


def c1_slope_consistency(p: Primitives) -> float | None:
    return _avg([_part_ma200_slope(p), _part_ma50(p), _part_r20(p), _part_r60(p), _part_rsi(p),
                 _part_momentum_consistency(p)])


def c2_slope_consistency_overheat(p: Primitives) -> float | None:
    s = c1_slope_consistency(p)
    return None if s is None else _clamp(s - _overheat_penalty(p))


def c3_slope_consistency_52w(p: Primitives) -> float | None:
    return _avg([_part_ma200_slope(p), _part_ma50(p), _part_r20(p), _part_r60(p), _part_rsi(p),
                 _part_momentum_consistency(p), _part_52w_proximity(p)])


def c4_full(p: Primitives) -> float | None:
    s = c3_slope_consistency_52w(p)
    if s is None:
        return None
    return _vol_dampen(_clamp(s - _overheat_penalty(p)), p)


VARIANTS: dict[str, Callable[[Primitives], float | None]] = {
    "v0_baseline": v0_baseline,
    "v1_overheat": v1_overheat,
    "v2_slope": v2_slope,
    "v3_consistency": v3_consistency,
    "v4_52w": v4_52w,
    "v5_voldamp": v5_voldamp,
    "c1_slope+cons": c1_slope_consistency,
    "c2_slope+cons+heat": c2_slope_consistency_overheat,
    "c3_slope+cons+52w": c3_slope_consistency_52w,
    "c4_full": c4_full,
}


@dataclass
class _Acc:
    n: int = 0
    long_n: int = 0
    long_wins: int = 0
    long_ret: float = 0.0
    long_excess: float = 0.0
    # for score/forward-return correlation (skill beyond the long threshold)
    sx: float = 0.0
    sy: float = 0.0
    sxx: float = 0.0
    syy: float = 0.0
    sxy: float = 0.0

    def add(self, score: float, fwd: float, excess: float) -> None:
        self.n += 1
        self.sx += score
        self.sy += fwd
        self.sxx += score * score
        self.syy += fwd * fwd
        self.sxy += score * fwd
        if score >= LONG_THRESHOLD:
            self.long_n += 1
            self.long_ret += fwd
            self.long_excess += excess
            if fwd > 0:
                self.long_wins += 1

    def report(self) -> dict:
        ic = None
        if self.n >= 30:
            vx = self.sxx - self.sx * self.sx / self.n
            vy = self.syy - self.sy * self.sy / self.n
            if vx > 0 and vy > 0:
                ic = (self.sxy - self.sx * self.sy / self.n) / (vx * vy) ** 0.5
        ln = self.long_n
        return {
            "n": self.n,
            "long_n": ln,
            "hit": round(self.long_wins / ln, 3) if ln else None,
            "avg_ret_pct": round(self.long_ret / ln * 100, 2) if ln else None,
            "avg_excess_pct": round(self.long_excess / ln * 100, 2) if ln else None,
            "ic": round(ic, 3) if ic is not None else None,
        }


@dataclass
class LabResult:
    cutoff: date
    results: dict = field(default_factory=dict)  # variant -> split -> horizon -> report


def run_lab(bars_by_symbol: dict[str, list[Bar]], benchmark_bars: list[Bar]) -> LabResult:
    bench_by_date = {b.as_of.date(): b.close for b in benchmark_bars}
    all_dates = sorted({b.as_of.date() for bars in bars_by_symbol.values() for b in bars})
    cutoff = all_dates[int(len(all_dates) * TRAIN_FRACTION)]

    acc: dict[str, dict[str, dict[int, _Acc]]] = {
        name: {"train": {h: _Acc() for h in HORIZONS}, "test": {h: _Acc() for h in HORIZONS}}
        for name in VARIANTS
    }

    for _symbol, bars in bars_by_symbol.items():
        if len(bars) < WARMUP + min(HORIZONS):
            continue
        closes = [b.close for b in bars]
        dates = [b.as_of.date() for b in bars]
        for t in range(WARMUP, len(closes), REBALANCE):
            prims = compute_primitives(closes, t)
            if prims is None:
                continue
            scores = {name: fn(prims) for name, fn in VARIANTS.items()}
            for h in HORIZONS:
                if t + h >= len(closes):
                    continue
                # Embargoed split: train exits before cutoff; test enters after it.
                if dates[t + h] <= cutoff:
                    split = "train"
                elif dates[t] > cutoff:
                    split = "test"
                else:
                    continue
                fwd = closes[t + h] / closes[t] - 1.0 - 0.002  # 10bps x2 costs
                b0, b1 = bench_by_date.get(dates[t]), bench_by_date.get(dates[t + h])
                excess = fwd - (b1 / b0 - 1.0) if (b0 and b1 and b0 > 0) else 0.0
                for name, s in scores.items():
                    if s is not None:
                        acc[name][split][h].add(s, fwd, excess)

    out = LabResult(cutoff=cutoff)
    for name, splits in acc.items():
        out.results[name] = {
            split: {str(h): a.report() for h, a in hs.items()} for split, hs in splits.items()
        }
    return out


def run_diagnosis(bars_by_symbol: dict[str, list[Bar]], benchmark_bars: list[Bar]) -> dict:
    """Deep-dive on the BASELINE signal: score-bucket calibration, market-regime
    conditioning (SPY above/below its 200-DMA at entry), and a long-threshold
    sweep. This is the evidence base for confidence calibration and regime
    gating — measured, not assumed."""
    bench_by_date = {b.as_of.date(): b.close for b in benchmark_bars}
    bench_closes = [b.close for b in benchmark_bars]
    bench_dates = [b.as_of.date() for b in benchmark_bars]
    # SPY regime at each date: above/below its 200-DMA (point-in-time).
    spy_regime: dict[date, bool] = {}
    for i in range(200, len(bench_closes)):
        m = sma(bench_closes[: i + 1], 200)
        if m is not None:
            spy_regime[bench_dates[i]] = bench_closes[i] > m

    buckets = [(0, 45), (45, 50), (50, 55), (55, 60), (60, 65), (65, 70), (70, 101)]
    thresholds = (50.0, 55.0, 60.0, 65.0, 70.0)

    def _bucket_name(s: float) -> str:
        for lo, hi in buckets:
            if lo <= s < hi:
                return f"{lo}-{min(hi, 100)}"
        return "0-45"

    stats: dict[str, dict] = {
        str(h): {
            "buckets": {f"{lo}-{min(hi, 100)}": {"n": 0, "wins": 0, "ret": 0.0, "exc": 0.0}
                        for lo, hi in buckets},
            "regime": {"risk_on": {"n": 0, "wins": 0, "exc": 0.0},
                       "risk_off": {"n": 0, "wins": 0, "exc": 0.0}},
            "thresholds": {str(t): {"n": 0, "wins": 0, "exc": 0.0} for t in thresholds},
        }
        for h in HORIZONS
    }

    for _symbol, bars in bars_by_symbol.items():
        if len(bars) < WARMUP + min(HORIZONS):
            continue
        closes = [b.close for b in bars]
        dates = [b.as_of.date() for b in bars]
        for t in range(WARMUP, len(closes), REBALANCE):
            prims = compute_primitives(closes, t)
            if prims is None:
                continue
            score = v0_baseline(prims)
            if score is None:
                continue
            for h in HORIZONS:
                if t + h >= len(closes):
                    continue
                fwd = closes[t + h] / closes[t] - 1.0 - 0.002
                b0, b1 = bench_by_date.get(dates[t]), bench_by_date.get(dates[t + h])
                excess = fwd - (b1 / b0 - 1.0) if (b0 and b1 and b0 > 0) else 0.0
                st = stats[str(h)]
                bk = st["buckets"][_bucket_name(score)]
                bk["n"] += 1
                bk["ret"] += fwd
                bk["exc"] += excess
                if fwd > 0:
                    bk["wins"] += 1
                if score >= LONG_THRESHOLD:
                    risk_on = spy_regime.get(dates[t])
                    if risk_on is not None:
                        rg = st["regime"]["risk_on" if risk_on else "risk_off"]
                        rg["n"] += 1
                        rg["exc"] += excess
                        if fwd > 0:
                            rg["wins"] += 1
                for thr in thresholds:
                    if score >= thr:
                        row = st["thresholds"][str(thr)]
                        row["n"] += 1
                        row["exc"] += excess
                        if fwd > 0:
                            row["wins"] += 1

    def _fin(d: dict, keys: tuple[str, str]) -> dict:
        n = d["n"]
        out = {"n": n, "hit": round(d["wins"] / n, 3) if n else None}
        for src, dst in [(keys[0], keys[1])]:
            out[dst] = round(d[src] / n * 100, 2) if n else None
        return out

    report: dict[str, dict] = {}
    for hname, st in stats.items():
        report[hname] = {
            "buckets": {k: {**_fin(v, ("exc", "avg_excess_pct")),
                            "avg_ret_pct": round(v["ret"] / v["n"] * 100, 2) if v["n"] else None}
                        for k, v in st["buckets"].items()},
            "regime": {k: _fin(v, ("exc", "avg_excess_pct")) for k, v in st["regime"].items()},
            "thresholds": {k: _fin(v, ("exc", "avg_excess_pct")) for k, v in st["thresholds"].items()},
        }
    return report


async def main() -> None:  # pragma: no cover — research CLI
    from us_watcher.domain.universe import Instrument
    from us_watcher.infrastructure.marketdata.base import AggregateSeries
    from us_watcher.market.service import get_market_service

    svc = get_market_service()
    u = svc._universe
    spy = u.by_symbol("SPY")
    universe = [*u.stocks, *u.sectors]
    # 5y history (vs the service's 2y): enough room for an embargoed train/test
    # split past the 260-bar warmup, and it spans the 2022 bear market so the
    # winner is not tuned on a bull-only sample.
    provider = svc._provider
    sem = asyncio.Semaphore(6)

    async def fetch(inst: Instrument) -> tuple[str, AggregateSeries | None]:
        async with sem:
            ysym = inst.yahoo_symbol or inst.symbol
            return inst.symbol, await provider.get_aggregates(ysym, range_="5y")

    fetched = await asyncio.gather(*(fetch(i) for i in [*universe] + ([spy] if spy else [])))
    agg = {sym: series for sym, series in fetched if series is not None}
    spy_series = agg.get("SPY")
    if spy_series is None or not spy_series.bars:
        print("SPY unavailable — aborting")
        return
    bars_by = {i.symbol: srow.bars for i in universe if (srow := agg.get(i.symbol)) is not None}
    n_bars = sorted(len(b) for b in bars_by.values())
    print(f"symbols={len(bars_by)} bars median={n_bars[len(n_bars) // 2]} "
          f"span={min(n_bars)}..{max(n_bars)}")
    lab = run_lab(bars_by, spy_series.bars)
    print(f"cutoff={lab.cutoff}  (train exits before | test enters after)")
    header = f"{'variant':<22}" + "".join(
        f"| {split[:2]} H{h}: hit  exc%   ic  " for split in ("train", "test") for h in HORIZONS
    )
    print(header)
    for name, splits in lab.results.items():
        row = f"{name:<22}"
        for split in ("train", "test"):
            for h in HORIZONS:
                r = splits[split][str(h)]
                hit = f"{r['hit']:.3f}" if r["hit"] is not None else "  -  "
                exc = f"{r['avg_excess_pct']:+.2f}" if r["avg_excess_pct"] is not None else "  -  "
                ic = f"{r['ic']:+.3f}" if r["ic"] is not None else "  -  "
                row += f"| {hit} {exc} {ic} "
        print(row)
    diag = run_diagnosis(bars_by, spy_series.bars)
    for h, st in diag.items():
        print(f"--- H{h} buckets: " + "  ".join(
            f"{k}:n={v['n']} hit={v['hit']} exc={v['avg_excess_pct']}"
            for k, v in st["buckets"].items() if v["n"]))
        print(f"    H{h} regime: " + "  ".join(
            f"{k}:n={v['n']} hit={v['hit']} exc={v['avg_excess_pct']}"
            for k, v in st["regime"].items()))
        print(f"    H{h} thresholds: " + "  ".join(
            f">={k}:n={v['n']} hit={v['hit']} exc={v['avg_excess_pct']}"
            for k, v in st["thresholds"].items()))
    payload = json.dumps({"cutoff": lab.cutoff.isoformat(), "results": lab.results,
                          "diagnosis": diag}, indent=2)
    await asyncio.to_thread(
        Path("signal_lab_results.json").write_text, payload, encoding="utf-8")
    print("saved -> signal_lab_results.json")


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(main())
