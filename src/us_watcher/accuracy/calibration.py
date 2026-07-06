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
    / unknown horizon). Prior x regime x conviction, shrunk toward live results."""
    if side not in ("buy", "sell") or horizon_days not in _BUY_HIT_PRIOR:
        return None
    if side == "buy":
        prior = _BUY_HIT_PRIOR[horizon_days][_tier(total_score)]
        reg = _REGIME_HIT[horizon_days]
        prior *= (reg["risk_on"] if risk_on else reg["risk_off"]) / reg["base"]
    else:
        prior = _SELL_HIT_PRIOR[horizon_days]

    hit = prior
    n_live = 0
    if live_rates:
        live = live_rates.get((horizon_days, side))
        if live is not None:
            live_hit, n_live = live
            hit = (prior * _PRIOR_N + live_hit * n_live) / (_PRIOR_N + n_live)
    return round(max(_TARGET_MIN, min(_TARGET_MAX, hit * 100.0)), 1)


async def live_hit_rates() -> dict[tuple[int, str], tuple[float, int]]:
    """Realized directional hit rates from matured outcomes, keyed by
    (horizon_days, side). Buy-side hit = positive absolute return; sell-side
    hit = negative absolute return. Small/absent samples simply mean the prior
    keeps dominating — never fabricated."""
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
                       RecommendationOutcome.horizon_days.in_(list(_BUY_HIT_PRIOR)))
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
            "Risk-off regimes also raise the buy-action score bar and cut confidence "
            "(measured hit-rate drop when the S&P is below its 200-DMA)."
        ),
        "buy_hit_priors": _BUY_HIT_PRIOR,
        "sell_hit_priors": _SELL_HIT_PRIOR,
        "regime_hit_at_conviction": _REGIME_HIT,
        "live_blend": live_view or {"note": "No matured 20/60/120d outcomes yet — priors dominate."},
    }
