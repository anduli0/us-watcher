"""Daily Brief generation (spec §30).

Builds the Full Daily Brief deterministically from the frozen market snapshot,
rotation, macro spine, latest recommendations, and top news clusters — in BOTH
English and Korean, stored separately (spec §31). Includes a "What Changed Since
Yesterday" diff vs the prior brief. Duplicate briefs for the same
(date, type, language) are prevented by an upsert.
"""

from __future__ import annotations

from sqlalchemy import select

from us_watcher.config import get_settings
from us_watcher.db.models import DailyBriefing
from us_watcher.db.repositories import add_audit_event, list_news_clusters
from us_watcher.domain.enums import BriefingType, Language
from us_watcher.domain.time import NextSession, now_utc, to_et, upcoming_session
from us_watcher.infrastructure.db import get_sessionmaker
from us_watcher.infrastructure.llm.factory import get_llm_provider
from us_watcher.market.schemas import OverviewResponse, RegimePulse, RotationResponse
from us_watcher.market.service import get_market_service


async def generate_daily_brief(briefing_type: BriefingType = BriefingType.FULL) -> dict:
    svc = get_market_service()
    overview = await svc.build_overview()
    rotation = await svc.build_rotation()
    clusters = await list_news_clusters(limit=6)
    date_et = to_et(now_utc()).date().isoformat()
    next_session = upcoming_session()
    # When the market is not currently open the brief is a forward look at the
    # next session (on a Korean weekend, the upcoming Monday open).
    is_forecast = overview.session != "open"

    settings = get_settings()
    results = {}
    for lang in (Language.EN, Language.KO):
        payload = _build_payload(lang, overview, rotation, clusters, briefing_type,
                                 next_session, is_forecast)
        prior = await _prior_brief(date_et, briefing_type.value, lang.value)
        payload["what_changed"] = _what_changed(lang, overview, prior)
        # Comprehensive submittable report: weave all sections into ONE document.
        report_md = _compose_report(lang, payload)
        gen_by = "deterministic"
        if settings.llm_enabled:
            woven = await _llm_report(lang, report_md, is_forecast=is_forecast)
            if woven:
                report_md, gen_by = woven, "llm"
        payload["report_md"] = report_md
        payload["report_generated_by"] = gen_by
        headline = payload["one_line_conclusion"]
        await _upsert(date_et, briefing_type.value, lang.value, headline, payload)
        _archive_to_file(date_et, briefing_type.value, lang.value, report_md)
        results[lang.value] = {"headline": headline, "sections": len(payload.get("sections", [])),
                               "report_chars": len(report_md), "report_by": gen_by}

    await add_audit_event("briefing.generated", f"Daily brief {date_et} ({briefing_type.value})",
                          payload={"date": date_et})
    return {"date": date_et, "type": briefing_type.value, "languages": list(results.keys()),
            "results": results, "as_of": now_utc().isoformat()}


