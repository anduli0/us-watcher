"""Market analysis service — fetch → deterministic features → regime → DTOs.

This is the orchestration seam between the providers and the API. All numbers
are computed by the deterministic analytics engine; this layer only fetches,
assembles, and writes plain-language interpretations off the computed values
(never invented). A small async TTL cache keeps us within Yahoo's keyless rate
limits across the overview/index/rotation surfaces.
"""

from __future__ import annotations

import asyncio
import time

from us_watcher.domain.analytics.features import FeatureSet, build_features
from us_watcher.domain.analytics.indicators import relative_strength, simple_return
from us_watcher.domain.analytics.series import closes
from us_watcher.domain.enums import DataQuality, DataStatus, RotationQuadrant
from us_watcher.domain.regime.derive import derive_components
from us_watcher.domain.regime.score import RegimeResult, compute_regime
from us_watcher.domain.time import now_utc, session_status, upcoming_session
from us_watcher.domain.universe import Instrument, Universe, get_universe
from us_watcher.infrastructure.macro.fred import FredProvider, MacroObservation
from us_watcher.infrastructure.marketdata.base import AggregateSeries
from us_watcher.infrastructure.marketdata.factory import get_provider
from us_watcher.logging_config import get_logger
from us_watcher.market.narrative import _COMPONENT_LABELS, build_regime_narrative
from us_watcher.market.schemas import (
    IndexWatcherResponse,
    MarketCard,
    MarketDriver,
    Metric,
    NextSession,
    OverviewResponse,
    RegimePulse,
    RotationResponse,
    SectorRow,
    StyleRow,
)

log = get_logger(__name__)

_CARD_LOOKBACKS = {"1w": 5, "1m": 21, "3m": 63}


class _TTLCache:
    """TTL cache that also retains the last known-good value per key.

    ``get`` returns a fresh value (within TTL) or ``_MISS``. ``last_good``
    returns the most recent non-``None`` value ever stored (no TTL), so the
    service can degrade gracefully to slightly-stale data instead of blanking
    the page when a live fetch is slow or fails — the difference between a
    momentary provider hiccup showing yesterday's close vs. "Data unavailable".
    """

    def __init__(self, ttl_seconds: float = 90.0) -> None:
        self._ttl = ttl_seconds
        self._fresh: dict[str, tuple[float, AggregateSeries | None]] = {}
        self._good: dict[str, AggregateSeries] = {}

    def get(self, key: str) -> AggregateSeries | None | object:
        hit = self._fresh.get(key)
        if hit is None:
            return _MISS
        ts, val = hit
        if time.monotonic() - ts > self._ttl:
            return _MISS
        return val

    def last_good(self, key: str) -> AggregateSeries | object:
        return self._good.get(key, _MISS)

    def put(self, key: str, val: AggregateSeries | None) -> None:
        self._fresh[key] = (time.monotonic(), val)
        if val is not None:
            self._good[key] = val


_MISS = object()


