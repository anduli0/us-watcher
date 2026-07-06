"""Recommendation generation pipeline (spec §21-26).

Generates short / medium / medium-to-long recommendations for the tracked ETF
universe from deterministic component scores, then persists each as an immutable
revision. Every recommendation has evidence, risks, invalidation conditions,
three scenarios, and a dissent — and NO fabricated target prices (target_range
stays None; we have no valuation model in the keyless tier).

The candidate set is ETFs (sector/core/style) we can source keyless. Single-stock
coverage drops in when a constituents + fundamentals feed is configured; the
engine itself is identical.
"""

from __future__ import annotations

import asyncio

from us_watcher.config import get_settings
from us_watcher.db.repositories import (
    add_audit_event,
    latest_recommendations,
    record_big_bets_weekly,
    save_recommendation,
)
from us_watcher.domain.analytics.features import FeatureSet, build_features
from us_watcher.domain.analytics.indicators import relative_strength
from us_watcher.domain.analytics.series import closes
from us_watcher.domain.enums import AssetType, DataStatus, Horizon, RecAction
from us_watcher.domain.fundamentals import EdgarFacts, FundamentalSnapshot
from us_watcher.domain.recommendation.config import ETF_APPLICABLE_KEYS, STOCK_APPLICABLE_KEYS
from us_watcher.domain.recommendation.features import build_component_scores
from us_watcher.domain.recommendation.schemas import Recommendation, Scenario
from us_watcher.domain.recommendation.scoring import ComponentScores, ScoreResult, score_recommendation
from us_watcher.domain.time import now_utc
from us_watcher.domain.universe import Instrument, SpotlightEntry
from us_watcher.infrastructure.edgar import EdgarProvider
from us_watcher.infrastructure.marketdata.fundamentals import YahooFundamentalsProvider
from us_watcher.market.schemas import RegimePulse
from us_watcher.market.service import get_market_service

_HORIZONS = [Horizon.SHORT, Horizon.MEDIUM, Horizon.MEDIUM_LONG]
_HORIZON_DAYS = {Horizon.SHORT: 20, Horizon.MEDIUM: 120, Horizon.MEDIUM_LONG: 252}
BIG_BETS_TOP_N = 6  # 🐋 대어 — keep in sync with the web MoonshotSection
# Above this share of MOCK candidate prices, a live-mode run is ABORTED rather
# than overwriting the prior real recommendations with synthetic-priced ones
# (CLAUDE.md invariant 2). Below it, individual mock names are skipped and the
# rest of the (live) board is refreshed normally.
_MAX_MOCK_FRACTION = 0.4


async def _fetch_fundamentals(symbols: list[str]) -> dict[str, FundamentalSnapshot]:
    """Fetch fundamentals for stocks with bounded concurrency (polite to Yahoo)."""
    provider = YahooFundamentalsProvider()
    sem = asyncio.Semaphore(6)

    async def one(sym: str) -> tuple[str, FundamentalSnapshot | None]:
        async with sem:
            return sym, await provider.get_fundamentals(sym)

    try:
        pairs = await asyncio.gather(*(one(s) for s in symbols))
    finally:
        await provider.aclose()
    return {s: f for s, f in pairs if f is not None}


async def _fetch_edgar(symbols: list[str]) -> dict[str, EdgarFacts]:
    """Fetch SEC EDGAR capex/R&D facts for stocks (bounded concurrency; SEC <=10 req/s)."""
    provider = EdgarProvider()
    sem = asyncio.Semaphore(5)

    async def one(sym: str) -> tuple[str, EdgarFacts | None]:
        async with sem:
            return sym, await provider.get_facts(sym)

    try:
        pairs = await asyncio.gather(*(one(s) for s in symbols))
    finally:
        await provider.aclose()
    return {s: f for s, f in pairs if f is not None}


def mock_data_gate(
    statuses: list[DataStatus], *, live_mode: bool
) -> tuple[bool, int, int, float]:
    """Decide whether to ABORT a recommendation run because too much of the
    candidate price data degraded to MOCK (CLAUDE.md invariant 2). Pure function
    so the data-integrity policy is unit-testable in isolation.

    Returns ``(abort, mock_count, total, mock_fraction)``. In explicit mock mode
    (``live_mode=False``) mock is intentional (offline demo) so we never abort.
    """
    total = len(statuses)
    mock_n = sum(1 for s in statuses if s == DataStatus.MOCK)
    frac = (mock_n / total) if total else 1.0
    abort = live_mode and (total == 0 or frac > _MAX_MOCK_FRACTION)
    return abort, mock_n, total, frac


