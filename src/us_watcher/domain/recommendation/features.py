"""Deterministic component scores for a single instrument (spec §3.1, §24).

Maps real, computable signals to 0-100 component scores. CRITICAL honesty rule
(spec §25): components that require data we do not have keyless (fundamentals,
earnings revisions, true capital-migration evidence) are left ``None`` and
reweighted out — we never proxy capital migration from price momentum. They light
up when a fundamentals/flow feed is configured.
"""

from __future__ import annotations

from us_watcher.domain.analytics.features import FeatureSet
from us_watcher.domain.analytics.series import Bar
from us_watcher.domain.fundamentals import EdgarFacts, FundamentalSnapshot
from us_watcher.domain.recommendation.scoring import ComponentScores, capital_migration_score


def _clamp01(x: float) -> float:
    return max(0.0, min(100.0, x))


def technical_score(feat: FeatureSet) -> float | None:
    parts: list[float] = []
    if feat.above_ma200 is not None:
        parts.append(70.0 if feat.above_ma200 else 30.0)
    if feat.above_ma50 is not None:
        parts.append(62.0 if feat.above_ma50 else 38.0)
    r20 = feat.returns.get("r20")
    if r20 is not None:
        parts.append(_clamp01(50.0 + r20 * 400.0))  # +12.5% -> 100
    r60 = feat.returns.get("r60")
    if r60 is not None:
        parts.append(_clamp01(50.0 + r60 * 180.0))
    if feat.rsi14 is not None:
        # Reward 45-68 (constructive); penalise >80 (overbought) and <25 (broken).
        rsi = feat.rsi14
        if rsi > 80:
            parts.append(40.0)
        elif rsi < 25:
            parts.append(30.0)
        else:
            parts.append(_clamp01(50.0 + (rsi - 50.0) * 0.8))
    if not parts:
        return None
    return round(sum(parts) / len(parts), 1)


def flow_proxy_score(bars: list[Bar]) -> float | None:
    """On-balance-volume-style flow proxy over the last 20 sessions.

    A legitimate *technical flow* proxy (up-volume vs down-volume), NOT a claim
    about institutional flows. Returns ``None`` without volume.
    """
    recent = bars[-21:]
    if len(recent) < 21 or any(b.volume is None for b in recent):
        return None
    up_vol = 0.0
    dn_vol = 0.0
    for i in range(1, len(recent)):
        vol = recent[i].volume or 0.0
        if recent[i].close >= recent[i - 1].close:
            up_vol += vol
        else:
            dn_vol += vol
    total = up_vol + dn_vol
    if total == 0:
        return None
    return round(_clamp01(100.0 * up_vol / total), 1)


def macro_fit_score(regime_score: float | None) -> float | None:
    """Risk-asset macro fit from the composite regime score (-100..100)."""
    if regime_score is None:
        return None
    return round(_clamp01(50.0 + regime_score * 0.45), 1)


def sector_leadership_score(rel_strength_1m: float | None) -> float | None:
    """From the instrument's (or its sector's) 1-month relative strength fraction."""
    if rel_strength_1m is None:
        return None
    return round(_clamp01(50.0 + rel_strength_1m * 500.0), 1)  # +10% RS -> 100


def blend_sub_industry_cycle(
    own_rs: float | None, group_cycle_rs: float | None, *, group_weight: float = 0.4
) -> float | None:
    """Temper a stock's own relative strength with its sub-industry's CYCLE.

    ``group_cycle_rs`` is the mean multi-month relative strength of the name's
    sub-industry peers vs the market — a keyless, deterministic read of where that
    sub-industry's price cycle sits *right now* (memory rolling over vs logic
    accelerating). Blending it into the name's own 1-month relative strength makes
    the sector-leadership signal reflect the industry cycle, not just the single
    stock's short trend: a memory name whose own price has not yet broken is still
    dragged by a rolling-over memory group, and a logic name lagging a strong group
    is lifted. Returns ``own_rs`` unchanged for unclassified names (no group read),
    so this only touches instruments we explicitly classify."""
    if group_cycle_rs is None:
        return own_rs
    if own_rs is None:
        return group_cycle_rs
    w = max(0.0, min(1.0, group_weight))
    return (1.0 - w) * own_rs + w * group_cycle_rs


