"""Empirical confidence calibration (spec §32) — the accuracy feedback loop.

Problem this fixes: the structural confidence (coverage x data quality) said
~66% while the measured base rate of a short-horizon long call was ~54% —
systematic overconfidence. Calibration anchors each recommendation's confidence
to MEASURED hit rates instead:

1. **Priors** — a 5-year point-in-time study of the deterministic technical
   signal (185 symbols, embargoed splits; reproducible via
   ``python -m us_watcher.accuracy.signal_lab``) gives base hit rates by
   horizon, conviction tier, and market-regime side.
2. **Live feedback** — as real ``recommendation_outcomes`` mature they are
   blended in with sample-size weighting, so over time the system's OWN track
   record dominates the historical prior. Self-correcting: if live calls hit
   less often than the prior claims, confidence drifts down automatically.

Nothing here fabricates precision: with few live outcomes the prior dominates;
targets are clamped to an honest band and never exceed 85%.
"""

from __future__ import annotations

from sqlalchemy import select

from us_watcher.domain.enums import Horizon, RecAction

# Recommendation display horizons -> evaluation horizon (trading days).
HORIZON_DAYS: dict[Horizon, int] = {
    Horizon.SHORT: 20,
    Horizon.MEDIUM: 60,
    Horizon.MEDIUM_LONG: 120,
}

BUY_SIDE = {RecAction.STRONG_BUY, RecAction.BUY, RecAction.ACCUMULATE}
SELL_SIDE = {RecAction.REDUCE, RecAction.SELL, RecAction.AVOID}

# ---- measured priors (signal_lab diagnosis, 2026-07-05; 5y, point-in-time) ----
# Buy-side: fraction of long signals with positive forward return, by conviction
# tier of the total score (>=70 high, >=60 mid, else base) — the study showed
# hit rate AND benchmark excess rise monotonically with signal conviction
# (H120 excess: +4.98% at >=55 -> +10.54% at >=70).
_BUY_HIT_PRIOR: dict[int, dict[str, float]] = {
    20: {"hi": 0.554, "mid": 0.537, "base": 0.537},
    60: {"hi": 0.573, "mid": 0.562, "base": 0.566},
    120: {"hi": 0.646, "mid": 0.637, "base": 0.635},
}
# Regime conditioning at >=55 conviction (risk_on = composite regime not in the
# risk-off set; measured proxy: S&P above/below its 200-DMA).
_REGIME_HIT: dict[int, dict[str, float]] = {
    20: {"risk_on": 0.553, "risk_off": 0.430, "base": 0.537},
    60: {"risk_on": 0.584, "risk_off": 0.453, "base": 0.566},
    120: {"risk_on": 0.654, "risk_off": 0.517, "base": 0.635},
}
# Sell-side correctness prior = 1 - hit of LOW-score (0-45) names: in the 5y
# sample, beaten-down names still rose 56/63/66% of the time (H20/H60/H120) —
# so a long-horizon SELL is right far less often than it feels. Honest, low.
_SELL_HIT_PRIOR: dict[int, float] = {20: 0.436, 60: 0.368, 120: 0.340}

# Prior weight in "virtual samples" — live outcomes overtake it as they mature.
_PRIOR_N = 300
_TARGET_MIN, _TARGET_MAX = 25.0, 85.0

# ---- early live evidence (matured short-window outcomes) ---------------------
# By 2026-07 the system had 1,293 matured LIVE outcomes (h1 n=1281 hit 45.7%,
# h5 n=12 hit 75%) while every 20/60/120d display horizon was still immature —
# so NONE of the system's own track record reached calibration. A matured 5-day
# outcome IS a real live directional result; it counts toward the 20d bucket at
# an explicit discount of 5/20 = 0.25 of its sample size (a 5d window covers a
# quarter of the 20d horizon, so 4 early outcomes carry the evidential weight
# of 1 matured 20d one — small n cannot swing confidence; see the shrinkage
# math in ``confidence_target_pct``).
# 1-day outcomes are EXCLUDED entirely: single-day direction is noise-dominated
# (measured live: hit 45.7% yet positive expectancy — avg gain +1.41% vs avg
# loss −1.03% — i.e. the daily direction bit carries ~no signal about the 20d
# outcome; blending it would add noise, not evidence).
_EARLY_EVIDENCE_DISCOUNT: dict[int, dict[int, float]] = {20: {5: 0.25}}
# Horizons live_hit_rates() must fetch: the display horizons plus every
# discounted early-evidence source horizon (h1 deliberately absent).
_QUERY_HORIZONS: list[int] = sorted(
    {*_BUY_HIT_PRIOR, *(h for srcs in _EARLY_EVIDENCE_DISCOUNT.values() for h in srcs)}
)


def _tier(total_score: float) -> str:
    if total_score >= 70.0:
        return "hi"
    if total_score >= 60.0:
        return "mid"
    return "base"


def action_side(action: RecAction) -> str:
    if action in BUY_SIDE:
        return "buy"
    if action in SELL_SIDE:
        return "sell"
    return "neutral"


