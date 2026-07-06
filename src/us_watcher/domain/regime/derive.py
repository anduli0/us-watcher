"""Derive regime component sub-scores from deterministic features.

Maps the market data we can actually source (keyless) onto the regime
components. Components we cannot source honestly (credit spreads, bottom-up
earnings, valuation, positioning) are left ``None`` and the regime engine
reweights over the rest. This is the seam where richer feeds (FRED credit
spreads, earnings revisions) drop in later without changing the scorer.
"""

from __future__ import annotations

from us_watcher.domain.analytics.features import FeatureSet
from us_watcher.domain.regime.score import RegimeComponents


def _tanh_like(x: float, scale: float) -> float:
    """Squash an unbounded signal into [-1, 1] without importing math.tanh
    semantics that over-saturate; linear near 0, clamped at the tails."""
    y = x / scale
    return max(-1.0, min(1.0, y))


def derive_components(
    *,
    index: FeatureSet | None,
    cap_weight: FeatureSet | None = None,
    equal_weight: FeatureSet | None = None,
    vix_level: float | None = None,
    yield_curve_2s10s: float | None = None,
    dollar_ret_20: float | None = None,
) -> tuple[RegimeComponents, float | None]:
    """Return (components, cap_minus_equal_weight_gap).

    Only ``trend``, ``breadth``, ``volatility`` and ``cross_asset`` are derivable
    from keyless data today; the rest stay ``None`` (honest unavailable).
    """
    trend = None
    if index is not None:
        signals: list[float] = []
        r20 = index.returns.get("r20")
        r60 = index.returns.get("r60")
        if r20 is not None:
            signals.append(_tanh_like(r20, 0.06))
        if r60 is not None:
            signals.append(_tanh_like(r60, 0.12))
        if index.above_ma200 is not None:
            signals.append(1.0 if index.above_ma200 else -1.0)
        if index.above_ma50 is not None:
            signals.append(0.5 if index.above_ma50 else -0.5)
        if index.ma200_slope is not None:
            signals.append(_tanh_like(index.ma200_slope, 0.03))
        if signals:
            trend = max(-1.0, min(1.0, sum(signals) / len(signals)))

    # Breadth proxy: cap-weight vs equal-weight 20d return divergence. If equal
    # weight keeps pace, breadth is healthy (+); if cap-weight runs away, narrow.
    breadth = None
    gap: float | None = None
    if cap_weight is not None and equal_weight is not None:
        cw = cap_weight.returns.get("r20")
        ew = equal_weight.returns.get("r20")
        if cw is not None and ew is not None:
            gap = cw - ew
            # ew >= cw -> broad participation (positive). cw >> ew -> narrow.
            breadth = _tanh_like(ew - cw, 0.03)
            # bias breadth by the absolute tape so a broad *decline* reads bearish
            if ew is not None:
                breadth = max(-1.0, min(1.0, 0.5 * breadth + 0.5 * _tanh_like(ew, 0.05)))

    # Volatility: low VIX supportive, high VIX a drag. ~15 neutral, 12 calm, 25 stressed.
    volatility = None
    if vix_level is not None:
        volatility = max(-1.0, min(1.0, (16.0 - vix_level) / 10.0))

    # Cross-asset confirmation: inverted/flat curve and a surging dollar are
    # headwinds; a steepening curve and soft dollar are tailwinds.
    cross_asset = None
    xs: list[float] = []
    if yield_curve_2s10s is not None:
        xs.append(_tanh_like(yield_curve_2s10s, 1.0))  # spread in pct points
    if dollar_ret_20 is not None:
        xs.append(_tanh_like(-dollar_ret_20, 0.03))
    if xs:
        cross_asset = sum(xs) / len(xs)

    return (
        RegimeComponents(
            trend=trend,
            breadth=breadth,
            volatility=volatility,
            cross_asset=cross_asset,
        ),
        gap,
    )
