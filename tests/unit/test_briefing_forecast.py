"""Weekend / closed-market brief is authored as a next-session (Monday) forecast."""

from __future__ import annotations

from us_watcher.briefing.service import _compose_report
from us_watcher.domain.enums import Language


def _payload(*, is_forecast: bool) -> dict:
    return {
        "date_et": "2026-06-27T03:00:00-04:00",
        "data_timestamp": "2026-06-26T20:00:00+00:00",
        "data_quality": "fresh",
        "is_forecast": is_forecast,
        "next_session_line": "The next U.S. regular session is Monday 6/29 (opens 9:30 AM ET / 22:30 KST 6/29).",
        "next_session_label": "Monday 6/29",
        "one_line_conclusion": "[Monday 6/29 session outlook] bullish lean — Moderate uptrend",
        "executive_summary": "Forward read into Monday.",
        "sections": [{"body": f"s{i}"} for i in range(9)],
        "what_changed": {"items": ["No material change vs prior brief."]},
        "sources": ["Yahoo Finance (delayed)"],
        "disclaimer": "Not investment advice.",
    }


def test_forecast_brief_titled_as_next_session_forecast():
    md = _compose_report(Language.EN, _payload(is_forecast=True))
    assert "# US Stock Watcher Next-Session Forecast — Monday 6/29" in md
    assert "🔮 Next-session forecast" in md
    # the generic daily title must NOT be used for a forecast edition
    assert "Daily Comprehensive Brief" not in md


def test_regular_brief_keeps_daily_title():
    md = _compose_report(Language.EN, _payload(is_forecast=False))
    assert "# US Stock Watcher Daily Comprehensive Brief — 2026-06-27" in md
    assert "🔮" not in md
    assert "Next-Session Forecast" not in md