def _build_payload(
    lang: Language, overview: OverviewResponse, rotation: RotationResponse,
    clusters: list[dict], briefing_type: BriefingType,
    next_session: NextSession, is_forecast: bool,
) -> dict:
    p = overview.pulse
    ko = lang == Language.KO
    cards = {c.symbol: c for c in overview.cards}
    next_line = _next_session_line(ko, next_session)
    # Short session label for headlines/titles, e.g. "월요일 6/29" / "Monday 6/29".
    sess_label = (
        f"{next_session.weekday_ko} {next_session.open_et.month}/{next_session.open_et.day}"
        if ko else
        f"{next_session.weekday_en} {next_session.open_et.month}/{next_session.open_et.day}"
    )

    def card_line(sym: str, label: str) -> str:
        c = cards.get(sym)
        if not c or c.last is None:
            return f"{label}: n/a"
        if c.change_1d_pct is None:
            return f"{label}: {c.last:,.2f}"
        return f"{label}: {c.last:,.2f} ({c.change_1d_pct:+.2f}% 1d)"

    bias_ko = "상승 우위" if p.score > 10 else "하락 우위" if p.score < -10 else "중립"
    bias_en = "bullish lean" if p.score > 10 else "bearish lean" if p.score < -10 else "neutral"
    if is_forecast:
        # Weekend / closed-market brief: author it explicitly as a forecast for the
        # next U.S. session (on a Korean weekend, Monday). The deterministic regime
        # numbers are unchanged — only the framing leads with the forward call.
        conclusion = (
            f"[{sess_label} 장 예측] {bias_ko} — {p.regime_ko} 국면 · "
            f"종합점수 {p.score:+.0f} · 신뢰도 {p.confidence:.0f}%"
            if ko else
            f"[{sess_label} session outlook] {bias_en} — {p.regime_en} · "
            f"composite {p.score:+.0f} · confidence {p.confidence:.0f}%"
        )
    else:
        conclusion = (
            f"{p.regime_ko} · 종합점수 {p.score:+.0f} · 신뢰도 {p.confidence:.0f}%"
            if ko else
            f"{p.regime_en} · composite {p.score:+.0f} · confidence {p.confidence:.0f}%"
        )
    leaders = ", ".join(r.name for r in rotation.sectors[:3])
    laggards = ", ".join(r.name for r in rotation.sectors[-3:])
    sections = [
        {"title": "지수" if ko else "Major indices",
         "body": " | ".join([card_line("SPX", "S&P 500"), card_line("NDX", "Nasdaq-100"),
                             card_line("DJI", "Dow"), card_line("RUT", "Russell 2000")])},
        {"title": "시장 동인" if ko else "Market drivers",
         "body": "; ".join((d.name_ko if ko else d.name) + f" ({d.direction})" for d in overview.drivers)},
        {"title": "폭/집중도" if ko else "Breadth & concentration",
         "body": (p.diagnosis_ko if ko else p.diagnosis_en)},
        {"title": "섹터 순환" if ko else "Sector & rotation",
         "body": (f"주도: {leaders}. 부진: {laggards}." if ko else f"Leading: {leaders}. Lagging: {laggards}.")},
        {"title": "금리/달러/원자재" if ko else "Rates, dollar, oil",
         "body": " | ".join([card_line("US10Y", "10Y"), card_line("DXY", "DXY"),
                             card_line("WTI", "WTI"), card_line("GOLD", "Gold")])},
        {"title": "단기 전망" if ko else "Short-term outlook",
         "body": _short_outlook(ko, p, next_line, is_forecast)},
        {"title": "중기 전망" if ko else "Medium-term outlook",
         "body": (_outlook_ko if ko else _outlook_en)(p, "medium")},
        {"title": "중장기 전망" if ko else "Medium-to-long-term outlook",
         "body": (_outlook_ko if ko else _outlook_en)(p, "medium_long")},
        {"title": "주요 뉴스" if ko else "Top news",
         "body": " || ".join(c["headline"] for c in clusters) or ("뉴스 없음" if ko else "No news ingested.")},
    ]
    disclaimer = (
        "본 브리핑은 정보 제공·연구·교육 목적의 AI 분석이며 투자자문이 아닙니다."
        if ko else
        "This brief is AI-generated for information/research/education only — not investment advice."
    )
    diagnosis = p.diagnosis_ko if ko else p.diagnosis_en
    if is_forecast:
        # Lead the summary with the forward call so the whole brief reads as a
        # forecast for the upcoming session, not a recap of a closed market.
        executive_summary = (
            f"{next_line} 이번 브리핑은 그 장을 향한 예측입니다. {diagnosis}" if ko else
            f"{next_line} This brief is a forecast for that session. {diagnosis}"
        )
    else:
        executive_summary = diagnosis
    return {
        "date_et": to_et(now_utc()).isoformat(),
        "data_timestamp": overview.as_of.isoformat(),
        "data_quality": overview.data_quality,
        "regime_label": p.regime.value,
        "score": p.score,
        "is_forecast": is_forecast,
        "next_session_line": next_line,
        "next_session_label": sess_label,
        "one_line_conclusion": conclusion,
        "executive_summary": executive_summary,
        "sections": sections,
        "disclaimer": disclaimer,
        "sources": ["Yahoo Finance (delayed)", "FRED (keyless)", "Google News RSS"],
    }