async def generate_recommendations() -> dict:
    from us_watcher.accuracy.calibration import (
        HORIZON_DAYS,
        action_side,
        confidence_target_pct,
        live_hit_rates,
    )
    from us_watcher.domain.recommendation.config import RISK_OFF_REGIMES

    svc = get_market_service()
    overview = await svc.build_overview()
    rotation = await svc.build_rotation()
    regime_score = overview.pulse.score
    regime = overview.pulse.regime
    # Realized-accuracy feedback: matured live outcomes shrink the calibration
    # priors (accuracy/calibration.py). Fetched once per run — deterministic.
    live_rates = await live_hit_rates()
    risk_on = regime not in RISK_OFF_REGIMES

    rel_by_symbol: dict[str, float | None] = {}
    for srow in rotation.sectors:
        rel_by_symbol[srow.symbol] = (srow.rel_strength_1m / 100.0) if srow.rel_strength_1m is not None else None
    for strow in rotation.style_leadership:
        rel_by_symbol[strow.symbol] = (strow.rel_strength_1m / 100.0) if strow.rel_strength_1m is not None else None

    u = svc._universe
    etf_candidates = [*u.sectors, *u.etfs_core, *u.styles]
    stock_candidates = u.stocks
    cc_candidates = u.covered_call_etfs
    candidates = [*etf_candidates, *stock_candidates, *cc_candidates]
    bench = u.by_symbol("SPY")
    agg = await svc._fetch_many([*candidates, bench] if bench else candidates)

    # Data-integrity gate (CLAUDE.md invariant 2): in live mode, NEVER persist a
    # recommendation board built on synthetic MOCK prices as if it were a real
    # session. A burst rate-limit that degraded most candidates to mock must not
    # overwrite the prior live (immutable) revisions with fiction — abort the run
    # and keep the last real recommendations instead.
    live_mode = get_settings().market_data_provider != "mock"
    usable = [s for s in (agg.get(i.symbol) for i in candidates) if s is not None and len(s.bars) >= 60]
    abort, mock_n, total_n, mock_frac = mock_data_gate(
        [s.status for s in usable], live_mode=live_mode)
    if abort:
        await add_audit_event(
            "recommendations.skipped_degraded_data",
            f"Aborted recommendation run: {mock_n}/{total_n} candidate prices were MOCK "
            f"(> {_MAX_MOCK_FRACTION:.0%} threshold). Kept the prior live recommendations "
            "rather than overwriting them with synthetic prices.",
            payload={"mock": mock_n, "total": total_n, "mock_fraction": round(mock_frac, 3)})
        return {"generated": 0, "skipped": True, "reason": "degraded_data",
                "mock": mock_n, "total": total_n, "mock_fraction": round(mock_frac, 3),
                "as_of": now_utc().isoformat()}

    # SPY baseline for per-stock relative strength
    spy_series = agg.get("SPY")
    spy_closes = closes(spy_series.bars) if spy_series and spy_series.bars else []

    # fundamentals (Yahoo) + SEC EDGAR capex/R&D for stocks; yields for covered-call ETFs
    stock_syms = [s.symbol for s in stock_candidates]
    cc_syms = [c.symbol for c in cc_candidates]
    funds, edgars, cc_funds = await asyncio.gather(
        _fetch_fundamentals(stock_syms), _fetch_edgar(stock_syms), _fetch_fundamentals(cc_syms))

    generated = 0
    skipped_mock = 0
    by_action: dict[str, int] = {}
    items: list[dict] = []
    for inst in candidates:
        series = agg.get(inst.symbol)
        if series is None or len(series.bars) < 60:
            continue
        if live_mode and series.status == DataStatus.MOCK:
            # Don't persist a synthetic-priced recommendation; the prior live
            # revision stays as the latest for this lineage (invariant 2).
            skipped_mock += 1
            continue
        is_stock = inst.group == "stock"
        is_cc = inst.group == "covered_call"
        feat = build_features(inst.symbol, series.bars, series.as_of)
        cs = closes(series.bars)
        if is_stock or is_cc:
            rs = relative_strength(cs, spy_closes, 21) if spy_closes else None
        else:
            rs = rel_by_symbol.get(inst.symbol)
        fund = funds.get(inst.symbol) if is_stock else None
        edgar = edgars.get(inst.symbol) if is_stock else None
        cc_fund = cc_funds.get(inst.symbol) if is_cc else None
        scores, cms_detail = build_component_scores(
            feat, series.bars, regime_score=regime_score, rel_strength_1m=rs,
            fund=fund, edgar=edgar, current_price=cs[-1],
        )
        spot = u.spotlight.get(inst.symbol) if is_stock else None
        # Confidence coverage must be measured against what this asset class can
        # KNOW (spec §24): an ETF has no bottom-up fundamentals, so penalising its
        # confidence for them would mask every keyless BUY as WATCH. Stocks are
        # held to the full set — missing fundamentals there is a genuine gap.
        applicable_keys = STOCK_APPLICABLE_KEYS if is_stock else ETF_APPLICABLE_KEYS
        for horizon in _HORIZONS:
            # Two-pass scoring: a preliminary pass decides which SIDE the call is
            # on, then the empirical hit-rate target for that side/horizon/
            # conviction/regime is blended into the final confidence (and the
            # WATCH floor re-checked against the calibrated value).
            prelim = score_recommendation(
                scores, horizon=horizon, regime=regime, applicable_keys=applicable_keys
            )
            target = confidence_target_pct(
                HORIZON_DAYS[horizon], prelim.total_score, action_side(prelim.action),
                risk_on=risk_on, live_rates=live_rates,
            )
            result = score_recommendation(
                scores, horizon=horizon, regime=regime, applicable_keys=applicable_keys,
                confidence_target=target,
            )
            rec = _build_recommendation(inst, feat, scores, result, horizon, overview.pulse,
                                        cms_detail=cms_detail, fund=fund, is_stock=is_stock,
                                        is_covered_call=is_cc, cc_fund=cc_fund, spotlight=spot,
                                        price_status=series.status)
            saved = await save_recommendation(
                rec.model_dump(mode="json"),
                ticker=inst.symbol, horizon=horizon.value, action=result.action.value,
                total_score=result.total_score, confidence=result.confidence,
                one_line=rec.one_line_thesis_en, asset_type=rec.asset_type.value,
                company_name=inst.name, as_of=rec.as_of, expires_at=rec.expires_at,
                data_freshness=rec.data_freshness,
            )
            generated += 1
            by_action[result.action.value] = by_action.get(result.action.value, 0) + 1
            items.append({"ticker": inst.symbol, "horizon": horizon.value,
                          "action": result.action.value, "score": result.total_score,
                          "change_type": saved["change_type"]})

    await add_audit_event(
        "recommendations.generated",
        f"Generated {generated} recs ({len(funds)} w/ fundamentals, {len(edgars)} w/ SEC EDGAR; "
        f"{skipped_mock} mock-priced names skipped)",
        payload={"by_action": by_action, "stocks_with_fundamentals": len(funds),
                 "stocks_with_edgar": len(edgars), "skipped_mock": skipped_mock,
                 "mock_fraction": round(mock_frac, 3)})
    big_bets_new = await _maybe_snapshot_big_bets()
    return {"generated": generated, "skipped_mock": skipped_mock,
            "mock_fraction": round(mock_frac, 3), "as_of": now_utc().isoformat(),
            "by_action": by_action, "stocks_with_fundamentals": len(funds),
            "stocks_with_edgar": len(edgars), "big_bets_snapshot": big_bets_new, "items": items}


