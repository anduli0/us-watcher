"""Fundamental snapshot (pure domain data shape).

Lives in ``domain`` so analytics/recommendation can depend on it without
importing infrastructure. The provider in
``infrastructure/marketdata/fundamentals.py`` produces it.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class FundamentalSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    as_of: datetime
    source: str = "yahoo"
    # Quality
    profit_margin: float | None = None
    operating_margin: float | None = None
    gross_margin: float | None = None
    return_on_equity: float | None = None
    revenue_growth: float | None = None
    earnings_growth: float | None = None
    free_cashflow: float | None = None
    total_debt: float | None = None
    debt_to_equity: float | None = None
    # Valuation
    trailing_pe: float | None = None
    forward_pe: float | None = None
    peg_ratio: float | None = None
    price_to_book: float | None = None
    # Estimates / revisions
    recommendation_mean: float | None = None  # 1=strong buy .. 5=sell
    num_analysts: int | None = None
    eps_rev_up_30d: int | None = None
    eps_rev_down_30d: int | None = None
    earnings_growth_next_q: float | None = None
    earnings_growth_next_y: float | None = None
    # Targets (third-party analyst consensus — attributed, not our target)
    target_low: float | None = None
    target_mean: float | None = None
    target_high: float | None = None
    # Risk / liquidity
    market_cap: float | None = None
    avg_volume: float | None = None
    # Income (ETFs / dividend payers)
    dividend_yield: float | None = None


class EdgarFacts(BaseModel):
    """Official point-in-time financial facts from SEC EDGAR XBRL (companyconcept).

    Used to fill the Capital Migration Score components that require filings —
    capital expenditure growth and R&D growth — which we never estimate from
    price (spec §25). ``None`` fields mean the concept was not reported/available.
    """

    model_config = ConfigDict(extra="forbid")

    ticker: str
    cik: str
    as_of: datetime
    source: str = "sec_edgar"
    capex_latest: float | None = None
    capex_prior: float | None = None
    capex_growth_yoy: float | None = None
    rnd_latest: float | None = None
    rnd_prior: float | None = None
    rnd_growth_yoy: float | None = None
    fiscal_year: int | None = None