class MarketService:
    # The overview is the homepage surface and is read on every page load (plus
    # by the briefing and orchestrator). Live-fetching ~11 Yahoo symbols + FRED
    # on each request made it slow and occasionally hang under provider
    # throttling. We serve a cached snapshot instead and refresh it in the
    # background (stale-while-revalidate): the first load builds it once, every
    # subsequent request returns instantly, and the data is never more than
    # ``_OVERVIEW_TTL`` seconds stale.
    _OVERVIEW_TTL = 60.0

    def __init__(self) -> None:
        self._provider = get_provider()
        self._fred = FredProvider()
        self._cache = _TTLCache()
        self._universe = get_universe()
        self._overview_snap: tuple[float, OverviewResponse] | None = None
        self._overview_lock = asyncio.Lock()
        self._overview_refreshing = False
        self._refresh_task: asyncio.Task[None] | None = None

    # --- low-level fetch (cached, parallel) ---
    async def _aggregates(self, instrument: Instrument) -> AggregateSeries | None:
        if not instrument.yahoo_symbol:
            return None
        key = instrument.yahoo_symbol
        cached = self._cache.get(key)
        if cached is not _MISS:
            if cached is not None:
                return cached  # type: ignore[return-value]
            # Fresh negative (a recent failure cached for the TTL window): don't
            # hammer the provider — fall back to the last known-good series.
            good = self._cache.last_good(key)
            return good if good is not _MISS else None  # type: ignore[return-value]
        series = await self._provider.get_aggregates(instrument.yahoo_symbol)
        self._cache.put(key, series)
        if series is None:
            good = self._cache.last_good(key)
            if good is not _MISS:
                return good  # type: ignore[return-value]
        return series

    async def _fetch_many(self, instruments: list[Instrument]) -> dict[str, AggregateSeries | None]:
        # Bound concurrency: firing ~190 simultaneous Yahoo requests both exhausts
        # local sockets (the larger universe could crash the worker) and trips the
        # keyless endpoint's rate limit, silently degrading symbols to MOCK. 10 is a
        # safe, polite ceiling. (No retry — a retry storm of new TLS clients spikes CPU.)
        sem = asyncio.Semaphore(10)

        async def one(inst: Instrument) -> AggregateSeries | None:
            async with sem:
                return await self._aggregates(inst)

        results = await asyncio.gather(*(one(i) for i in instruments))
        return {inst.symbol: res for inst, res in zip(instruments, results, strict=True)}

    def _features(self, instrument: Instrument | None, series: AggregateSeries | None) -> FeatureSet | None:
        if instrument is None or series is None or not series.bars:
            return None
        return build_features(instrument.symbol, series.bars, series.as_of)

    # --- card construction ---
    def _card(self, inst: Instrument, series: AggregateSeries | None) -> MarketCard:
        if series is None or len(series.bars) < 2:
            return MarketCard(
                symbol=inst.symbol, name=inst.name, group=inst.group, last=None,
                change_1d_pct=None, change_1w_pct=None, change_1m_pct=None, change_3m_pct=None,
                trend="na", status=DataStatus.UNAVAILABLE, source="none", as_of=None,
                is_proxy=inst.is_proxy,
                interpretation_en="Data unavailable.", interpretation_ko="데이터 없음.",
            )
        cs = closes(series.bars)
        last = cs[-1]
        c1d = simple_return(cs, 1)
        changes = {k: simple_return(cs, lb) for k, lb in _CARD_LOOKBACKS.items()}
        trend = "up" if (c1d or 0) > 0.0005 else "down" if (c1d or 0) < -0.0005 else "flat"
        en, ko = _interpret_card(inst, last, c1d, changes.get("1m"))
        return MarketCard(
            symbol=inst.symbol, name=inst.name, group=inst.group, last=round(last, 4),
            change_1d_pct=_pct(c1d), change_1w_pct=_pct(changes["1w"]),
            change_1m_pct=_pct(changes["1m"]), change_3m_pct=_pct(changes["3m"]),
            trend=trend, status=series.status, source=series.source, as_of=series.as_of,
            is_proxy=inst.is_proxy, interpretation_en=en, interpretation_ko=ko,
        )

    # --- public surfaces ---
    async def build_overview(self) -> OverviewResponse:
        """Return the market overview from a cached snapshot (stale-while-revalidate).

        Fast path: a fresh snapshot is returned immediately. A stale snapshot is
        still returned immediately while a background refresh is kicked off. Only
        the very first call (cold cache) blocks on the live build, serialized by
        a lock so concurrent first-loads don't stampede the providers.
        """
        snap = self._overview_snap
        if snap is not None:
            built_at, ov = snap
            if time.monotonic() - built_at > self._OVERVIEW_TTL:
                self._schedule_overview_refresh()
            return ov
        async with self._overview_lock:
            if self._overview_snap is not None:  # built by another waiter
                return self._overview_snap[1]
            ov = await self._build_overview_live()
            self._overview_snap = (time.monotonic(), ov)
            return ov

    def _schedule_overview_refresh(self) -> None:
        if self._overview_refreshing:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._overview_refreshing = True

        async def _refresh() -> None:
            try:
                ov = await self._build_overview_live()
                self._overview_snap = (time.monotonic(), ov)
            except Exception as exc:  # keep the previous good snapshot on failure
                log.warning("overview.refresh_failed", error=str(exc))
            finally:
                self._overview_refreshing = False

        self._refresh_task = loop.create_task(_refresh())

    async def prewarm(self) -> None:
        """Build the overview snapshot ahead of the first request (startup hook)."""
        try:
            await self.build_overview()
        except Exception as exc:  # best-effort; the request path will retry
            log.warning("overview.prewarm_failed", error=str(exc))

    async def _build_overview_live(self) -> OverviewResponse:
        u = self._universe
        card_instruments = [
            *[i for i in u.indices],
            *[i for i in u.cross_assets if i.yahoo_symbol],
        ]
        # Equities (Yahoo) and yields (FRED) are independent fetches — run them
        # concurrently so the overview is bounded by the slower of the two
        # providers, not their sum.
        agg, yields = await asyncio.gather(
            self._fetch_many(card_instruments + _pick(u.etfs_core, ("SPY", "RSP"))),
            self._fred.get_many(["DGS2", "DGS10", "T10Y2Y"]),
        )
        cards = [self._card(i, agg.get(i.symbol)) for i in card_instruments]

        # yields from FRED (level cards; changes shown as unavailable honestly)
        for sym, sid in (("US2Y", "DGS2"), ("US10Y", "DGS10"), ("T10Y2Y", "T10Y2Y")):
            inst = u.by_symbol(sym)
            obs = yields.get(sid)
            if inst is not None:
                cards.append(_yield_card(inst, obs))

        pulse = self._regime_pulse(u, agg, yields)
        drivers = _rank_drivers(cards, pulse)
        statuses = [c.status for c in cards]
        dq = _roll_up_quality(statuses)
        notes = _data_notes(cards)
        status = session_status()
        return OverviewResponse(
            as_of=now_utc(), session=status, data_quality=dq.value,
            pulse=pulse, cards=cards, drivers=drivers, notes=notes,
            next_session=_next_session_dto(status),
        )

    def _regime_pulse(
        self, u: Universe, agg: dict[str, AggregateSeries | None], yields: dict[str, MacroObservation]
    ) -> RegimePulse:
        spx = self._features(u.by_symbol("SPX"), agg.get("SPX"))
        spy = self._features(u.by_symbol("SPY"), agg.get("SPY"))
        rsp = self._features(u.by_symbol("RSP"), agg.get("RSP"))
        dxy = self._features(u.by_symbol("DXY"), agg.get("DXY"))
        vix_series = agg.get("VIX")
        vix_level = closes(vix_series.bars)[-1] if vix_series and vix_series.bars else None
        curve_obs = yields.get("T10Y2Y")
        curve = curve_obs.value if curve_obs else None
        dollar_r20 = dxy.returns.get("r20") if dxy else None

        components, gap = derive_components(
            index=spx or spy,
            cap_weight=spy,
            equal_weight=rsp,
            vix_level=vix_level,
            yield_curve_2s10s=curve,
            dollar_ret_20=dollar_r20,
        )
        result = compute_regime(
            components, cap_minus_equal_weight=gap, vix_level=vix_level
        )
        diag_en, diag_ko = _regime_diagnosis(result, gap, vix_level)
        narrative = build_regime_narrative(
            result, gap=gap, vix_level=vix_level, spx=spx or spy,
            dollar_ret20=dollar_r20, curve=curve,
        )
        return RegimePulse(
            score=result.score, regime=result.regime, regime_ko=result.regime_ko,
            regime_en=result.regime_en, confidence=result.confidence, coverage=result.coverage,
            available=result.available, unavailable=result.unavailable,
            diagnosis_en=diag_en, diagnosis_ko=diag_ko, narrative=narrative,
        )

    async def build_index_watcher(self, market: str) -> IndexWatcherResponse:
        u = self._universe
        market = market.upper()
        index_map = {"SP500": "SPX", "NASDAQ": "NDX", "DOW": "DJI", "NYSE": "NYA"}
        idx_symbol = index_map.get(market, "SPX")
        related = {
            "SP500": ["SPX", "SPY", "RSP"],
            "NASDAQ": ["NDX", "IXIC", "QQQ", "SMH"],
            "DOW": ["DJI", "DIA"],
            "NYSE": ["NYA", "RSP", "IWM"],
        }.get(market, ["SPX", "SPY"])
        insts = [u.by_symbol(s) for s in related if u.by_symbol(s)]
        agg = await self._fetch_many([i for i in insts if i])
        cards = [self._card(i, agg.get(i.symbol)) for i in insts if i]
        idx_feat = self._features(u.by_symbol(idx_symbol), agg.get(idx_symbol))
        metrics = _index_metrics(idx_feat)
        # breadth via cap vs equal weight when both present
        diag_en, diag_ko = _index_diagnosis(market, idx_feat, agg, u, self)
        return IndexWatcherResponse(
            market=market, name=_market_name(market), as_of=now_utc(),
            cards=cards, metrics=metrics, diagnosis_en=diag_en, diagnosis_ko=diag_ko,
            notes=_data_notes(cards),
        )

    async def build_rotation(self) -> RotationResponse:
        u = self._universe
        sectors = u.sectors
        styles = u.styles
        bench_inst = u.by_symbol("SPY")
        agg = await self._fetch_many([*sectors, *styles, bench_inst] if bench_inst else [*sectors, *styles])
        bench_bars = agg.get("SPY")
        bench_closes = closes(bench_bars.bars) if bench_bars and bench_bars.bars else []

        rows: list[SectorRow] = []
        for s in sectors:
            series = agg.get(s.symbol)
            rows.append(_sector_row(s, series, bench_closes))
        rows.sort(key=lambda r: (r.rel_strength_1m if r.rel_strength_1m is not None else -99), reverse=True)

        style_rows = _style_rows(styles, agg, bench_closes)
        diag_en, diag_ko = _rotation_diagnosis(rows)
        return RotationResponse(
            as_of=now_utc(), benchmark="SPY", sectors=rows, style_leadership=style_rows,
            diagnosis_en=diag_en, diagnosis_ko=diag_ko, notes=[],
        )


