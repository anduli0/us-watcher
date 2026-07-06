"""Domain enumerations.

All enums are :class:`enum.StrEnum` — we persist and serialise the *string
value*, never the ordinal position, so reordering members can never silently
corrupt stored data.
"""

from __future__ import annotations

from enum import StrEnum


class MarketDirection(StrEnum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class Horizon(StrEnum):
    """Investment / analysis horizons used across agents and recommendations."""

    SHORT = "short"          # days to ~4 weeks
    MEDIUM = "medium"        # 1-6 months
    MEDIUM_LONG = "medium_long"  # 6 months to 3+ years


class Impact(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class MarketCode(StrEnum):
    """The four primary Market & Index Watchers, plus auxiliaries."""

    SP500 = "SP500"
    NASDAQ = "NASDAQ"
    DOW = "DOW"
    NYSE = "NYSE"
    SMALL = "SMALL"
    MID = "MID"
    SEMI = "SEMI"
    NA = "NA"


class MarketRegime(StrEnum):
    """Composite regime labels (spec §6.1). Mapped from the deterministic
    Market Regime Score in :mod:`us_watcher.domain.regime`."""

    STRONG_UPTREND = "STRONG_UPTREND"
    MODERATE_UPTREND = "MODERATE_UPTREND"
    BROAD_EXPANSION = "BROAD_EXPANSION"
    SELECTIVE_BULL = "SELECTIVE_BULL"
    ROTATION_EXPANSION = "ROTATION_EXPANSION"
    OVERHEATED_RALLY = "OVERHEATED_RALLY"
    NEUTRAL_RANGE = "NEUTRAL_RANGE"
    CORRECTION = "CORRECTION"
    RISK_OFF = "RISK_OFF"
    BEAR_MARKET = "BEAR_MARKET"
    TRANSITION_WATCH = "TRANSITION_WATCH"


class DataStatus(StrEnum):
    """Provenance / freshness of every data item (spec §14.3). Surfaced in the
    UI when material so a value can never be mistaken for something it is not."""

    REAL_TIME = "REAL_TIME"
    DELAYED = "DELAYED"
    END_OF_DAY = "END_OF_DAY"
    PROXY = "PROXY"
    ESTIMATED = "ESTIMATED"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"
    MOCK = "MOCK"


class DataQuality(StrEnum):
    """Coarse roll-up of data status for an analysis run."""

    FRESH = "fresh"
    MIXED = "mixed"
    STALE = "stale"


class RotationQuadrant(StrEnum):
    LEADING = "LEADING"
    IMPROVING = "IMPROVING"
    WEAKENING = "WEAKENING"
    LAGGING = "LAGGING"


class StyleFactor(StrEnum):
    GROWTH = "GROWTH"
    VALUE = "VALUE"
    QUALITY = "QUALITY"
    MOMENTUM = "MOMENTUM"
    LOW_VOL = "LOW_VOL"
    HIGH_DIV = "HIGH_DIV"
    CYCLICAL = "CYCLICAL"
    DEFENSIVE = "DEFENSIVE"
    LARGE_CAP = "LARGE_CAP"
    MID_CAP = "MID_CAP"
    SMALL_CAP = "SMALL_CAP"


class RecAction(StrEnum):
    """The eight recommendation actions (spec §23)."""

    STRONG_BUY = "strong_buy"
    BUY = "buy"
    ACCUMULATE = "accumulate"
    HOLD = "hold"
    WATCH = "watch"
    REDUCE = "reduce"
    SELL = "sell"
    AVOID = "avoid"


class AssetType(StrEnum):
    STOCK = "stock"
    ETF = "etf"
    COVERED_CALL_ETF = "covered_call_etf"
    ADR = "adr"
    INDEX = "index"
    OTHER = "other"


class Language(StrEnum):
    KO = "ko"
    EN = "en"


class BriefingType(StrEnum):
    PREMARKET = "premarket"
    MIDDAY = "midday"
    CLOSING = "closing"
    FULL = "full"
    WEEKLY = "weekly"
    EVENT = "event"


# Korean labels for the eight actions (spec §23).
REC_ACTION_KO: dict[RecAction, str] = {
    RecAction.STRONG_BUY: "강한 매수",
    RecAction.BUY: "매수",
    RecAction.ACCUMULATE: "분할매수",
    RecAction.HOLD: "보유",
    RecAction.WATCH: "관망",
    RecAction.REDUCE: "비중축소",
    RecAction.SELL: "매도",
    RecAction.AVOID: "회피",
}
