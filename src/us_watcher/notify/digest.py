"""Build and send the daily Telegram digests (brief + recommendations).

Reads the latest persisted Korean brief and recommendations and formats compact,
readable Telegram messages with a link back to the full web report. Read-side
only; delivery is best-effort (``send_telegram`` never raises).
"""

from __future__ import annotations

from typing import Any

from us_watcher.config import get_settings
from us_watcher.db.repositories import latest_briefing, latest_recommendations
from us_watcher.logging_config import get_logger
from us_watcher.notify.telegram import esc, send_telegram

log = get_logger(__name__)

_ACTION_KO = {
    "strong_buy": "🟢 적극 매수", "buy": "🟢 매수", "accumulate": "🟢 분할 매수",
    "hold": "⚪ 보유", "watch": "⚪ 관망",
    "reduce": "🔴 비중 축소", "sell": "🔴 매도", "avoid": "🔴 회피",
}
_HORIZON_KO = {"short": "단기", "medium": "중기", "medium_long": "중장기"}
_BUY_SIDE = {"strong_buy", "buy", "accumulate"}
_SELL_SIDE = {"reduce", "sell", "avoid"}


async def send_brief_digest() -> bool:
    """Send the latest Korean daily brief to Telegram."""
    b = await latest_briefing(language="ko", briefing_type="full")
    if not b:
        log.info("digest.brief_absent")
        return False
    base = get_settings().public_base_url
    pl: dict[str, Any] = b.get("payload", {}) or {}
    sections = {s.get("title"): s.get("body", "") for s in pl.get("sections", [])}
    lines = [
        "📊 <b>US Stock Watcher · 데일리 브리핑</b>",
        f"🗓 {esc(b.get('briefing_date', ''))}",
        "",
        f"<b>한줄 결론</b>\n{esc(b.get('headline', ''))}",
    ]
    # When the market is shut (weekend/holiday/after-hours) lead with the next-session
    # forecast so the Korean-weekend push clearly reads as a Monday outlook.
    ns_line = pl.get("next_session_line")
    if pl.get("is_forecast") and isinstance(ns_line, str) and ns_line.strip():
        lines.append(f"\n🔮 <b>다음 장 전망</b>\n{esc(ns_line)}")
    for title in ("단기 전망", "중기 전망", "중장기 전망"):
        if sections.get(title):
            lines.append(f"\n<b>{esc(title)}</b>\n{esc(sections[title])}")
    if sections.get("섹터/로테이션"):
        lines.append(f"\n<b>섹터 · 로테이션</b>\n{esc(sections['섹터/로테이션'])}")
    if sections.get("주요 뉴스"):
        news = [n for n in sections["주요 뉴스"].split(" || ") if n][:3]
        if news:
            lines.append("\n<b>주요 뉴스</b>\n" + "\n".join(f"• {esc(n)}" for n in news))
    wc = pl.get("what_changed")
    if isinstance(wc, list):
        wc = " · ".join(str(x) for x in wc)
    if isinstance(wc, str) and wc.strip():
        lines.append(f"\n<b>어제 대비 변화</b>\n{esc(wc)}")
    lines.append(f"\n🔗 전체 리포트: {base}/brief")
    lines.append("\n<i>정보·연구·교육용 AI 분석 · 투자자문 아님</i>")
    return await send_telegram("\n".join(lines))


async def send_recommendations_digest() -> bool:
    """Send the strongest current stock recommendations to Telegram."""
    recs = await latest_recommendations()
    if not recs:
        log.info("digest.recs_absent")
        return False
    base = get_settings().public_base_url
    as_of = (recs[0].get("as_of") or "")[:10]
    # Keep the strongest-conviction signal per ticker (max score across horizons).
    best: dict[str, dict[str, Any]] = {}
    for r in recs:
        t = r.get("ticker")
        if not t:
            continue
        if t not in best or (r.get("total_score") or 0) > (best[t].get("total_score") or 0):
            best[t] = r
    items = list(best.values())
    buys = sorted(
        (r for r in items if r.get("action") in _BUY_SIDE),
        key=lambda r: r.get("total_score") or 0, reverse=True,
    )[:6]
    sells = sorted(
        (r for r in items if r.get("action") in _SELL_SIDE),
        key=lambda r: r.get("total_score") or 0,
    )[:4]

    def line(r: dict[str, Any]) -> str:
        act = _ACTION_KO.get(r.get("action", ""), r.get("action", ""))
        hz = _HORIZON_KO.get(r.get("horizon", ""), r.get("horizon", ""))
        name = r.get("company_name") or r.get("ticker") or ""
        return (
            f"• <b>{esc(r.get('ticker', ''))}</b> {esc(name)} — {act} "
            f"({esc(hz)}) · 점수 {(r.get('total_score') or 0):.0f}/100"
        )

    lines = ["💡 <b>US Stock Watcher · 종목 추천 업데이트</b>", f"🗓 {esc(as_of)}"]
    if buys:
        lines.append("\n<b>매수 우위 (확신 상위)</b>")
        lines += [line(r) for r in buys]
    if sells:
        lines.append("\n<b>비중 축소 · 회피</b>")
        lines += [line(r) for r in sells]
    if not buys and not sells:
        lines.append("\n현재 강한 매수/매도 신호 없음 — 대부분 보유·관망 구간입니다.")
    lines.append(f"\n🔗 전체 추천 · 근거: {base}/recommendations")
    lines.append("\n<i>정보·연구·교육용 AI 분석 · 투자자문·목표가 단정 아님</i>")
    return await send_telegram("\n".join(lines))