def _next_session_line(ko: bool, ns: NextSession) -> str:
    """One-line, plain-language statement of the next U.S. regular session."""
    m, d = ns.open_et.month, ns.open_et.day
    km, kd = ns.open_kst.month, ns.open_kst.day
    khm = f"{ns.open_kst.hour:02d}:{ns.open_kst.minute:02d}"
    if ko:
        return (f"다음 미국 정규장은 {ns.weekday_ko} {m}/{d}"
                f"(한국시각 {km}/{kd} {khm} 개장)입니다.")
    return (f"The next U.S. regular session is {ns.weekday_en} {m}/{d} "
            f"(opens 9:30 AM ET / {khm} KST {km}/{kd}).")


def _short_outlook(ko: bool, p: RegimePulse, next_line: str, is_forecast: bool) -> str:
    """Short-horizon outlook, framed for the next session when the market is shut."""
    base = (_outlook_ko if ko else _outlook_en)(p, "short")
    if not is_forecast:
        return base
    lead = (f"{next_line} 아래 전망은 그 장을 기준으로 합니다. " if ko
            else f"{next_line} The outlook below is framed for that session. ")
    return lead + base


def _outlook_en(p: RegimePulse, horizon: str) -> str:
    bias = "constructive" if p.score > 10 else "defensive" if p.score < -10 else "balanced"
    h = horizon.replace("_", "-").title()
    return (f"{h}: {bias} bias given the '{p.regime_en}' market state (confidence {p.confidence:.0f}%). "
            "The view flips if the overall score crosses zero.")


def _outlook_ko(p: RegimePulse, horizon: str) -> str:
    bias = "우호적" if p.score > 10 else "방어적" if p.score < -10 else "중립"
    label = {"short": "단기", "medium": "중기", "medium_long": "중장기"}.get(horizon, horizon)
    return (f"{label}: '{p.regime_ko}' 국면 기준 {bias} 쪽에 무게 (신뢰도 {p.confidence:.0f}%). "
            "종합점수가 0을 넘어서면 방향 판단이 바뀔 수 있어 주의.")


def _what_changed(lang: Language, overview: OverviewResponse, prior: dict | None) -> dict:
    ko = lang == Language.KO
    if prior is None:
        return {"items": [("이전 브리핑 없음 — 최초 발행." if ko else "No prior brief — first publication.")]}
    items: list[str] = []
    prev_regime = prior.get("regime_label")
    cur_regime = overview.pulse.regime.value
    if prev_regime and prev_regime != cur_regime:
        items.append(
            f"시장 국면 변화: {prev_regime} → {cur_regime}." if ko
            else f"Market-state change: {prev_regime} → {cur_regime}.")
    prev_score = prior.get("score")
    if prev_score is not None:
        delta = overview.pulse.score - prev_score
        if abs(delta) >= 5:
            items.append(f"종합점수 {delta:+.0f} 변화." if ko else f"Composite score moved {delta:+.0f}.")
    if not items:
        items.append("중대한 변화 없음." if ko else "No material change vs prior brief.")
    return {"items": items}


