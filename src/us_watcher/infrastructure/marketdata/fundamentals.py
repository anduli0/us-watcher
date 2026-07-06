"""Keyless Yahoo fundamentals provider (quoteSummary + crumb flow).

Yahoo's quoteSummary requires a session cookie + crumb. We fetch those once
(lazily), cache them, and refresh once on a 401. NEVER raises — returns ``None``
on any failure so the recommendation engine degrades to the technical tier. All
values are point-in-time as of fetch (`as_of`); analyst target prices are stored
as THIRD-PARTY consensus (attributed), never as our own fabricated target.
"""

from __future__ import annotations

import asyncio

import httpx

from us_watcher.domain.fundamentals import FundamentalSnapshot
from us_watcher.domain.time import now_utc
from us_watcher.infrastructure.http import new_async_client

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_MODULES = "financialData,defaultKeyStatistics,earningsTrend,summaryDetail,price"


def _raw(node: dict | None, key: str) -> float | None:
    if not node:
        return None
    v = node.get(key)
    if isinstance(v, dict):
        v = v.get("raw")
    return float(v) if isinstance(v, int | float) else None


def _int(node: dict | None, key: str) -> int | None:
    v = _raw(node, key)
    return int(v) if v is not None else None


class YahooFundamentalsProvider:
    name = "yahoo"

    def __init__(self, *, timeout: float = 10.0) -> None:
        self._timeout = timeout
        self._crumb: str | None = None
        self._client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()

    async def _ensure_session(self, force: bool = False) -> bool:
        async with self._lock:
            if self._client is None:
                self._client = new_async_client(headers={"User-Agent": _UA}, timeout=self._timeout)
            if self._crumb and not force:
                return True
            try:
                await self._client.get("https://fc.yahoo.com")
                resp = await self._client.get("https://query1.finance.yahoo.com/v1/test/getcrumb")
                crumb = resp.text.strip()
                if resp.status_code == 200 and crumb and "<" not in crumb:
                    self._crumb = crumb
                    return True
            except httpx.HTTPError:
                return False
            return False

    async def get_fundamentals(self, symbol: str) -> FundamentalSnapshot | None:
        if not await self._ensure_session():
            return None
        data = await self._fetch(symbol)
        if data is None:
            # crumb may have expired; refresh once and retry
            if not await self._ensure_session(force=True):
                return None
            data = await self._fetch(symbol)
        if data is None:
            return None
        return self._parse(symbol, data)

    async def _fetch(self, symbol: str) -> dict | None:
        if self._client is None:
            return None
        url = f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
        try:
            resp = await self._client.get(url, params={"modules": _MODULES, "crumb": self._crumb})
            if resp.status_code == 401:
                self._crumb = None
                return None
            if resp.status_code != 200:
                return None
            result = resp.json().get("quoteSummary", {}).get("result")
            return result[0] if result else None
        except (httpx.HTTPError, ValueError, KeyError, IndexError):
            return None

    def _parse(self, symbol: str, d: dict) -> FundamentalSnapshot:
        fd = d.get("financialData", {})
        ks = d.get("defaultKeyStatistics", {})
        sd = d.get("summaryDetail", {})
        et = d.get("earningsTrend", {}).get("trend", [])
        # earnings revisions: next-quarter (index 0..) — find +1q and +1y entries
        rev_up = rev_down = None
        g_q = g_y = None
        for t in et:
            period = t.get("period")
            revs = t.get("epsRevisions", {})
            growth = _raw(t, "growth")
            if period == "+1q":
                rev_up = _int(revs, "upLast30days")
                rev_down = _int(revs, "downLast30days")
                g_q = growth
            elif period == "+1y":
                g_y = growth
        return FundamentalSnapshot(
            symbol=symbol, as_of=now_utc(),
            profit_margin=_raw(fd, "profitMargins"),
            operating_margin=_raw(fd, "operatingMargins"),
            gross_margin=_raw(fd, "grossMargins"),
            return_on_equity=_raw(fd, "returnOnEquity"),
            revenue_growth=_raw(fd, "revenueGrowth"),
            earnings_growth=_raw(fd, "earningsGrowth"),
            free_cashflow=_raw(fd, "freeCashflow"),
            total_debt=_raw(fd, "totalDebt"),
            debt_to_equity=_raw(fd, "debtToEquity"),
            trailing_pe=_raw(sd, "trailingPE"),
            forward_pe=_raw(ks, "forwardPE") or _raw(sd, "forwardPE"),
            peg_ratio=_raw(ks, "pegRatio"),
            price_to_book=_raw(ks, "priceToBook"),
            recommendation_mean=_raw(fd, "recommendationMean"),
            num_analysts=_int(fd, "numberOfAnalystOpinions"),
            eps_rev_up_30d=rev_up, eps_rev_down_30d=rev_down,
            earnings_growth_next_q=g_q, earnings_growth_next_y=g_y,
            target_low=_raw(fd, "targetLowPrice"),
            target_mean=_raw(fd, "targetMeanPrice"),
            target_high=_raw(fd, "targetHighPrice"),
            market_cap=_raw(sd, "marketCap") or _raw(ks, "enterpriseValue"),
            avg_volume=_raw(sd, "averageVolume"),
            dividend_yield=_raw(sd, "yield") or _raw(sd, "dividendYield") or _raw(sd, "trailingAnnualDividendYield"),
        )

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
