"""Response DTOs for the market/overview/index/sector surfaces.

These are presentation-shaped (what the API returns and the web renders). Every
data-bearing object carries a :class:`DataStatus` and an ``as_of`` so the UI can
label provenance and freshness (spec §3.3, §6.1, §6.2).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from us_watcher.domain.enums import DataStatus, MarketRegime, RotationQuadrant


class MarketCard(BaseModel):
    """One core market card (spec §6.2): value + multi-horizon changes + status."""

    model_config = ConfigDict(extra="forbid")

    symbol: str
    name: str
    group: str
    last: float | None
    change_1d_pct: float | None
    change_1w_pct: float | None
    change_1m_pct: float | None
    change_3m_pct: float | None
    trend: str  # "up" | "down" | "flat" | "na"
    status: DataStatus
    source: str
    as_of: datetime | None
    is_proxy: bool = False
    interpretation_en: str
    interpretation_ko: str


class NarrativeBlock(BaseModel):
    """One labelled section of a structured, plain-language interpretation.

    The body is prose; ``bullets`` are optional supporting points. Both EN and
    KO are always populated from the SAME computed numbers — the narrative is
    deterministic interpretation, never invented data (CLAUDE.md invariant 1).
    """

    model_config = ConfigDict(extra="forbid")

    key: str  # "summary" | "drivers" | "stance" | "watch" | "coverage"
    label_en: str
    label_ko: str
    body_en: str = ""
    body_ko: str = ""
    bullets_en: list[str] = []
    bullets_ko: list[str] = []


class RegimeNarrative(BaseModel):
    """Structured, criteria-anchored reading of the regime for non-experts.

    Replaces the single terse diagnosis line: a headline bottom-line plus
    labelled blocks (what it means / key drivers / how to position / what to
    watch / data coverage) so the reader gets the *so-what*, not just numbers.
    """

    model_config = ConfigDict(extra="forbid")

    headline_en: str
    headline_ko: str
    blocks: list[NarrativeBlock]


class RegimePulse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: float
    regime: MarketRegime
    regime_ko: str
    regime_en: str
    confidence: float
    coverage: float
    available: list[str]
    unavailable: list[str]
    diagnosis_en: str
    diagnosis_ko: str
    narrative: RegimeNarrative | None = None


class NextSession(BaseModel):
    """The upcoming U.S. regular session the overview forecasts toward.

    Present so the UI can frame a closed market (after-hours / weekend / holiday)
    as a forward look at the next session instead of a dead "closed" label.
    ``is_forecast`` is true whenever the market is not currently open.
    """

    model_config = ConfigDict(extra="forbid")

    session_date: str  # ISO date (ET calendar) of the session
    open_et: datetime
    open_kst: datetime
    is_today: bool
    is_forecast: bool
    weekday_en: str
    weekday_ko: str
    label_en: str
    label_ko: str


class OverviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    as_of: datetime
    session: str
    data_quality: str
    pulse: RegimePulse
    cards: list[MarketCard]
    drivers: list[MarketDriver]
    notes: list[str]
    next_session: NextSession | None = None


class MarketDriver(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    name_ko: str
    direction: str  # "supportive" | "headwind" | "mixed"
    rank: int
    confidence: float
    evidence_en: str
    evidence_ko: str


class IndexWatcherResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    market: str
    name: str
    as_of: datetime
    cards: list[MarketCard]
    metrics: list[Metric]
    diagnosis_en: str
    diagnosis_ko: str
    notes: list[str]


class Metric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label_en: str
    label_ko: str
    value: float | None
    unit: str = ""
    status: DataStatus = DataStatus.END_OF_DAY
    hint_en: str = ""
    hint_ko: str = ""


class SectorRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    name: str
    gics: str
    ret_1w: float | None
    ret_1m: float | None
    ret_3m: float | None
    ret_6m: float | None
    rel_strength_1m: float | None  # vs SPY
    quadrant: RotationQuadrant
    status: DataStatus
    as_of: datetime | None


class RotationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    as_of: datetime
    benchmark: str
    sectors: list[SectorRow]
    style_leadership: list[StyleRow]
    diagnosis_en: str
    diagnosis_ko: str
    notes: list[str]


class StyleRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    style: str
    symbol: str
    name: str
    ret_1m: float | None
    rel_strength_1m: float | None
    leading: bool


# Resolve forward references (MarketDriver / Metric / StyleRow declared after use).
OverviewResponse.model_rebuild()
IndexWatcherResponse.model_rebuild()
RotationResponse.model_rebuild()