# ---------------- module-level helpers (pure) ----------------

def _next_session_dto(status: str) -> NextSession:
    """Forward-looking next-session descriptor for the overview header.

    When the market is closed (after-hours / weekend / holiday) ``is_forecast``
    is true and the UI frames the page as a forecast for this session. On a
    Korean weekend this resolves to the upcoming Monday open.
    """
    us = upcoming_session()
    m, d = us.open_et.month, us.open_et.day
    km, kd = us.open_kst.month, us.open_kst.day
    khm = f"{us.open_kst.hour:02d}:{us.open_kst.minute:02d}"
    label_en = (
        f"Next U.S. session: {us.weekday_en} {m}/{d} — opens 9:30 AM ET "
        f"({khm} KST {km}/{kd})."
    )
    label_ko = (
        f"다음 미국 정규장: {us.weekday_ko} {m}/{d} — 한국시각 {km}/{kd} {khm} 개장."
    )
    return NextSession(
        session_date=us.session_date.isoformat(),
        open_et=us.open_et, open_kst=us.open_kst,
        is_today=us.is_today, is_forecast=status != "open",
        weekday_en=us.weekday_en, weekday_ko=us.weekday_ko,
        label_en=label_en, label_ko=label_ko,
    )


def _pct(x: float | None) -> float | None:
    return round(x * 100.0, 2) if x is not None else None