def confidence_target_pct(
    horizon_days: int,
    total_score: float,
    side: str,
    *,
    risk_on: bool,
    live_rates: dict[tuple[int, str], tuple[float, int]] | None = None,
) -> float | None:
    """Empirical confidence target (0-100) for a call, or ``None`` (neutral side
    / unknown horizon). Prior x regime x conviction, shrunk toward live results.

    Live evidence = matured same-horizon outcomes at FULL weight plus matured
    short-window outcomes at the documented ``_EARLY_EVIDENCE_DISCOUNT`` (e.g.
    12 matured 5d outcomes = 3 effective samples vs a 300-strong prior — barely
    a nudge; thousands would rightly dominate). Never fabricated precision."""
    if side not in ("buy", "sell") or horizon_days not in _BUY_HIT_PRIOR:
        return None
    if side == "buy":
        prior = _BUY_HIT_PRIOR[horizon_days][_tier(total_score)]
        reg = _REGIME_HIT[horizon_days]
        prior *= (reg["risk_on"] if risk_on else reg["risk_off"]) / reg["base"]
    else:
        prior = _SELL_HIT_PRIOR[horizon_days]

    num = prior * _PRIOR_N
    den = float(_PRIOR_N)
    if live_rates:
        live = live_rates.get((horizon_days, side))
        if live is not None:
            live_hit, n_live = live
            num += live_hit * n_live
            den += n_live
        for early_h, discount in _EARLY_EVIDENCE_DISCOUNT.get(horizon_days, {}).items():
            early = live_rates.get((early_h, side))
            if early is not None:
                early_hit, early_n = early
                num += early_hit * (early_n * discount)
                den += early_n * discount
    hit = num / den
    return round(max(_TARGET_MIN, min(_TARGET_MAX, hit * 100.0)), 1)


async def live_hit_rates() -> dict[tuple[int, str], tuple[float, int]]:
    """Realized directional hit rates from matured outcomes, keyed by
    (horizon_days, side). Buy-side hit = positive absolute return; sell-side
    hit = negative absolute return. Fetches the display horizons AND the
    early-evidence source horizons (matured 5d outcomes, discounted into the
    20d bucket by ``confidence_target_pct``; 1d is excluded as noise-dominated).
    Small/absent samples simply mean the prior keeps dominating — never
    fabricated."""
    from us_watcher.db.models import Recommendation, RecommendationOutcome
    from us_watcher.infrastructure.db import get_sessionmaker

    sm = get_sessionmaker()
    async with sm() as s:
        rows = (
            await s.execute(
                select(RecommendationOutcome.horizon_days, Recommendation.action,
                       RecommendationOutcome.abs_return_pct)
                .join(Recommendation, RecommendationOutcome.recommendation_id == Recommendation.id)
                .where(RecommendationOutcome.status == "evaluated",
                       RecommendationOutcome.abs_return_pct.is_not(None),
                       RecommendationOutcome.horizon_days.in_(_QUERY_HORIZONS))
            )
        ).all()

    acc: dict[tuple[int, str], list[int]] = {}
    for horizon_days, action, abs_ret in rows:
        try:
            side = action_side(RecAction(action))
        except ValueError:
            continue
        if side == "neutral":
            continue
        won = (abs_ret > 0) if side == "buy" else (abs_ret < 0)
        key = (int(horizon_days), side)
        wins_n = acc.setdefault(key, [0, 0])
        wins_n[0] += 1 if won else 0
        wins_n[1] += 1
    return {k: (wins / n, n) for k, (wins, n) in acc.items() if n > 0}


def calibration_summary(live_rates: dict[tuple[int, str], tuple[float, int]] | None = None) -> dict:
    """Transparency block for /accuracy: priors, live blend state, and method."""
    live_view = {
        f"h{h}_{side}": {"hit": round(hit, 3), "n": n}
        for (h, side), (hit, n) in (live_rates or {}).items()
    }
    return {
        "method": (
            "Confidence is blended toward measured base rates: 5y point-in-time priors "
            "(by horizon, conviction tier, and market-regime side; signal_lab, embargoed) "
            f"shrunk toward live recommendation outcomes with prior weight n={_PRIOR_N}. "
            "Matured short-window live outcomes count early at an explicit discount (see "
            "early_evidence). Risk-off regimes also raise the buy-action score bar and cut "
            "confidence (measured hit-rate drop when the S&P is below its 200-DMA)."
        ),
        "buy_hit_priors": _BUY_HIT_PRIOR,
        "sell_hit_priors": _SELL_HIT_PRIOR,
        "regime_hit_at_conviction": _REGIME_HIT,
        "early_evidence": {
            "discounts": {
                f"h{target}_from_h{src}": disc
                for target, srcs in _EARLY_EVIDENCE_DISCOUNT.items()
                for src, disc in srcs.items()
            },
            "note": (
                "Matured 5d live outcomes count toward the 20d bucket at 0.25x their "
                "sample size (a 5d window covers a quarter of the 20d horizon). 1d "
                "outcomes are excluded: single-day direction is noise-dominated (live: "
                "45.7% hit with positive expectancy), so it would add noise, not evidence."
            ),
        },
        "live_blend": live_view or {
            "note": "No matured 20/60/120d (or discounted 5d) outcomes yet — priors dominate."
        },
    }
