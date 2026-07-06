"""SEC EDGAR provider — official, keyless company financial facts (spec §14.1).

Uses the XBRL ``companyconcept`` API to pull annual (10-K, full-year) capital
expenditure and R&D, computing YoY growth for the Capital Migration Score. SEC
requires a declared User-Agent with a contact; we send one. NEVER raises —
returns ``None`` so the CMS simply reweights those components out when EDGAR is
unavailable. Rate-limited (<=10 req/s); we fetch only small per-concept series.
"""

from __future__ import annotations

import asyncio

import httpx

from us_watcher.domain.fundamentals import EdgarFacts
from us_watcher.domain.time import now_utc
from us_watcher.infrastructure.http import new_async_client

_UA = "US-WATCHER/0.1 (research; minkyu494@gmail.com)"
_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_CONCEPT_URL = "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{tag}.json"

# Preferred XBRL tags (first that resolves wins).
_CAPEX_TAGS = ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"]
_RND_TAGS = ["ResearchAndDevelopmentExpense"]


class EdgarProvider:
    name = "sec_edgar"

    def __init__(self, *, timeout: float = 12.0) -> None:
        self._timeout = timeout
        self._cik_map: dict[str, str] | None = None
        self._client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = new_async_client(
                headers={"User-Agent": _UA, "Accept-Encoding": "gzip"}, timeout=self._timeout)
        return self._client

    async def _cik_for(self, ticker: str) -> str | None:
        async with self._lock:
            if self._cik_map is None:
                self._cik_map = await self._load_cik_map()
        return self._cik_map.get(ticker.upper().replace("-", "."))  # BRK-B -> BRK.B on SEC

    async def _load_cik_map(self) -> dict[str, str]:
        try:
            client = await self._get_client()
            resp = await client.get(_TICKERS_URL)
            if resp.status_code != 200:
                return {}
            data = resp.json()
        except (httpx.HTTPError, ValueError):
            return {}
        out: dict[str, str] = {}
        for row in data.values():
            t = str(row.get("ticker", "")).upper()
            cik = str(row.get("cik_str", "")).zfill(10)
            if t:
                out[t] = cik
        return out

    async def _annual_series(self, cik: str, tags: list[str]) -> list[tuple[int, float]]:
        """Return [(fiscal_year, value)] for annual (10-K, FY) filings, newest last."""
        client = await self._get_client()
        for tag in tags:
            try:
                resp = await client.get(_CONCEPT_URL.format(cik=cik, tag=tag))
                if resp.status_code != 200:
                    continue
                units = resp.json().get("units", {}).get("USD", [])
            except (httpx.HTTPError, ValueError, KeyError):
                continue
            by_fy: dict[int, float] = {}
            for e in units:
                if e.get("form") == "10-K" and e.get("fp") == "FY" and isinstance(e.get("val"), int | float):
                    fy = e.get("fy")
                    if isinstance(fy, int):
                        by_fy[fy] = float(e["val"])  # later entries (restatements) overwrite
            if len(by_fy) >= 2:
                return sorted(by_fy.items())
        return []

    @staticmethod
    def _yoy(series: list[tuple[int, float]]) -> tuple[float | None, float | None, float | None, int | None]:
        if len(series) < 2:
            return None, None, None, (series[-1][0] if series else None)
        (_, prior), (fy, latest) = series[-2], series[-1]
        growth = (latest / prior - 1.0) if prior else None
        return latest, prior, growth, fy

    async def get_facts(self, ticker: str) -> EdgarFacts | None:
        cik = await self._cik_for(ticker)
        if cik is None:
            return None
        capex = await self._annual_series(cik, _CAPEX_TAGS)
        rnd = await self._annual_series(cik, _RND_TAGS)
        cx_l, cx_p, cx_g, fy = self._yoy(capex)
        rd_l, rd_p, rd_g, _ = self._yoy(rnd)
        if cx_l is None and rd_l is None:
            return None
        return EdgarFacts(
            ticker=ticker.upper(), cik=cik, as_of=now_utc(),
            capex_latest=cx_l, capex_prior=cx_p, capex_growth_yoy=cx_g,
            rnd_latest=rd_l, rnd_prior=rd_p, rnd_growth_yoy=rd_g, fiscal_year=fy,
        )

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