def _pick(insts: list[Instrument], symbols: tuple[str, ...]) -> list[Instrument]:
    return [i for i in insts if i.symbol in symbols]


def _market_name(market: str) -> str:
    return {
        "SP500": "S&P 500 Watcher", "NASDAQ": "Nasdaq Watcher",
        "DOW": "Dow Jones Watcher", "NYSE": "NYSE Watcher",
    }.get(market, market)


def _roll_up_quality(statuses: list[DataStatus]) -> DataQuality:
    if not statuses:
        return DataQuality.STALE
    live = {DataStatus.REAL_TIME, DataStatus.DELAYED, DataStatus.END_OF_DAY}
    bad = {DataStatus.MOCK, DataStatus.UNAVAILABLE, DataStatus.STALE}
    n_bad = sum(1 for s in statuses if s in bad)
    n_live = sum(1 for s in statuses if s in live)
    if n_bad == 0:
        return DataQuality.FRESH
    if n_live >= n_bad:
        return DataQuality.MIXED
    return DataQuality.STALE


def _data_notes(cards: list[MarketCard]) -> list[str]:
    notes: list[str] = []
    mock = [c.symbol for c in cards if c.status == DataStatus.MOCK]
    proxy = [c.symbol for c in cards if c.is_proxy]
    unavail = [c.symbol for c in cards if c.status == DataStatus.UNAVAILABLE]
    if mock:
        notes.append(f"MOCK data (labelled, not live): {', '.join(mock)}")
    if proxy:
        notes.append(f"Proxy series in use: {', '.join(proxy)}")
    if unavail:
        notes.append(f"Unavailable: {', '.join(unavail)}")
    return notes


def _interpret_card(inst: Instrument, last: float, c1d: float | None, c1m: float | None) -> tuple[str, str]:
    d = (c1d or 0) * 100
    m = (c1m or 0) * 100
    arrow = "rose" if d > 0 else "fell" if d < 0 else "was flat"
    arrow_ko = "상승" if d > 0 else "하락" if d < 0 else "보합"
    mtrend = "up" if m > 0.5 else "down" if m < -0.5 else "roughly flat"
    mtrend_ko = "상승세" if m > 0.5 else "하락세" if m < -0.5 else "횡보"
    if inst.symbol == "VIX":
        if last >= 20:
            imp, imp_ko = ("elevated — hedging demand is high, a headwind for risk assets",
                           "높음 — 헤지 수요가 커 위험자산엔 부담")
        elif last <= 15:
            imp, imp_ko = ("calm — low hedging demand, supportive for risk assets",
                           "안정 — 헤지 수요가 낮아 위험자산에 우호적")
        else:
            imp, imp_ko = ("moderate", "보통")
        return (f"Volatility {imp} (VIX {last:.1f}).", f"변동성 {imp_ko} (VIX {last:.1f}).")
    return (
        f"{inst.name} {arrow} {abs(d):.2f}% today; over the past month it is {mtrend} ({m:+.1f}%).",
        f"{inst.name} 오늘 {abs(d):.2f}% {arrow_ko} · 최근 1개월은 {mtrend_ko}({m:+.1f}%)입니다.",
    )