def _compose_report(lang: Language, payload: dict) -> str:
    """Weave every section into ONE cohesive Markdown report (submittable).

    Deterministic baseline — a single continuous document (not separate cards),
    with bold lead-ins and connected prose. When an LLM editor is configured the
    caller rewrites this into fully flowing prose, keeping the numbers exact.
    """
    ko = lang == Language.KO
    s = [x["body"] for x in payload.get("sections", [])]

    def sec(i: int) -> str:
        return s[i] if i < len(s) else ""

    wc = payload.get("what_changed", {}).get("items", [])
    date = str(payload.get("date_et", ""))[:10]
    sess_label = payload.get("next_session_label", "")
    if payload.get("is_forecast") and sess_label:
        # Weekend / closed-market editions are titled as the next-session forecast.
        title = (f"US Stock Watcher 다음 장 예측 브리핑 — {sess_label}" if ko
                 else f"US Stock Watcher Next-Session Forecast — {sess_label}")
        heading = f"# {title}"
    else:
        title = ("US Stock Watcher 데일리 종합 브리핑" if ko
                 else "US Stock Watcher Daily Comprehensive Brief")
        heading = f"# {title} — {date}"
    out: list[str] = [
        heading,
        "",
        f"> **{payload['one_line_conclusion']}**",
        "",
    ]
    if payload.get("is_forecast") and payload.get("next_session_line"):
        flag = "🔮 다음 장 전망" if ko else "🔮 Next-session forecast"
        out += [f"> **{flag}** · {payload['next_session_line']}", ""]
    out += [
        f"_{('데이터 기준' if ko else 'Data as of')}: {str(payload.get('data_timestamp',''))[:19]} · "
        f"{('데이터 품질' if ko else 'data quality')}: {payload.get('data_quality','')}_",
        "",
        ("## 총평" if ko else "## Executive summary"),
        payload["executive_summary"],
        "",
        ("## 시장 진단" if ko else "## Market diagnosis"),
    ]
    if ko:
        out += [
            f"**지수.** {sec(0)}", "",
            f"**시장 동인.** {sec(1)}", "",
            f"**폭·집중도.** {sec(2)}", "",
            f"**섹터·로테이션.** {sec(3)}", "",
            f"**금리·달러·원자재.** {sec(4)}", "",
            "## 전망",
            f"**단기.** {sec(5)}", f"**중기.** {sec(6)}", f"**중장기.** {sec(7)}", "",
            "## 주요 뉴스", sec(8), "",
            "## 어제 대비 변화", ("- " + "\n- ".join(wc)) if wc else "—",
        ]
    else:
        out += [
            f"**Indices.** {sec(0)}", "",
            f"**Market drivers.** {sec(1)}", "",
            f"**Breadth & concentration.** {sec(2)}", "",
            f"**Sector & rotation.** {sec(3)}", "",
            f"**Rates, dollar & commodities.** {sec(4)}", "",
            "## Outlook",
            f"**Short term.** {sec(5)}", f"**Medium term.** {sec(6)}", f"**Medium-to-long term.** {sec(7)}", "",
            "## Top news", sec(8), "",
            "## What changed since yesterday", ("- " + "\n- ".join(wc)) if wc else "—",
        ]
    out += [
        "",
        "---",
        f"{'출처' if ko else 'Sources'}: " + ", ".join(payload.get("sources", [])),
        "",
        f"_{payload.get('disclaimer', '')}_",
        "",
        "**US Stock Watcher** · © 2026 Minkyu An · 안민규 · ID-2026-MA-USW-01",
    ]
    return "\n".join(out)