def risk_score(
    feat: FeatureSet, fund: FundamentalSnapshot | None = None,
    *, is_leveraged: bool = False, is_inverse: bool = False,
) -> float:
    """0 (safe) .. 100 (risky) from volatility, drawdown, structure, and (for
    stocks) fundamental fragility + liquidity/size filters (spec §21)."""
    risk = 18.0
    if feat.realized_vol_20 is not None:
        risk += min(38.0, feat.realized_vol_20 * 110.0)
    if feat.max_drawdown is not None:
        risk += min(18.0, abs(feat.max_drawdown) * 55.0)
    if is_leveraged:
        risk += 15.0
    if is_inverse:
        risk += 10.0
    if fund is not None:
        # persistent loss
        if fund.profit_margin is not None and fund.profit_margin < 0:
            risk += 14.0
        # micro/small-cap fragility
        if fund.market_cap is not None:
            if fund.market_cap < 2e9:
                risk += 16.0
            elif fund.market_cap < 1e10:
                risk += 6.0
        # illiquidity
        if fund.avg_volume is not None and fund.avg_volume < 500_000:
            risk += 10.0
        # leverage
        if fund.debt_to_equity is not None and fund.debt_to_equity > 200:
            risk += 8.0
    return round(min(100.0, risk), 1)


def fundamental_quality_score(fund: FundamentalSnapshot) -> float | None:
    parts: list[float] = []
    if fund.profit_margin is not None:
        parts.append(_clamp01(50.0 + fund.profit_margin * 200.0))   # 25% margin -> 100
    if fund.return_on_equity is not None:
        parts.append(_clamp01(45.0 + fund.return_on_equity * 150.0))
    if fund.gross_margin is not None:
        parts.append(_clamp01(20.0 + fund.gross_margin * 90.0))
    if fund.free_cashflow is not None:
        parts.append(70.0 if fund.free_cashflow > 0 else 30.0)
    if fund.debt_to_equity is not None:
        parts.append(_clamp01(75.0 - fund.debt_to_equity / 6.0))    # 150 D/E -> 50
    return round(sum(parts) / len(parts), 1) if parts else None


def valuation_score(fund: FundamentalSnapshot, current_price: float | None = None) -> float | None:
    """Higher = more attractively valued. PEG-led, P/E and P/B, PLUS the analyst-
    implied upside vs the CURRENT price — a name trading far above its analyst
    target is expensive (low score), far below is cheap (high score). This is what
    makes the BUY/SELL decision price-aware: the same company is a worse buy after
    it has run up. Guards value traps (a negative/absurd multiple is not 'cheap')."""
    parts: list[float] = []
    if fund.peg_ratio is not None and fund.peg_ratio > 0:
        parts.append(_clamp01(110.0 - fund.peg_ratio * 45.0))       # PEG 1 -> 65, 2.5 -> 0
    if fund.forward_pe is not None and 0 < fund.forward_pe < 200:
        parts.append(_clamp01(95.0 - fund.forward_pe * 1.4))        # fPE 25 -> 60
    if fund.price_to_book is not None and 0 < fund.price_to_book < 50:
        parts.append(_clamp01(85.0 - fund.price_to_book * 3.0))
    # Analyst-implied upside vs the current price (only when the target is sane vs
    # price — outside 0.4x-2.5x it is almost certainly stale/bad data).
    if (current_price is not None and current_price > 0 and fund.target_mean is not None
            and 0.4 * current_price <= fund.target_mean <= 2.5 * current_price):
        upside = fund.target_mean / current_price - 1.0
        parts.append(_clamp01(50.0 + upside * 140.0))               # +30% -> ~92, -20% -> ~22
    return round(sum(parts) / len(parts), 1) if parts else None


def earnings_revision_score(fund: FundamentalSnapshot) -> float | None:
    parts: list[float] = []
    up, down = fund.eps_rev_up_30d, fund.eps_rev_down_30d
    if up is not None and down is not None and (up + down) > 0:
        parts.append(_clamp01(50.0 + 50.0 * (up - down) / (up + down)))  # net revision breadth
    if fund.recommendation_mean is not None:
        parts.append(_clamp01((5.0 - fund.recommendation_mean) / 4.0 * 100.0))  # 1=SB->100, 5=S->0
    if fund.earnings_growth_next_y is not None:
        parts.append(_clamp01(50.0 + fund.earnings_growth_next_y * 120.0))
    return round(sum(parts) / len(parts), 1) if parts else None


