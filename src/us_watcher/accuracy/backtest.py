"""Point-in-time backtester for the deterministic technical signal (spec §32).

Validates that the quant signal has forward-return skill, with NO look-ahead
(the signal at date t uses only bars[:t+1]), transaction costs, and benchmark
excess vs SPY. Reproducible: same bars -> same report. This is an in-sample
*methodology validation* over ~2y of history, honestly labelled — NOT a live
tradeable track record (live recommendation outcomes are tracked separately and
mature over real time in ``recommendation_outcomes``).
"""

from __future__ import annotations

from us_watcher.domain.analytics.indicators import rsi, simple_return, sma
from us_watcher.domain.analytics.series import Bar

WARMUP = 210          # need ~200 bars before the first signal (200-DMA)
DEFAULT_HORIZONS = (20, 60, 120)
LONG_THRESHOLD = 55.0  # signal >= this -> "long" stance
_BUCKETS = [(0, 40), (40, 50), (50, 60), (60, 70), (70, 101)]


def point_in_time_signal(closes: list[float], t: int) -> float | None:
    """Deterministic technical score (0-100) using ONLY closes[:t+1]."""
    window = closes[: t + 1]
    if len(window) < WARMUP:
        return None
    parts: list[float] = []
    m200 = sma(window, 200)
    m50 = sma(window, 50)
    last = window[-1]
    if m200 is not None:
        parts.append(70.0 if last > m200 else 30.0)
    if m50 is not None:
        parts.append(62.0 if last > m50 else 38.0)
    r20 = simple_return(window, 20)
    if r20 is not None:
        parts.append(max(0.0, min(100.0, 50.0 + r20 * 400.0)))
    r60 = simple_return(window, 60)
    if r60 is not None:
        parts.append(max(0.0, min(100.0, 50.0 + r60 * 180.0)))
    r = rsi(window, 14)
    if r is not None:
        parts.append(40.0 if r > 80 else 30.0 if r < 25 else max(0.0, min(100.0, 50.0 + (r - 50.0) * 0.8)))
    return sum(parts) / len(parts) if parts else None


def _bucket(score: float) -> str:
    for lo, hi in _BUCKETS:
        if lo <= score < hi:
            return f"{lo}-{hi if hi <= 100 else 100}"
    return "0-40"


def run_backtest(
    bars_by_symbol: dict[str, list[Bar]],
    benchmark_bars: list[Bar],
    *,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    rebalance_every: int = 21,
    cost_bps: float = 10.0,
    long_threshold: float = LONG_THRESHOLD,
) -> dict:
    """Run the backtest. Returns metrics by horizon + a calibration table."""
    bench_close_by_date = {b.as_of.date(): b.close for b in benchmark_bars}
    cost = cost_bps / 10000.0

    # accumulators
    by_h: dict[int, dict] = {
        h: {"n": 0, "long_n": 0, "long_wins": 0, "long_ret": 0.0, "long_excess": 0.0,
            "buckets": {f"{lo}-{hi if hi <= 100 else 100}": {"n": 0, "ret": 0.0} for lo, hi in _BUCKETS}}
        for h in horizons
    }

    for _symbol, bars in bars_by_symbol.items():
        if len(bars) < WARMUP + min(horizons):
            continue
        closes = [b.close for b in bars]
        dates = [b.as_of.date() for b in bars]
        for t in range(WARMUP, len(closes), rebalance_every):
            score = point_in_time_signal(closes, t)
            if score is None or closes[t] <= 0:
                continue
            for h in horizons:
                if t + h >= len(closes):
                    continue
                acc = by_h[h]
                fwd = closes[t + h] / closes[t] - 1.0 - 2.0 * cost  # entry+exit cost
                # benchmark forward over the SAME calendar window
                b0 = bench_close_by_date.get(dates[t])
                b1 = bench_close_by_date.get(dates[t + h])
                excess = fwd - (b1 / b0 - 1.0) if (b0 and b1 and b0 > 0) else 0.0
                acc["n"] += 1
                bk = acc["buckets"][_bucket(score)]
                bk["n"] += 1
                bk["ret"] += fwd
                if score >= long_threshold:
                    acc["long_n"] += 1
                    acc["long_ret"] += fwd
                    acc["long_excess"] += excess
                    if fwd > 0:
                        acc["long_wins"] += 1

    return _finalize(by_h, horizons, rebalance_every, cost_bps, long_threshold)


def _finalize(by_h: dict, horizons: tuple[int, ...], rebalance: int, cost_bps: float, thr: float) -> dict:
    out_h: dict[str, dict] = {}
    monotonic_ok = True
    for h in horizons:
        a = by_h[h]
        ln = a["long_n"]
        buckets = {}
        bucket_avgs = []
        for name, bk in a["buckets"].items():
            avg = round(bk["ret"] / bk["n"] * 100, 2) if bk["n"] else None
            buckets[name] = {"n": bk["n"], "avg_return_pct": avg}
            if avg is not None:
                bucket_avgs.append((name, avg))
        # calibration monotonicity: do higher score buckets have higher avg forward return?
        ordered = [v for _, v in bucket_avgs]
        if len(ordered) >= 3 and not _mostly_increasing(ordered):
            monotonic_ok = False
        out_h[str(h)] = {
            "samples": a["n"],
            "long_signals": ln,
            "long_hit_rate": round(a["long_wins"] / ln, 3) if ln else None,
            "long_avg_return_pct": round(a["long_ret"] / ln * 100, 2) if ln else None,
            "long_avg_excess_pct": round(a["long_excess"] / ln * 100, 2) if ln else None,
            "calibration_buckets": buckets,
        }
    return {
        "method": "point_in_time_technical_signal",
        "note": "In-sample methodology validation over ~2y history; no look-ahead, "
                f"{cost_bps:.0f}bps round-trip cost, rebalance every {rebalance} trading days, "
                f"long when signal>={thr:.0f}. NOT a live tradeable track record.",
        "by_horizon": out_h,
        "calibration_monotonic": monotonic_ok,
    }


def _mostly_increasing(xs: list[float]) -> bool:
    """True if the sequence trends upward (allows minor dips) — a skill cue."""
    if len(xs) < 2:
        return True
    ups = sum(1 for i in range(1, len(xs)) if xs[i] >= xs[i - 1])
    return ups >= (len(xs) - 1) / 2