def rank_big_bets(recs: list[dict], n: int = BIG_BETS_TOP_N) -> list[dict]:
    """The 🐋 대어 list: highest moonshot stock per ticker, >0, top N (mirrors the web)."""
    best: dict[str, dict] = {}
    for r in recs:
        if r.get("asset_type") != "stock":
            continue
        t = r["ticker"]
        cur = best.get(t)
        if cur is None or (r.get("moonshot_score") or 0) > (cur.get("moonshot_score") or 0):
            best[t] = r
    ranked = [r for r in best.values() if (r.get("moonshot_score") or 0) > 0]
    ranked.sort(key=lambda r: -(r.get("moonshot_score") or 0))
    return ranked[:n]


async def _maybe_snapshot_big_bets() -> bool:
    """Freeze the Big-Bet list once per ISO week (the first run of a new week wins;
    later daily runs no-op). Long-horizon convictions shouldn't churn daily;
    repeats across weeks are fine. Returns True when a fresh snapshot was written."""
    picks = rank_big_bets(await latest_recommendations())
    if not picks:
        return False
    now = now_utc()
    iso_year, iso_week, _ = now.isocalendar()
    return await record_big_bets_weekly(f"{iso_year}-W{iso_week:02d}", picks, as_of=now.isoformat())


def _build_recommendation(
    inst: Instrument, feat: FeatureSet, scores: ComponentScores, result: ScoreResult,
    horizon: Horizon, pulse: RegimePulse, *, cms_detail: dict, fund: FundamentalSnapshot | None,
    is_stock: bool, is_covered_call: bool = False, cc_fund: FundamentalSnapshot | None = None,
    spotlight: SpotlightEntry | None = None, price_status: DataStatus = DataStatus.DELAYED,
) -> Recommendation:
    r20 = feat.returns.get("r20")
    vol = feat.realized_vol_20
    now = now_utc()
    (reasons_en, reasons_ko), (risks_en, risks_ko), (inval_en, inval_ko) = _evidence(
        inst, feat, scores, result, fund)
    bull, base, bear = _scenarios(result.total_score, vol, inst.name)
    thesis_en, thesis_ko = _thesis(inst, result, horizon, r20)
    cat_en, cat_ko = _catalysts(inst, pulse)
    if spotlight is not None:
        # Surface WHY this name is highlighted (honest, labelled as a focus theme).
        if spotlight.note_en:
            cat_en = [f"🔭 {spotlight.theme_en or 'In focus'}: {spotlight.note_en}", *cat_en][:4]
        if spotlight.note_ko:
            cat_ko = [f"🔭 {spotlight.theme_ko or '관심 테마'}: {spotlight.note_ko}", *cat_ko][:4]
    cms_score = cms_detail.get("score")

    asset_type = AssetType.COVERED_CALL_ETF if is_covered_call else (
        AssetType.STOCK if is_stock else AssetType.ETF)
    fund_en, fund_ko = _fundamental_summary(fund)
    val_en, val_ko = _valuation_summary(fund)
    cms_en, cms_ko = _cms_summary(cms_detail, fund)
    diss_en, diss_ko = _dissent(feat, result)
    if is_covered_call:
        underlying = str((inst.extra or {}).get("underlying", "SPY"))
        fund_en, fund_ko, cc_risks_en, cc_risks_ko = _covered_call_notes(cc_fund, underlying, pulse)
        risks_en = [*cc_risks_en, *risks_en][:5]
        risks_ko = [*cc_risks_ko, *risks_ko][:5]
        val_en = (f"Income strategy — judge on TOTAL RETURN vs {underlying}, not distribution yield; "
                  "options writing caps upside and distributions may include return of capital.")
        val_ko = (f"인컴 전략 — 분배수익률이 아니라 {underlying} 대비 '총수익'으로 판단하세요. 옵션 매도가 상승을 "
                  "제한하고 분배금에 원금 환급분이 섞일 수 있습니다.")
        diss_en = (f"Bull case: in a strong advance the underlying ({underlying}) typically out-totals a "
                   "covered-call wrapper; high yield is not outperformance.")
        diss_ko = (f"강세 시각: 강한 상승장에서는 기초자산({underlying})의 총수익이 커버드콜을 대개 앞섭니다 — 높은 "
                   "수익률이 곧 초과성과는 아닙니다.")

    top_reason = (reasons_en[0], reasons_ko[0]) if reasons_en else None
    top_risk = (risks_en[0], risks_ko[0]) if risks_en else None
    top_inval = (inval_en[0], inval_ko[0]) if inval_en else None
    rat_en, rat_ko = _rationale(inst, result, horizon, top_reason, top_risk, top_inval)
    hotness = _hotness(feat, fund, cms_score, result.total_score, spotlight=spotlight)
    moonshot = _moonshot(feat, fund, cms_score, spotlight=spotlight) if is_stock else 0.0
    # NEVER derive a target band from an untrustworthy price (CLAUDE.md invariant 2):
    #  - MOCK fallback prices are synthetic (this produced a $6,637 band for a $55 stock);
    #  - chart prices that diverge >3x from the analyst target are corrupt source data.
    # Either way: no trustworthy anchor → no band (invariant 4).
    price_is_mock = price_status == DataStatus.MOCK
    price_corrupt = _price_is_corrupt(feat.last_close, fund.target_mean if fund else None)
    price_trusted = not price_is_mock and not price_corrupt
    tgt_low, tgt_high, tb_en, tb_ko = (
        _target_range(feat.last_close, fund, vol, result.total_score, horizon, result.confidence, result.action)
        if (is_stock and price_trusted) else (None, None, "", "")
    )

    return Recommendation(
        ticker=inst.symbol, company_name=inst.name, asset_type=asset_type,
        horizon=horizon, action=result.action,
        total_score=result.total_score, confidence=result.confidence,
        as_of=now, expires_at=None,
        one_line_thesis_en=thesis_en, one_line_thesis_ko=thesis_ko,
        rationale_en=rat_en, rationale_ko=rat_ko,
        reasons=reasons_en, reasons_ko=reasons_ko,
        catalysts=cat_en, catalysts_ko=cat_ko,
        risks=risks_en, risks_ko=risks_ko,
        invalidation_conditions=inval_en, invalidation_conditions_ko=inval_ko,
        technical_summary=_technical_summary(feat),
        fundamental_summary=fund_en, fundamental_summary_ko=fund_ko,
        valuation_summary=val_en, valuation_summary_ko=val_ko,
        capital_migration_summary=cms_en, capital_migration_summary_ko=cms_ko,
        capital_migration_score=cms_score,
        hotness_score=hotness,
        moonshot_score=moonshot,
        spotlight_theme_en=spotlight.theme_en if spotlight else "",
        spotlight_theme_ko=spotlight.theme_ko if spotlight else "",
        spotlight_note_en=spotlight.note_en if spotlight else "",
        spotlight_note_ko=spotlight.note_ko if spotlight else "",
        target_low=tgt_low, target_high=tgt_high,
        target_basis_en=tb_en, target_basis_ko=tb_ko,
        bull_scenario=bull, base_scenario=base, bear_scenario=bear,
        dissent_summary=diss_en, dissent_summary_ko=diss_ko,
        component_scores={k: v for k, v in scores.model_dump().items()},
        contributions=result.contributions,
        evidence_ids=[f"feat:{inst.symbol}:{horizon.value}"]
        + ([f"fund:{inst.symbol}"] if fund is not None else []),
        data_freshness=(
            "mock" if price_is_mock
            else "suspect" if price_corrupt
            else "fresh" if (is_stock and fund is not None) or feat.availability() >= 0.6
            else "mixed"
        ),
    )