def _yield_card(inst: Instrument, obs: MacroObservation | None) -> MarketCard:
    if obs is None:
        return MarketCard(
            symbol=inst.symbol, name=inst.name, group="rates", last=None,
            change_1d_pct=None, change_1w_pct=None, change_1m_pct=None, change_3m_pct=None,
            trend="na", status=DataStatus.UNAVAILABLE, source="fred", as_of=None,
            interpretation_en="Yield unavailable.", interpretation_ko="금리 데이터 없음.",
        )
    val = obs.value
    en = f"{inst.name}: {val:.2f}% (as of {obs.observation_date})."
    ko = f"{inst.name}: {val:.2f}% ({obs.observation_date} 기준)."
    if inst.symbol == "T10Y2Y":
        shape = "inverted" if val < 0 else "flat" if val < 0.2 else "positively sloped"
        shape_ko = "역전" if val < 0 else "평탄" if val < 0.2 else "정상(우상향)"
        en = f"10Y–2Y spread {val:+.2f}pp — curve {shape}."
        ko = f"10년–2년 스프레드 {val:+.2f}%p — 수익률곡선 {shape_ko}."
    return MarketCard(
        symbol=inst.symbol, name=inst.name, group="rates",
        last=round(val, 2), change_1d_pct=None, change_1w_pct=None,
        change_1m_pct=None, change_3m_pct=None, trend="na",
        status=DataStatus.END_OF_DAY, source="fred",
        as_of=obs.available_at, interpretation_en=en, interpretation_ko=ko,
    )


def _rank_drivers(cards: list[MarketCard], pulse: RegimePulse) -> list[MarketDriver]:
    drivers: list[MarketDriver] = []
    by = {c.symbol: c for c in cards}

    def add(name: str, name_ko: str, direction: str, conf: float, ev_en: str, ev_ko: str) -> None:
        drivers.append(MarketDriver(
            name=name, name_ko=name_ko, direction=direction, rank=0,
            confidence=conf, evidence_en=ev_en, evidence_ko=ev_ko))

    vix = by.get("VIX")
    if vix and vix.last is not None:
        sup = vix.last < 18
        why = ("calm; low hedging demand supports risk appetite" if sup
               else "elevated; rising hedging demand is a risk headwind")
        why_ko = "안정적이라 위험선호에 우호적" if sup else "높아 위험자산에 부담"
        add("Volatility", "변동성", "supportive" if sup else "headwind", 70,
            f"VIX {vix.last:.1f} — {why}.", f"VIX {vix.last:.1f} — {why_ko}.")
    spx = by.get("SPX") or by.get("NDX")
    if spx and spx.change_1m_pct is not None:
        sup = spx.change_1m_pct > 0
        why = "uptrend intact" if sup else "momentum fading"
        why_ko = "상승 추세 유지" if sup else "모멘텀 둔화"
        add("Index trend", "지수 추세", "supportive" if sup else "headwind", 65,
            f"S&P 1-month {spx.change_1m_pct:+.1f}% — {why}.",
            f"S&P 1개월 {spx.change_1m_pct:+.1f}% — {why_ko}.")
    curve = by.get("T10Y2Y")
    if curve and curve.last is not None:
        sup = curve.last > 0
        why = "positively sloped (normal)" if sup else "inverted, a late-cycle caution"
        why_ko = "정상(우상향)" if sup else "역전, 경기후반 경계"
        add("Yield curve", "수익률곡선", "supportive" if sup else "headwind", 60,
            f"10Y–2Y {curve.last:+.2f}pp — {why}.", f"10–2년 {curve.last:+.2f}%p — {why_ko}.")
    dxy = by.get("DXY")
    if dxy and dxy.change_1m_pct is not None:
        sup = dxy.change_1m_pct < 0
        why = "easing, a tailwind for equities" if sup else "firming, a headwind for equities"
        why_ko = "약세라 증시에 우호적" if sup else "강세라 증시에 부담"
        add("US dollar", "달러", "supportive" if sup else "headwind", 55,
            f"DXY 1-month {dxy.change_1m_pct:+.1f}% — {why}.",
            f"달러지수 1개월 {dxy.change_1m_pct:+.1f}% — {why_ko}.")
    drivers.sort(key=lambda d: d.confidence, reverse=True)
    for i, d in enumerate(drivers):
        d.rank = i + 1
    return drivers[:6]


