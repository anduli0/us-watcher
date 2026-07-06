"""Unit tests for rotation quadrants, money guard, timezone, features."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from us_watcher.domain.analytics.features import build_features
from us_watcher.domain.analytics.series import Bar
from us_watcher.domain.enums import RotationQuadrant
from us_watcher.domain.money import to_decimal
from us_watcher.domain.time import (
    ensure_aware,
    is_trading_day,
    next_trading_day,
    now_utc,
    session_status,
    to_kst,
    upcoming_session,
)
from us_watcher.market.service import _quadrant


# ---- rotation quadrants ----
def test_quadrant_leading():
    assert _quadrant(0.06, 0.02) == RotationQuadrant.LEADING  # strong & rising


def test_quadrant_weakening():
    assert _quadrant(0.06, 0.10) == RotationQuadrant.WEAKENING  # strong but momentum down


def test_quadrant_improving():
    assert _quadrant(-0.02, -0.06) == RotationQuadrant.IMPROVING  # weak but rising


def test_quadrant_lagging():
    assert _quadrant(-0.06, -0.02) == RotationQuadrant.LAGGING  # weak & falling


# ---- money guard ----
def test_to_decimal_rejects_float():
    with pytest.raises(TypeError):
        to_decimal(1.23)


def test_to_decimal_accepts_str_int():
    assert str(to_decimal("1.23")) == "1.23"
    assert str(to_decimal(5)) == "5"


# ---- timezone ----
def test_ensure_aware_rejects_naive():
    with pytest.raises(ValueError):
        ensure_aware(datetime(2026, 1, 1, 12, 0, 0))


def test_to_kst_offset():
    dt = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    assert to_kst(dt).hour == 9  # KST = UTC+9


def test_session_status_values():
    assert session_status(now_utc()) in {
        "premarket", "open", "afterhours", "closed", "weekend", "holiday",
    }


# ---- trading calendar / next session ----
def test_is_trading_day_weekend_and_holiday():
    assert is_trading_day(date(2026, 6, 29)) is True          # Monday, regular
    assert is_trading_day(date(2026, 6, 27)) is False         # Saturday
    assert is_trading_day(date(2026, 1, 19)) is False         # MLK Day (3rd Mon Jan)
    assert is_trading_day(date(2026, 4, 3)) is False          # Good Friday 2026
    assert is_trading_day(date(2026, 7, 3)) is False          # Independence Day observed (Jul 4 is Sat)
    assert is_trading_day(date(2026, 12, 25)) is False        # Christmas (Fri)


def test_next_trading_day_skips_weekend_and_holiday():
    assert next_trading_day(date(2026, 6, 27)) == date(2026, 6, 29)   # Sat → Mon
    assert next_trading_day(date(2026, 7, 2)) == date(2026, 7, 6)     # Thu → Mon (Fri holiday + weekend)


def test_upcoming_session_on_korean_weekend_targets_monday():
    # Saturday 2026-06-27, 06:00 UTC (15:00 KST) — deep in the Korean weekend.
    sat = datetime(2026, 6, 27, 6, 0, tzinfo=UTC)
    ns = upcoming_session(sat)
    assert ns.session_date == date(2026, 6, 29)   # the upcoming Monday
    assert ns.is_today is False
    assert ns.weekday_en == "Monday"
    assert ns.weekday_ko == "월요일"
    assert (ns.open_et.hour, ns.open_et.minute) == (9, 30)   # 9:30 AM ET open
    assert str(ns.open_kst.tzinfo) == "Asia/Seoul"


def test_upcoming_session_intraday_is_today():
    # 2026-06-29 (Mon) 14:00 UTC = 10:00 ET — market is open, today's session.
    intraday = datetime(2026, 6, 29, 14, 0, tzinfo=UTC)
    ns = upcoming_session(intraday)
    assert ns.session_date == date(2026, 6, 29)
    assert ns.is_today is True


def test_session_status_holiday():
    # 2026-12-25 (Christmas, Fri) 17:00 UTC = 12:00 ET.
    assert session_status(datetime(2026, 12, 25, 17, 0, tzinfo=UTC)) == "holiday"


# ---- features ----
def _bars(closes: list[float]) -> list[Bar]:
    now = now_utc()
    return [Bar(as_of=now, open=c, high=c * 1.01, low=c * 0.99, close=c) for c in closes]


def test_build_features_partial_data_marks_none():
    feat = build_features("TEST", _bars([100.0, 101.0, 102.0]), now_utc())
    assert feat.n_bars == 3
    assert feat.returns["r252"] is None  # not enough history
    assert feat.moving_averages["ma200"] is None
    assert feat.last_close == 102.0


def test_features_availability_fraction():
    closes = [100.0 + i for i in range(260)]
    feat = build_features("TEST", _bars(closes), now_utc())
    assert feat.availability() > 0.8
    assert feat.above_ma200 is True