def _covered_call_notes(
    cc_fund: FundamentalSnapshot | None, underlying: str, pulse: RegimePulse
) -> tuple[str, str, list[str], list[str]]:
    """Covered-call structural analysis (spec §27) — never recommend on yield alone."""
    y = cc_fund.dividend_yield if cc_fund and cc_fund.dividend_yield is not None else None
    yield_en = f"distribution yield ~{y * 100:.1f}%" if y else "distribution yield n/a"
    yield_ko = f"분배수익률 ~{y * 100:.1f}%" if y else "분배수익률 미상"
    summary_en = (f"Covered-call/option-income ETF: {yield_en}. Writes calls on {underlying} — trades "
                  "upside for income; distribution is not total return and may include return of capital.")
    summary_ko = (f"커버드콜·옵션인컴 ETF: {yield_ko}. {underlying}에 콜옵션을 매도해 상승 여력을 인컴과 맞바꾸는 "
                  "구조 — 분배금은 총수익이 아니며 원금 환급분이 섞일 수 있습니다.")
    risks_en = [
        "Capped upside — lags the underlying in strong advances (opportunity cost).",
        "NAV erosion risk if distributions exceed total return.",
        "Distribution yield ≠ total return; payouts may include return of capital.",
    ]
    risks_ko = [
        "상승 여력 제한 — 강한 상승장에서 기초자산에 뒤처집니다(기회비용).",
        "분배금이 총수익을 넘으면 순자산가치(NAV)가 깎일 위험.",
        "분배수익률 ≠ 총수익 — 지급액에 원금 환급분이 포함될 수 있습니다.",
    ]
    # In a strong/overheated up-state the opportunity cost is highest.
    if pulse.score >= 35:
        risks_en.insert(0, f"Market is a strong advance ({pulse.score:+.0f}) — capped upside most costly now.")
        risks_ko.insert(0, f"지금은 강한 상승 국면({pulse.score:+.0f}) — 상승 여력 제한의 기회비용이 가장 큽니다.")
    return summary_en, summary_ko, risks_en, risks_ko


def _fundamental_summary(fund: FundamentalSnapshot | None) -> tuple[str, str]:
    if fund is None:
        return ("ETF / keyless tier: bottom-up fundamentals not applicable or not sourced.",
                "ETF·키리스 — 개별 기업 펀더멘털이 해당 없거나 수집되지 않았습니다.")
    en: list[str] = []
    ko: list[str] = []
    if fund.profit_margin is not None:
        en.append(f"net margin {fund.profit_margin * 100:.0f}%")
        ko.append(f"순이익률 {fund.profit_margin * 100:.0f}%")
    if fund.revenue_growth is not None:
        en.append(f"revenue growth {fund.revenue_growth * 100:.0f}%")
        ko.append(f"매출성장 {fund.revenue_growth * 100:.0f}%")
    if fund.return_on_equity is not None:
        en.append(f"ROE {fund.return_on_equity * 100:.0f}%")
        ko.append(f"자기자본이익률(ROE) {fund.return_on_equity * 100:.0f}%")
    if fund.free_cashflow is not None:
        en.append("FCF positive" if fund.free_cashflow > 0 else "FCF negative")
        ko.append("잉여현금흐름 흑자" if fund.free_cashflow > 0 else "잉여현금흐름 적자")
    return ("; ".join(en) or "fundamentals unavailable", "; ".join(ko) or "펀더멘털 데이터 없음")