def _regime_diagnosis(result: RegimeResult, gap: float | None, vix: float | None) -> tuple[str, str]:
    parts_en = [f"Overall market-state score {result.score:+.0f}/100 → {result.regime_en} "
                f"(confidence {result.confidence:.0f}%, {len(result.available)} components measured)."]
    parts_ko = [f"종합 점수 {result.score:+.0f}/100 → {result.regime_ko} 국면 "
                f"(신뢰도 {result.confidence:.0f}%, {len(result.available)}개 항목 측정)."]
    if gap is not None and gap >= 0.02:
        parts_en.append("Cap-weight is outpacing equal-weight — advance is narrow / mega-cap-led.")
        parts_ko.append("시총가중이 동일가중을 앞서 — 상승이 대형주 중심으로 좁습니다.")
    if vix is not None and vix >= 20:
        parts_en.append(f"VIX {vix:.1f} signals elevated risk.")
        parts_ko.append(f"VIX {vix:.1f}로 위험 경계.")
    if result.unavailable:
        miss_en = ", ".join(_COMPONENT_LABELS.get(n, (n, n))[0] for n in result.unavailable)
        miss_ko = ", ".join(_COMPONENT_LABELS.get(n, (n, n))[1] for n in result.unavailable)
        parts_en.append(f"Unmeasured: {miss_en} (reweighted out).")
        parts_ko.append(f"미측정: {miss_ko} (가중치 제외).")
    return " ".join(parts_en), " ".join(parts_ko)


def _index_metrics(feat: FeatureSet | None) -> list[Metric]:
    if feat is None:
        return [Metric(key="na", label_en="Data", label_ko="데이터", value=None,
                       status=DataStatus.UNAVAILABLE, hint_en="No data.", hint_ko="데이터 없음.")]
    m: list[Metric] = []

    def add(key: str, en: str, ko: str, val: float | None, unit: str = "",
            hint_en: str = "", hint_ko: str = "") -> None:
        m.append(Metric(key=key, label_en=en, label_ko=ko, value=val, unit=unit,
                        status=DataStatus.END_OF_DAY if val is not None else DataStatus.UNAVAILABLE,
                        hint_en=hint_en, hint_ko=hint_ko))

    add("r20", "1-month return", "1개월 수익률", _pct(feat.returns.get("r20")), "%")
    add("r60", "3-month return", "3개월 수익률", _pct(feat.returns.get("r60")), "%")
    add("r252", "1-year return", "1년 수익률", _pct(feat.returns.get("r252")), "%")
    add("rsi14", "RSI(14)", "RSI(14)", round(feat.rsi14, 1) if feat.rsi14 else None, "",
        "Above 70 overbought, below 30 oversold.", "70 이상 과매수, 30 이하 과매도.")
    add("vol20", "Realized vol (20d, ann.)", "실현변동성(20일, 연율)",
        round(feat.realized_vol_20 * 100, 1) if feat.realized_vol_20 else None, "%")
    add("dd", "Distance from 52w high", "52주 고점 대비", _pct(feat.distance_from_52w_high), "%")
    add("mdd", "Max drawdown (2y)", "최대낙폭(2년)", _pct(feat.max_drawdown), "%")
    return m