def capital_migration_components(
    fund: FundamentalSnapshot, current_price: float | None, edgar: EdgarFacts | None = None
) -> dict[str, float]:
    """Real CMS components (spec §25) — never price-momentum-as-migration.
    capex growth and R&D growth come from official SEC EDGAR filings when
    available; backlog/RPO still require deeper filing parsing and are omitted
    (reweighted out), not faked."""
    comp: dict[str, float] = {}
    # Official filing-based capital deployment (SEC EDGAR) — the literal
    # "where the money is going" signal, not a proxy.
    if edgar is not None:
        if edgar.capex_growth_yoy is not None:
            comp["capex_growth"] = round(_clamp01(50.0 + edgar.capex_growth_yoy * 130.0), 1)
        if edgar.rnd_growth_yoy is not None:
            comp["hiring_rnd_patents"] = round(_clamp01(50.0 + edgar.rnd_growth_yoy * 150.0), 1)
    # revenue acceleration + estimate revisions (real)
    if fund.revenue_growth is not None:
        rev = _clamp01(40.0 + fund.revenue_growth * 130.0)          # 30% growth -> ~80
        up, down = fund.eps_rev_up_30d, fund.eps_rev_down_30d
        if up is not None and down is not None and (up + down) > 0:
            rev = 0.6 * rev + 0.4 * _clamp01(50.0 + 50.0 * (up - down) / (up + down))
        comp["revenue_accel_revisions"] = round(rev, 1)
    # moat / pricing power proxy: gross margin + ROE
    moat_parts = []
    if fund.gross_margin is not None:
        moat_parts.append(_clamp01(fund.gross_margin * 130.0))
    if fund.return_on_equity is not None:
        moat_parts.append(_clamp01(40.0 + fund.return_on_equity * 130.0))
    if moat_parts:
        comp["moat_barriers"] = round(sum(moat_parts) / len(moat_parts), 1)
        comp["supply_bottleneck_pricing"] = round(
            _clamp01(fund.gross_margin * 120.0) if fund.gross_margin is not None else 50.0, 1)
    # analyst-implied upside (third-party signal, attributed)
    if fund.target_mean is not None and current_price and current_price > 0:
        upside = fund.target_mean / current_price - 1.0
        comp["valuation_upside"] = round(_clamp01(50.0 + upside * 150.0), 1)
    return comp


def build_component_scores(
    feat: FeatureSet,
    bars: list[Bar],
    *,
    regime_score: float | None,
    rel_strength_1m: float | None,
    fund: FundamentalSnapshot | None = None,
    edgar: EdgarFacts | None = None,
    current_price: float | None = None,
    news_catalyst: float | None = None,
    is_leveraged: bool = False,
    is_inverse: bool = False,
) -> tuple[ComponentScores, dict]:
    """Assemble component scores. With a :class:`FundamentalSnapshot` (stocks),
    fundamental/valuation/earnings-revision and a real partial Capital Migration
    Score are populated; without it (ETFs), those stay ``None`` and are
    reweighted out. Returns (scores, cms_detail)."""
    tech = technical_score(feat)
    flow = flow_proxy_score(bars)

    fq = val = ern = cms = theme = None
    cms_detail: dict = {"score": None, "coverage": 0.0, "components": {}}
    if fund is not None:
        fq = fundamental_quality_score(fund)
        val = valuation_score(fund, current_price)
        ern = earnings_revision_score(fund)
        comps = capital_migration_components(fund, current_price, edgar)
        if comps:
            cms_val, cov = capital_migration_score(comps)
            cms = cms_val
            cms_detail = {"score": cms_val, "coverage": cov, "components": comps}
            theme = comps.get("revenue_accel_revisions")

    present = [x for x in (tech, flow, regime_score, rel_strength_1m, fq, val, ern, cms) if x is not None]
    data_quality = min(100.0, 40.0 + 7.0 * len(present))
    scores = ComponentScores(
        technical=tech,
        flow_positioning=flow,
        sector_leadership=sector_leadership_score(rel_strength_1m),
        macro_fit=macro_fit_score(regime_score),
        news_catalyst=news_catalyst,
        fundamental_quality=fq,
        valuation=val,
        earnings_revision=ern,
        capital_migration=cms,
        emerging_theme=theme,
        risk=risk_score(feat, fund, is_leveraged=is_leveraged, is_inverse=is_inverse),
        data_quality=data_quality,
    )
    return scores, cms_detail
