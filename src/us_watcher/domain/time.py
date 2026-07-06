"""Timezone-aware time utilities.

All times are stored and reasoned about in UTC. The primary *market* timezone is
``America/New_York`` (spec §37) and the user-facing dual display is ET + KST.
Naive datetimes are rejected at domain boundaries.

Beyond the coarse intraday ``session_status`` label this module also answers the
forward-looking question *"what is the next U.S. trading session?"* — so that
when the market is closed (after hours, a weekend, or an exchange holiday) the
product can frame its analysis as a forecast for the **upcoming** session instead
of going dark. The trading calendar (weekends + the standard NYSE full-day
holidays, Good Friday included) is computed deterministically. It remains
advisory — it does NOT model ad-hoc half-days or rare unscheduled closures — so
callers still rely on each data item's ``as_of`` for true freshness.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from functools import cache
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
KST = ZoneInfo("Asia/Seoul")

# Regular US cash-equity session (ET). DST is handled automatically by ZoneInfo.
_MARKET_OPEN = time(9, 30)
_MARKET_CLOSE = time(16, 0)
_PREMARKET_OPEN = time(4, 0)
_AFTERHOURS_CLOSE = time(20, 0)

_WEEKDAY_KO = ("월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일")


def now_utc() -> datetime:
    """Current time, timezone-aware in UTC."""
    return datetime.now(tz=UTC)


def ensure_aware(dt: datetime) -> datetime:
    """Reject naive datetimes; normalise to UTC. Domain-boundary guard."""
    if dt.tzinfo is None:
        raise ValueError("naive datetime rejected at domain boundary; use tz-aware UTC")
    return dt.astimezone(UTC)


def to_et(dt: datetime) -> datetime:
    return ensure_aware(dt).astimezone(ET)


def to_kst(dt: datetime) -> datetime:
    return ensure_aware(dt).astimezone(KST)


# ---------------------------------------------------------------------------
# Trading calendar (deterministic; weekends + standard NYSE full-day holidays).
# ---------------------------------------------------------------------------

def _easter(year: int) -> date:
    """Gregorian Easter Sunday (Anonymous algorithm) — basis for Good Friday."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    el = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * el) // 451
    month = (h + el - 7 * m + 114) // 31
    day = ((h + el - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """The ``n``-th (1-based) ``weekday`` (Mon=0) of ``month``."""
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    """The last ``weekday`` (Mon=0) of ``month``."""
    nxt = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    last = nxt - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _observed(d: date) -> date:
    """NYSE weekend-observation rule for fixed-date holidays (Sat→Fri, Sun→Mon)."""
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


@cache
def _us_market_holidays(year: int) -> frozenset[date]:
    """Standard NYSE full-day closures for ``year`` (advisory; no half-days)."""
    h: set[date] = set()
    # New Year's Day — observed Sun→Mon, but NOT shifted back to the Friday when it
    # falls on a Saturday (the NYSE stays open that preceding Friday).
    ny = date(year, 1, 1)
    if ny.weekday() == 6:
        h.add(date(year, 1, 2))
    elif ny.weekday() != 5:
        h.add(ny)
    h.add(_nth_weekday(year, 1, 0, 3))        # Martin Luther King Jr. Day
    h.add(_nth_weekday(year, 2, 0, 3))        # Washington's Birthday (Presidents' Day)
    h.add(_easter(year) - timedelta(days=2))  # Good Friday
    h.add(_last_weekday(year, 5, 0))          # Memorial Day
    if year >= 2022:
        h.add(_observed(date(year, 6, 19)))   # Juneteenth (federal market holiday since 2022)
    h.add(_observed(date(year, 7, 4)))        # Independence Day
    h.add(_nth_weekday(year, 9, 0, 1))        # Labor Day
    h.add(_nth_weekday(year, 11, 3, 4))       # Thanksgiving
    h.add(_observed(date(year, 12, 25)))      # Christmas
    return frozenset(h)


def is_trading_day(d: date) -> bool:
    """True when ``d`` is a regular NYSE session (not weekend, not a holiday)."""
    return d.weekday() < 5 and d not in _us_market_holidays(d.year)


def next_trading_day(d: date) -> date:
    """The first trading day strictly after ``d``."""
    nd = d + timedelta(days=1)
    while not is_trading_day(nd):
        nd += timedelta(days=1)
    return nd


def session_status(dt: datetime | None = None) -> str:
    """Coarse US market session label for the given instant (ET).

    Returns one of: ``"premarket"``, ``"open"``, ``"afterhours"``, ``"closed"``,
    ``"weekend"``, ``"holiday"``. Calendar-aware for weekends and the standard
    NYSE holidays, but it does NOT model half-days or rare unscheduled closures —
    callers treat it as advisory and rely on the data ``as_of`` for freshness.
    """
    et = to_et(dt or now_utc())
    if et.weekday() >= 5:  # Saturday/Sunday
        return "weekend"
    if et.date() in _us_market_holidays(et.year):
        return "holiday"
    t = et.time()
    if _MARKET_OPEN <= t < _MARKET_CLOSE:
        return "open"
    if _PREMARKET_OPEN <= t < _MARKET_OPEN:
        return "premarket"
    if _MARKET_CLOSE <= t < _AFTERHOURS_CLOSE:
        return "afterhours"
    return "closed"


@dataclass(frozen=True)
class NextSession:
    """The upcoming (or in-progress) U.S. regular session we forecast toward."""

    session_date: date
    open_et: datetime
    close_et: datetime
    open_kst: datetime
    is_today: bool  # the current ET day's own session (we are pre-open or mid-session)

    @property
    def weekday_en(self) -> str:
        return self.open_et.strftime("%A")

    @property
    def weekday_ko(self) -> str:
        return _WEEKDAY_KO[self.session_date.weekday()]


def upcoming_session(dt: datetime | None = None) -> NextSession:
    """The next U.S. regular session to look ahead to from ``dt`` (now if None).

    If the current ET day is a trading day and the close has not yet passed, that
    (today's) session is returned with ``is_today=True`` — we are pre-open or
    mid-session. Otherwise (after the close, a weekend, or a holiday) the next
    trading day's session is returned. ``open_et``/``close_et`` are tz-aware ET
    (DST-correct); ``open_kst`` is the same instant in Korean time for the dual
    display. On a Korean weekend this resolves to the upcoming Monday's open.
    """
    et = to_et(dt or now_utc())
    today = et.date()
    if is_trading_day(today) and et.time() < _MARKET_CLOSE:
        sess_date, is_today = today, True
    else:
        sess_date, is_today = next_trading_day(today), False
    open_et = datetime.combine(sess_date, _MARKET_OPEN, tzinfo=ET)
    close_et = datetime.combine(sess_date, _MARKET_CLOSE, tzinfo=ET)
    return NextSession(
        session_date=sess_date,
        open_et=open_et,
        close_et=close_et,
        open_kst=open_et.astimezone(KST),
        is_today=is_today,
    )