def _index_diagnosis(
    market: str,
    idx_feat: FeatureSet | None,
    agg: dict[str, AggregateSeries | None],
    u: Universe,
    svc: MarketService,
) -> tuple[str, str]:
    if idx_feat is None:
        return ("Index data unavailable.", "지수 데이터 없음.")
    name = _market_name(market)
    r1m, r3m = _pct(idx_feat.returns.get("r20")), _pct(idx_feat.returns.get("r60"))
    rsi = idx_feat.rsi14
    dist = idx_feat.distance_from_52w_high

    if idx_feat.above_ma200:
        trend_en = "above its 200-day moving average, so the primary trend is still up"
        trend_ko = "200일 이동평균선 위에 있어 1차 추세는 상승입니다"
    else:
        trend_en = "below its 200-day moving average, so the primary trend has turned down"
        trend_ko = "200일 이동평균선 아래에 있어 1차 추세는 하락으로 돌아섰습니다"
    en = f"{name}: the index is {trend_en}. Momentum is {r1m}% over 1 month and {r3m}% over 3 months"
    ko = f"{name}: 지수는 {trend_ko}. 모멘텀은 1개월 {r1m}%, 3개월 {r3m}%"
    if rsi is not None:
        if rsi >= 70:
            en += f", and RSI {rsi:.0f} is overbought (>70) — stretched, prone to a pause."
            ko += f", RSI {rsi:.0f}는 과매수(70 초과)로 단기 과열·숨고르기 가능성이 있습니다."
        elif rsi <= 30:
            en += f", and RSI {rsi:.0f} is oversold (<30) — washed out, prone to a bounce."
            ko += f", RSI {rsi:.0f}는 과매도(30 미만)로 낙폭과대·반등 여지가 있습니다."
        else:
            en += f", with RSI {rsi:.0f} in a neutral range."
            ko += f", RSI {rsi:.0f}는 중립 구간입니다."
    else:
        en += "."
        ko += "."
    if dist is not None:
        d = dist * 100
        if d <= -0.1:
            en += f" It sits {abs(d):.1f}% below its 52-week high."
            ko += f" 현재가는 52주 고점 대비 {abs(d):.1f}% 아래입니다."
        else:
            en += " It is sitting at/near its 52-week high."
            ko += " 현재가는 52주 고점 부근입니다."
    en += " The 200-day line is the key level to watch — losing it would flip the primary trend."
    ko += " 200일선이 핵심 분기점으로, 이 선을 내주면 1차 추세가 전환됩니다."
    if market == "SP500":
        spy = svc._features(u.by_symbol("SPY"), agg.get("SPY"))
        rsp = svc._features(u.by_symbol("RSP"), agg.get("RSP"))
        if spy and rsp:
            cw, ew = spy.returns.get("r20"), rsp.returns.get("r20")
            if cw is not None and ew is not None:
                if cw - ew > 0.02:
                    en += " Cap-weight (SPY) is outrunning equal-weight (RSP): advance is concentrated."
                    ko += " 시총가중(SPY)이 동일가중(RSP)을 앞섬: 상승이 집중적입니다."
                else:
                    en += " Equal-weight (RSP) is keeping pace: participation is broad."
                    ko += " 동일가중(RSP)이 보조를 맞춤: 참여가 광범위합니다."
    if market == "DOW":
        en += " Note: the Dow is price-weighted — high-priced members drive the index, not market cap."
        ko += " 참고: 다우는 가격가중 — 고가 종목이 지수를 좌우하며 시가총액이 아닙니다."
    if market == "NYSE":
        en += " NYSE breadth proxied via equal-weight and small-cap participation (composite breadth not keyless)."
        ko += " NYSE 폭은 동일가중·소형주 참여로 프록시(컴포짓 폭 지표는 키리스 미제공)."
    return en, ko


def _sector_row(s: Instrument, series: AggregateSeries | None, bench_closes: list[float]) -> SectorRow:
    if series is None or not series.bars:
        return SectorRow(symbol=s.symbol, name=s.name, gics=s.gics or s.name,
                         ret_1w=None, ret_1m=None, ret_3m=None, ret_6m=None,
                         rel_strength_1m=None, quadrant=RotationQuadrant.LAGGING,
                         status=DataStatus.UNAVAILABLE, as_of=None)
    cs = closes(series.bars)
    r1w, r1m = simple_return(cs, 5), simple_return(cs, 21)
    r3m, r6m = simple_return(cs, 63), simple_return(cs, 126)
    rs1m = relative_strength(cs, bench_closes, 21) if bench_closes else None
    rs3m = relative_strength(cs, bench_closes, 63) if bench_closes else None
    quadrant = _quadrant(rs1m, rs3m)
    return SectorRow(
        symbol=s.symbol, name=s.name, gics=s.gics or s.name,
        ret_1w=_pct(r1w), ret_1m=_pct(r1m), ret_3m=_pct(r3m), ret_6m=_pct(r6m),
        rel_strength_1m=_pct(rs1m), quadrant=quadrant, status=series.status, as_of=series.as_of,
    )


def _quadrant(rs_short: float | None, rs_long: float | None, band: float = 0.005) -> RotationQuadrant:
    """RRG-style quadrant.

    ``level`` = recent (1-month) relative strength vs the benchmark; ``momentum``
    = how that relative strength has changed vs the 3-month window. A small
    deadband around zero avoids flip-flopping on noise.

    LEADING   = relatively strong AND still improving
    WEAKENING = relatively strong BUT losing momentum
    IMPROVING = relatively weak BUT gaining momentum
    LAGGING   = relatively weak AND still deteriorating
    """
    level = rs_short if rs_short is not None else 0.0
    prior = rs_long if rs_long is not None else 0.0
    momentum = level - prior
    strong = level > band
    rising = momentum >= -band
    if strong and rising:
        return RotationQuadrant.LEADING
    if strong and not rising:
        return RotationQuadrant.WEAKENING
    if not strong and rising:
        return RotationQuadrant.IMPROVING
    return RotationQuadrant.LAGGING