def _valuation_summary(fund: FundamentalSnapshot | None) -> tuple[str, str]:
    if fund is None:
        return ("No valuation model — no target price (avoids false precision).",
                "밸류에이션 모델 없음 — 목표가를 제시하지 않습니다(과도한 정밀함 회피).")
    en: list[str] = []
    ko: list[str] = []
    if fund.forward_pe is not None:
        en.append(f"fwd P/E {fund.forward_pe:.1f}")
        ko.append(f"선행 P/E {fund.forward_pe:.1f}배")
    if fund.peg_ratio is not None:
        en.append(f"PEG {fund.peg_ratio:.2f}")
        ko.append(f"PEG {fund.peg_ratio:.2f}")
    if fund.target_mean is not None:
        en.append(f"analyst mean target ${fund.target_mean:.0f} (third-party consensus)")
        ko.append(f"애널리스트 평균 목표가 ${fund.target_mean:.0f}(외부 컨센서스)")
    return ("; ".join(en) or "valuation data unavailable", "; ".join(ko) or "밸류에이션 데이터 없음")


def _cms_summary(cms_detail: dict, fund: FundamentalSnapshot | None) -> tuple[str | None, str | None]:
    score = cms_detail.get("score")
    if score is None:
        return None, None
    comps = cms_detail.get("components", {})
    keys = ", ".join(comps.keys())
    cov = cms_detail.get("coverage", 0.0)
    has_edgar = "capex_growth" in comps or "hiring_rnd_patents" in comps
    tail_en = "Incl. official SEC EDGAR capex/R&D growth. " if has_edgar else ""
    tail_ko = "공식 SEC EDGAR 설비투자·R&D 성장 포함. " if has_edgar else ""
    en = (f"CMS {score:.0f}/100 (coverage {cov:.0%}; from {keys}). {tail_en}"
          "Backlog/RPO need deeper filing parsing — reweighted out, not estimated.")
    ko = (f"자본이동점수(CMS) {score:.0f}/100 (반영률 {cov:.0%}; 근거: {keys}). {tail_ko}"
          "수주잔고·RPO는 추가 공시 파싱 필요 — 추정하지 않고 가중치에서 제외.")
    return en, ko


def _evidence(
    inst: Instrument, feat: FeatureSet, scores: ComponentScores, result: ScoreResult,
    fund: FundamentalSnapshot | None,
) -> tuple[tuple[list[str], list[str]], tuple[list[str], list[str]], tuple[list[str], list[str]]]:
    reasons_en: list[str] = []
    reasons_ko: list[str] = []
    risks_en: list[str] = []
    risks_ko: list[str] = []
    inval_en: list[str] = []
    inval_ko: list[str] = []

    def rea(en: str, ko: str) -> None:
        reasons_en.append(en)
        reasons_ko.append(ko)

    def rsk(en: str, ko: str) -> None:
        risks_en.append(en)
        risks_ko.append(ko)

    def inv(en: str, ko: str) -> None:
        inval_en.append(en)
        inval_ko.append(ko)

    if fund is not None:  # fundamentals lead for stocks
        if fund.revenue_growth is not None and fund.revenue_growth > 0.15:
            rea(f"Revenue growing {fund.revenue_growth * 100:.0f}% YoY.",
                f"매출이 전년 대비 {fund.revenue_growth * 100:.0f}% 성장 중입니다.")
        if fund.eps_rev_up_30d is not None and fund.eps_rev_down_30d is not None \
                and fund.eps_rev_up_30d > fund.eps_rev_down_30d:
            rea(f"EPS estimates revised up ({fund.eps_rev_up_30d} up vs {fund.eps_rev_down_30d} down, 30d).",
                f"최근 30일 EPS 추정치 상향 우세(상향 {fund.eps_rev_up_30d}·하향 {fund.eps_rev_down_30d}).")
        if fund.profit_margin is not None and fund.profit_margin > 0.2:
            rea(f"High net margin ({fund.profit_margin * 100:.0f}%) — quality/pricing power.",
                f"높은 순이익률({fund.profit_margin * 100:.0f}%) — 수익성·가격결정력이 좋습니다.")
        if fund.peg_ratio is not None and 0 < fund.peg_ratio < 1.2:
            rea(f"PEG {fund.peg_ratio:.2f} — growth reasonably priced.",
                f"PEG {fund.peg_ratio:.2f} — 성장성 대비 밸류가 합리적입니다.")
    if feat.above_ma200:
        rea("Above its 200-day moving average (primary uptrend intact).",
            "주가가 200일선 위에 있어 큰 추세가 상승으로 유지되고 있습니다.")
    if scores.sector_leadership and scores.sector_leadership > 55:
        rea("Positive relative strength vs the S&P 500.", "S&P 500 대비 상대강도가 앞섭니다.")
    if not reasons_en:
        rea("Mixed signals; see the component scores.", "신호가 혼재합니다 — 세부 점수를 참고하세요.")

    if feat.realized_vol_20 is not None:
        rsk(f"Realized volatility {feat.realized_vol_20 * 100:.0f}% (annualised).",
            f"실현 변동성이 연 {feat.realized_vol_20 * 100:.0f}%로 가격 출렁임이 있습니다.")
    if fund is not None:
        if fund.profit_margin is not None and fund.profit_margin < 0:
            rsk("Currently unprofitable (negative net margin).", "현재 적자 상태입니다(순이익률 마이너스).")
        if fund.forward_pe is not None and fund.forward_pe > 45:
            rsk(f"Rich valuation (fwd P/E {fund.forward_pe:.0f}) — sensitive to misses.",
                f"밸류가 비쌉니다(선행 P/E {fund.forward_pe:.0f}배) — 실적이 어긋나면 타격이 큽니다.")
        if fund.market_cap is not None and fund.market_cap < 1e10:
            rsk("Smaller-cap — higher volatility and liquidity risk.",
                "중소형주라 변동성·유동성 위험이 상대적으로 큽니다.")
    if feat.rsi14 is not None and feat.rsi14 > 75:
        rsk(f"RSI {feat.rsi14:.0f} — overbought, vulnerable to mean reversion.",
            f"RSI {feat.rsi14:.0f}로 과매수 — 단기 되돌림에 취약합니다.")
    if fund is None:
        rsk("ETF/keyless tier: no bottom-up fundamentals (medium-long conviction limited).",
            "ETF·키리스라 개별 펀더멘털이 없어 중장기 확신이 제한됩니다.")

    ma50 = feat.moving_averages.get("ma50")
    if ma50 is not None:
        inv(f"A daily close below the 50-day MA (~{ma50:.2f}).",
            f"50일선(~{ma50:.2f})을 종가로 내주면 판단을 거둡니다.")
    if fund is not None:
        inv("Negative earnings-estimate revisions or a guidance cut.",
            "실적 추정치 하향이나 가이던스 하향이 나오면 판단을 거둡니다.")
    inv("A shift in the broad market to a risk-off / correction state.",
        "시장 전반이 위험회피·조정 국면으로 바뀌면 판단을 거둡니다.")
    return (reasons_en[:4], reasons_ko[:4]), (risks_en[:4], risks_ko[:4]), (inval_en[:3], inval_ko[:3])