async def _llm_report(lang: Language, deterministic_md: str, is_forecast: bool = False) -> str:
    """Rewrite the deterministic report into one flowing professional report.
    Numbers must stay exact; never invents data. Returns '' on mock/failure."""
    language = "Korean" if lang == Language.KO else "English"
    plain = ""
    if lang == Language.KO:
        plain = (
            " 반드시 일반 투자자가 바로 이해할 평이한 한국어로 쓰세요. 학술·영어 차용 전문용어를 쓰지 마세요 — "
            "'레짐'→'시장 국면', '커버리지'→'측정 범위', '로테이션'→'섹터 순환', '컨센서스'→'시장 전망', "
            "'센티먼트'→'투자심리', '브레드스'→'시장 폭'처럼 쉬운 말로 바꾸고, liquidity·credit·earnings·"
            "macro_surprise·valuation·positioning 같은 영어 항목명은 유동성·신용·실적·경제지표 서프라이즈·"
            "밸류에이션·투자자 포지션으로 번역하세요. 약어를 처음 쓸 땐 괄호로 우리말 설명을 붙이세요."
        )
    forecast = ""
    if is_forecast:
        forecast = (
            " 이 브리핑은 미국 장이 닫힌 상태에서 작성하는 '다음 정규장(주말이면 다가오는 월요일) 예측'입니다. "
            "제목과 도입의 다음 장 예측 프레이밍을 유지하고, 전체를 그 다가오는 장을 향한 전망으로 일관되게 쓰세요. "
            "마감된 장의 회고가 아니라 앞으로의 장에 대한 예측 톤."
            if lang == Language.KO else
            " This brief is a forecast for the NEXT regular U.S. session (the upcoming Monday on a weekend), written "
            "while the market is closed. Keep the next-session forecast framing in the title and lead, and write the "
            "whole report as a forward outlook toward that upcoming session — not a recap of a closed market."
        )
    system = (
        f"You are a senior U.S. equity strategist writing a comprehensive daily brief for submission, in {language}. "
        "Rewrite the DATA into ONE cohesive, flowing professional report — connected prose under clear section "
        "headers, NOT disconnected bullet fragments. Keep EVERY number, ticker, and figure exactly as given; never "
        "invent data. Preserve the section structure, the 'what changed' notes, the sources line, the disclaimer, "
        "and the ownership line. This is analysis, not investment advice." + forecast + plain
    )
    try:
        result = await get_llm_provider().generate_text(
            system,
            f"DATA (rewrite into a flowing, submittable report; keep all numbers exact):\n\n{deterministic_md}",
            role="editor", max_tokens=1800,
        )
        if result.text.strip() and not result.is_mock:
            return result.text.strip()
    except Exception:  # never let the editor break brief generation
        return ""
    return ""


def _archive_to_file(date_et: str, btype: str, lang: str, report_md: str) -> None:
    """Mirror each generated brief to a durable Markdown file under ``briefs/``.

    The DB is the source of truth, but a plain-file archive lets the report be
    re-read, backed up, or shared without the app running. Best-effort — a write
    failure must never break brief generation.
    """
    from pathlib import Path

    from us_watcher.logging_config import get_logger

    try:
        root = Path(__file__).resolve().parents[3]  # …/us-watcher (project root)
        out_dir = root / "briefs"
        out_dir.mkdir(exist_ok=True)
        day = str(date_et)[:10]
        (out_dir / f"{day}_{btype}_{lang}.md").write_text(report_md, encoding="utf-8")
    except Exception as exc:  # never let archiving break the pipeline
        get_logger("us_watcher.briefing").warning("brief.archive_file_failed", error=str(exc)[:200])


async def _prior_brief(date_et: str, btype: str, lang: str) -> dict | None:
    sm = get_sessionmaker()
    async with sm() as s:
        stmt = (
            select(DailyBriefing)
            .where(DailyBriefing.briefing_type == btype, DailyBriefing.language == lang,
                   DailyBriefing.briefing_date != date_et)
            .order_by(DailyBriefing.briefing_date.desc())
            .limit(1)
        )
        row = (await s.execute(stmt)).scalars().first()
    if row is None:
        return None
    payload = row.payload or {}
    return {"regime_label": payload.get("regime_label"), "score": payload.get("score")}


async def _upsert(date_et: str, btype: str, lang: str, headline: str, payload: dict) -> None:
    # carry regime label/score at top level for cheap day-over-day diffing
    sm = get_sessionmaker()
    async with sm() as s:
        stmt = select(DailyBriefing).where(
            DailyBriefing.briefing_date == date_et, DailyBriefing.briefing_type == btype,
            DailyBriefing.language == lang)
        existing = (await s.execute(stmt)).scalars().first()
        if existing is not None:
            existing.headline = headline
            existing.payload = payload
        else:
            s.add(DailyBriefing(
                briefing_date=date_et, briefing_type=btype, language=lang,
                headline=headline, payload=payload, generated_by="deterministic"))
        await s.commit()