def _style_rows(
    styles: list[Instrument], agg: dict[str, AggregateSeries | None], bench_closes: list[float]
) -> list[StyleRow]:
    rows: list[StyleRow] = []
    for st in styles:
        series = agg.get(st.symbol)
        if series is None or not series.bars:
            rows.append(StyleRow(style=st.style or st.symbol, symbol=st.symbol, name=st.name,
                                 ret_1m=None, rel_strength_1m=None, leading=False))
            continue
        cs = closes(series.bars)
        r1m = simple_return(cs, 21)
        rs = relative_strength(cs, bench_closes, 21) if bench_closes else None
        rows.append(StyleRow(style=st.style or st.symbol, symbol=st.symbol, name=st.name,
                             ret_1m=_pct(r1m), rel_strength_1m=_pct(rs), leading=(rs or 0) > 0))
    rows.sort(key=lambda r: (r.rel_strength_1m if r.rel_strength_1m is not None else -99), reverse=True)
    return rows


_DEFENSIVE_KEYWORDS = ("utilit", "staple", "health", "real estate")


def _is_defensive(name: str) -> bool:
    low = name.lower()
    return any(k in low for k in _DEFENSIVE_KEYWORDS)


def _rotation_diagnosis(rows: list[SectorRow]) -> tuple[str, str]:
    def names(q: RotationQuadrant) -> list[str]:
        return [r.name for r in rows if r.quadrant == q][:3]

    leading, weakening = names(RotationQuadrant.LEADING), names(RotationQuadrant.WEAKENING)
    improving, lagging = names(RotationQuadrant.IMPROVING), names(RotationQuadrant.LAGGING)
    top = rows[0].name if rows else "n/a"
    bottom = rows[-1].name if rows else "n/a"
    # Plain-language framing of the quadrants up front, then the lists.
    en = (
        "Sectors are placed by relative strength vs. the S&P 500 and whether that strength is "
        "rising. 'Leading' = strong and still improving; 'improving' = weak but turning up; "
        "'weakening' = strong but fading; 'lagging' = weak and still sliding. "
        f"Leading: {', '.join(leading) or '—'}; improving: {', '.join(improving) or '—'}; "
        f"weakening: {', '.join(weakening) or '—'}; lagging: {', '.join(lagging) or '—'}. "
        f"Strongest 1-month relative is {top}; weakest is {bottom}."
    )
    ko = (
        "섹터는 S&P 500 대비 상대강도와 그 강도의 개선 여부로 분류합니다. '주도'=강하고 더 개선, "
        "'개선'=약하지만 반등, '약화'=강하나 둔화, '부진'=약하고 계속 하락. "
        f"주도: {', '.join(leading) or '—'}; 개선: {', '.join(improving) or '—'}; "
        f"약화: {', '.join(weakening) or '—'}; 부진: {', '.join(lagging) or '—'}. "
        f"1개월 상대강도 최상 {top}, 최하 {bottom}."
    )
    # Interpret what the leadership says about risk appetite.
    if leading:
        n_def = sum(1 for n in leading if _is_defensive(n))
        n_off = len(leading) - n_def
        if n_off > n_def:
            en += (" Leadership is offensive (cyclicals / growth) — consistent with risk-on "
                   "appetite and a healthy advance.")
            ko += " 주도 섹터가 공격적(경기민감·성장)이라 위험선호 심리와 건강한 상승에 부합합니다."
        elif n_def > n_off:
            en += (" Leadership is defensive (staples / utilities / health care) — money is "
                   "rotating to safety, a caution flag even with the index up.")
            ko += (" 주도 섹터가 방어적(필수소비·유틸리티·헬스케어)이라 자금이 안전처로 이동 중 — "
                   "지수가 올라도 경계 신호입니다.")
        else:
            en += " Leadership is mixed between cyclicals and defensives — no clear risk tilt yet."
            ko += " 주도 섹터가 경기민감·방어 혼재 — 아직 뚜렷한 위험선호 방향은 없습니다."
    return en, ko


_service_singleton: MarketService | None = None


def get_market_service() -> MarketService:
    global _service_singleton
    if _service_singleton is None:
        _service_singleton = MarketService()
    return _service_singleton