def _catalysts(inst: Instrument, pulse: RegimePulse) -> tuple[list[str], list[str]]:
    return (
        ["Upcoming macro prints (CPI/PCE, jobs) and FOMC communication.",
         f"Sector earnings season relevant to {inst.name}."],
        ["다가오는 주요 경제지표(소비자물가·고용)와 연준(FOMC)의 신호.",
         f"{inst.name}이(가) 속한 섹터의 실적 시즌."],
    )


def _scenarios(total: float, vol: float | None, inst_name: str) -> tuple[Scenario, Scenario, Scenario]:
    v = vol if vol is not None else 0.18
    p_bull = max(0.15, min(0.55, total / 200.0 + 0.2))
    p_bear = max(0.15, min(0.55, (100 - total) / 200.0 + 0.15))
    p_base = max(0.1, 1.0 - p_bull - p_bear)
    return (
        Scenario(label="bull", probability=round(p_bull, 2),
                 narrative_en="The uptrend holds: sector leadership and inflows stay supportive and "
                              "buyers defend pullbacks, so the stock keeps making higher highs.",
                 narrative_ko="상승 추세 유지 — 섹터 주도력과 자금 유입이 우호적으로 이어지고 눌림목마다 매수가 "
                              "들어와 고점을 높여가는 흐름입니다.", target_range=None),
        Scenario(label="base", probability=round(p_base, 2),
                 narrative_en="The most likely path: it tracks the broad market, drifting sideways to "
                              "modestly higher without a decisive breakout either way.",
                 narrative_ko="가장 가능성 높은 경로 — 시장 전체와 보조를 맞춰 뚜렷한 돌파 없이 횡보~완만한 상승에 "
                              "머무는 흐름입니다.", target_range=None),
        Scenario(label="bear", probability=round(p_bear, 2),
                 narrative_en=f"Risk case: volatility (~{v * 100:.0f}% annualised) expands, relative strength "
                              f"rolls over, and {inst_name} lags the market on any risk-off turn.",
                 narrative_ko=f"위험 시나리오 — 변동성(연 ~{v * 100:.0f}%)이 커지고 상대강도가 꺾이며, 위험회피 "
                              f"전환 시 {inst_name}이(가) 시장보다 부진한 흐름입니다.", target_range=None),
    )


def _thesis(inst: Instrument, result: ScoreResult, horizon: Horizon, r20: float | None) -> tuple[str, str]:
    act = result.action.value.replace("_", " ").upper()
    h = horizon.value
    sc, cf = result.total_score, result.confidence
    en = f"{inst.name}: {act} ({h}) — score {sc:.0f}/100, conf {cf:.0f}%."
    ko = f"{inst.name}: {act} ({h}) — 점수 {sc:.0f}/100, 신뢰도 {cf:.0f}%."
    return en, ko


def _technical_summary(feat: FeatureSet) -> str:
    bits: list[str] = []
    if feat.rsi14 is not None:
        bits.append(f"RSI {feat.rsi14:.0f}")
    r20 = feat.returns.get("r20")
    if r20 is not None:
        bits.append(f"1m {r20 * 100:+.1f}%")
    if feat.above_ma200 is not None:
        bits.append("above 200DMA" if feat.above_ma200 else "below 200DMA")
    return "; ".join(bits) or "n/a"


def _dissent(feat: FeatureSet, result: ScoreResult) -> tuple[str, str]:
    if result.action in (RecAction.STRONG_BUY, RecAction.BUY, RecAction.ACCUMULATE):
        if feat.rsi14 and feat.rsi14 > 70:
            return ("Bear case: overbought and possibly late; the advance may be narrow and mean-revert.",
                    "약세 시각: 과매수이고 다소 늦은 진입일 수 있으며, 상승이 좁아 되돌릴 수 있습니다.")
        return ("Bear case: leadership can rotate quickly and the keyless tier lacks fundamental confirmation.",
                "약세 시각: 주도주는 빠르게 바뀔 수 있고, 키리스 데이터라 펀더멘털 확증이 부족합니다.")
    return ("Bull case: a market-state upturn or a positive catalyst could re-rate this faster than the scores imply.",
            "강세 시각: 시장 국면이 개선되거나 호재가 나오면 점수가 가리키는 것보다 빠르게 재평가될 수 있습니다.")


_ACTION_PHRASE: dict[RecAction, tuple[str, str]] = {
    RecAction.STRONG_BUY: ("a strong buy", "적극 매수"),
    RecAction.BUY: ("a buy", "매수"),
    RecAction.ACCUMULATE: ("one to accumulate", "분할 매수"),
    RecAction.HOLD: ("a hold", "보유"),
    RecAction.WATCH: ("one to watch", "관망"),
    RecAction.REDUCE: ("one to trim", "비중 축소"),
    RecAction.SELL: ("a sell", "매도"),
    RecAction.AVOID: ("one to avoid", "회피"),
}
_HORIZON_KO_PHRASE = {"short": "단기", "medium": "중기", "medium_long": "중장기"}


def _lower_first(s: str) -> str:
    s = s.rstrip(".")
    return s[:1].lower() + s[1:] if s else s


def _rationale(
    inst: Instrument, result: ScoreResult, horizon: Horizon,
    reason: tuple[str, str] | None, risk: tuple[str, str] | None, inval: tuple[str, str] | None,
) -> tuple[str, str]:
    """Weave the call into one flowing, plain-language paragraph (EN + KO)."""
    act_en, act_ko = _ACTION_PHRASE.get(result.action, ("a hold", "보유"))
    h_en = horizon.value.replace("_", "-to-")
    h_ko = _HORIZON_KO_PHRASE.get(horizon.value, horizon.value)
    sc, cf = result.total_score, result.confidence

    en = (f"We read {inst.name} as {act_en} on the {h_en} horizon — composite score "
          f"{sc:.0f}/100, {cf:.0f}% confidence. ")
    if reason:
        en += f"Above all, {_lower_first(reason[0])}. "
    if risk:
        en += f"That said, {_lower_first(risk[0])}. "
    if inval:
        en += f"We'd step back if {_lower_first(inval[0])}."

    # reason/risk/inval KO strings are already complete sentences; chain them with
    # light connectors so it reads as one flowing paragraph (no forced grammar).
    ko = f"{inst.name}은(는) {h_ko} 관점에서 '{act_ko}'로 봅니다. 종합 점수 {sc:.0f}/100, 신뢰도 {cf:.0f}%입니다. "
    if reason:
        ko += f"무엇보다 {reason[1]} "
    if risk:
        ko += f"다만 {risk[1]} "
    if inval:
        ko += inval[1]
    return en.strip(), ko.strip()


def _strip_dot(s: str) -> str:
    return s.rstrip(".")


def _price_is_corrupt(price: float | None, target_mean: float | None) -> bool:
    """True when the chart price is wildly out of line with the analyst consensus
    target (>3x either way) — a strong signal of corrupt source data (a bad Yahoo
    split-adjustment, e.g. a "$1,134 Micron" whose real target is ~$150). We then
    suppress the target band rather than anchor a fiction on it. When there is no
    analyst target we cannot cross-check, so we trust the price (best effort)."""
    if not price or not target_mean or target_mean <= 0:
        return False
    ratio = price / target_mean
    return ratio > 3.0 or ratio < 1.0 / 3.0


def _hotness(
    feat: FeatureSet, fund: FundamentalSnapshot | None, cms_score: float | None, total_score: float,
    *, spotlight: SpotlightEntry | None = None,
) -> float:
    """Attention/heat score 0–100: analyst coverage + estimate revisions + momentum + flows.

    Approximates how much news/analyst/desk attention a name is drawing right now,
    from the signals we can source keylessly (no per-ticker news feed exists). The
    curated house-spotlight ``heat`` (editorial, labelled) sets a FLOOR so a name
    drawing real-world buzz that the keyless signals miss — e.g. a turnaround like
    Intel — still surfaces in the HOT list."""
    h = 0.0
    if fund is not None:
        if fund.num_analysts:
            h += min(22.0, fund.num_analysts * 0.9)  # breadth of analyst coverage
        rev = (fund.eps_rev_up_30d or 0) + (fund.eps_rev_down_30d or 0)
        h += min(20.0, rev * 2.5)  # estimate-revision churn = desks actively re-rating
    r20 = feat.returns.get("r20")
    if r20 is not None:
        h += min(26.0, abs(r20) * 100.0 * 1.6)  # a big recent move is what makes headlines
    if cms_score is not None:
        h += min(20.0, cms_score * 0.2)  # capital actively migrating in
    h += min(12.0, abs(total_score - 50.0) * 0.25)  # a strong (non-neutral) call draws eyes
    if spotlight is not None and spotlight.heat > 0:
        # House-spotlight floor + a small additive nudge above it (keyless signals
        # can still push a spotlight name higher than the floor).
        h = max(h, spotlight.heat) + min(6.0, h * 0.05)
    return round(min(100.0, h), 1)


_BAND_BASE = {Horizon.SHORT: 0.025, Horizon.MEDIUM: 0.05, Horizon.MEDIUM_LONG: 0.085}


_BULLISH_ACTIONS = (RecAction.STRONG_BUY, RecAction.BUY, RecAction.ACCUMULATE)
_BEARISH_ACTIONS = (RecAction.REDUCE, RecAction.SELL, RecAction.AVOID)
_MIN_DRIFT_ANNUAL = 0.04  # ±4%/yr floor so the band direction matches the committed call


def _target_range(
    price: float | None, fund: FundamentalSnapshot | None, vol: float | None,
    total_score: float, horizon: Horizon, confidence: float, action: RecAction,
) -> tuple[float | None, float | None, str, str]:
    """A *narrow, usable* expected-price band over the horizon, assumptions shown.

    Center = current price shifted by the (clamped) analyst-consensus target scaled
    to the horizon plus a small score tilt. The ±band is horizon-based, only gently
    widened by *clamped* volatility and tightened by confidence, then HARD-CAPPED.

    The band is then RECONCILED with the committed action: a buy must imply a target
    above the current price (visible upside), a sell a target below it. If the
    analyst consensus points against our call, the model's own view sets the
    direction (honestly flagged) — so we never show "BUY, target below today's price".
    Returns (None, None, …) with no anchor — never a bare point target (invariant 4)."""
    if price is None or price <= 0:
        return None, None, "", ""
    days = _HORIZON_DAYS.get(horizon, 120)
    t = days / 252.0
    score_tilt_annual = (total_score - 50.0) / 50.0 * 0.12  # ±12%/yr at the score extremes
    # Use the analyst target only when it is sane vs the price (0.4×–2.5×); outside
    # that it is almost certainly stale/bad data (e.g. an unadjusted split) and would
    # corrupt the center, so fall back to the score-only drift.
    if fund is not None and fund.target_mean is not None and 0.4 * price <= fund.target_mean <= 2.5 * price:
        analyst_12m = max(-0.40, min(0.60, fund.target_mean / price - 1.0))  # clamp wild targets
        exp_annual = 0.65 * analyst_12m + 0.35 * score_tilt_annual
        anchor_en = f"analyst mean ${fund.target_mean:.0f}"
        anchor_ko = f"애널리스트 평균목표 ${fund.target_mean:.0f}"
    else:
        exp_annual = score_tilt_annual
        anchor_en = "score-implied drift (no analyst target)"
        anchor_ko = "점수 기반 추세(애널리스트 목표 없음)"
    # Reconcile direction with the committed action (which is itself price-aware via
    # the valuation upside). A buy implies upside; a sell implies downside.
    diverged = False
    if action in _BULLISH_ACTIONS:
        if exp_annual < _MIN_DRIFT_ANNUAL:
            diverged = exp_annual < 0  # only flag when analysts actually point DOWN
            exp_annual = _MIN_DRIFT_ANNUAL
    elif action in _BEARISH_ACTIONS:
        if exp_annual > -_MIN_DRIFT_ANNUAL:
            diverged = exp_annual > 0
            exp_annual = -_MIN_DRIFT_ANNUAL
    center = price * (1.0 + exp_annual * t)
    # Band: horizon base, gently scaled by clamped vol, tightened by confidence, capped.
    v = min(max(vol if vol is not None else 0.30, 0.15), 0.55)
    conf_tighten = 1.0 - 0.25 * (confidence / 100.0)  # high confidence → as tight as 0.75×
    # Deliberately tight: a usable, committal range beats a "technically correct" but
    # meaningless wide one (the disclaimer covers the misses). Floor ±2%, HARD CAP ±10%
    # — even a very high-volatility name stays decisive.
    half_frac = max(0.02, min(0.10, _BAND_BASE.get(horizon, 0.05) * (v / 0.30) * conf_tighten))
    half = center * half_frac
    low = round(max(price * 0.55, center - half), 2)
    high = round(center + half, 2)
    # Hard guarantee: the printed band must not contradict the action.
    if action in _BULLISH_ACTIONS and high <= price:
        high = round(price * (1.0 + half_frac), 2)
    elif action in _BEARISH_ACTIONS and low >= price:
        low = round(price * (1.0 - half_frac), 2)
    note_en = " (model view diverges from analyst consensus)" if diverged else ""
    note_ko = " (모델 판단이 애널리스트 컨센서스와 다름)" if diverged else ""
    basis_en = (f"Base ${price:.2f}; {anchor_en} scaled to {days}d + score tilt → center "
                f"${center:.2f}; ±{half_frac * 100:.0f}% band (vol- & confidence-adjusted){note_en}.")
    basis_ko = (f"기준가 ${price:.2f}; {anchor_ko}를 {days}일로 환산 + 점수 반영 → 중심 "
                f"${center:.2f}; ±{half_frac * 100:.0f}% 밴드(변동성·신뢰도 반영){note_ko}.")
    return low, high, basis_en, basis_ko


def _moonshot(
    feat: FeatureSet, fund: FundamentalSnapshot | None, cms_score: float | None,
    *, spotlight: SpotlightEntry | None = None,
) -> float:
    """Visionary 'big bet' score: explosive future-growth potential while still
    cheap / out of favour now. Deliberately ignores momentum & technical strength
    (the opposite of the hotness score) — this is the prophet, not the trend.

    The curated house-spotlight ``conviction`` (editorial, labelled) sets a FLOOR,
    amplified by how far the name sits below its highs, so a genuine "next big
    thing" with thin keyless fundamentals (a fresh spin-off, a pre-revenue
    disruptor) still surfaces as a Big Bet instead of scoring ~0."""
    growth = 0.0
    if fund is not None:
        if fund.revenue_growth is not None:
            growth += min(35.0, max(0.0, fund.revenue_growth * 100.0) * 1.1)  # top-line growth
        rev_up = (fund.eps_rev_up_30d or 0) - (fund.eps_rev_down_30d or 0)
        growth += min(12.0, max(0, rev_up) * 1.5)  # estimates turning up
        if fund.profit_margin is not None and fund.profit_margin > 0.15:
            growth += 5.0  # quality of the growth
    if cms_score is not None:
        growth += min(33.0, cms_score * 0.33)  # capital migrating into the theme = the future

    dist = feat.distance_from_52w_high  # negative = below the 52-week high
    drawdown = abs(min(0.0, dist)) if dist is not None else 0.0  # 0 … ~0.6
    if growth < 12.0:  # no real growth story → not a moonshot, just possibly cheap
        base = growth * 0.4
    else:
        # "지금은 가격이 낮지만" is the whole point, so cheapness MULTIPLIES the growth:
        # a beaten-down high-growth name scores far above a high-growth one near its
        # highs (which is just a momentum darling, not a value-disguised moonshot).
        cheap_mult = 0.40 + min(0.85, drawdown * 2.1)  # −20% → ~0.82, −40%+ → ~1.25
        if feat.above_ma200 is False:
            cheap_mult += 0.10  # out of the momentum crowd
        base = growth * min(1.30, cheap_mult)

    if spotlight is not None and spotlight.conviction > 0:
        # House conviction floor; still-cheap names (further below the high) get
        # amplified, so the desk's value-disguised picks rise to the top.
        conv = spotlight.conviction * (0.85 + min(0.45, drawdown * 1.4))
        base = max(base, conv)
    return round(min(100.0, base), 1)
