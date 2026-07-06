"""Macro & Policy endpoint (spec §13).

Serves the deterministic macro spine (rates, curve) from FRED keyless data and a
nonpartisan policy-transmission scaffold. Narrative policy analysis is produced
by the agent layer; this endpoint provides the factual, calculated base.
"""

from __future__ import annotations

import time

from fastapi import APIRouter

from us_watcher.domain.time import now_utc
from us_watcher.infrastructure.macro.fred import FredProvider

router = APIRouter(tags=["macro"])

# Macro yields are daily series — caching the assembled response keeps the page
# snappy and avoids re-hitting FRED (6 series) on every load. ``_last_good`` is
# served if a refresh fails so a FRED hiccup never blanks the page.
_MACRO_TTL = 180.0
_macro_cache: dict[str, tuple[float, dict]] = {}
_macro_last_good: dict[str, dict] = {}

# FRED series for the macro spine. Keyless CSV serves latest revised values.
_SERIES = {
    "DGS2": "US 2-Year Treasury Yield",
    "DGS10": "US 10-Year Treasury Yield",
    "T10Y2Y": "10Y–2Y Spread",
    "DFF": "Effective Federal Funds Rate",
    "T10YIE": "10-Year Breakeven Inflation",
    "DGS10-DFII10": "10-Year Real Yield (DFII10)",
}


@router.get("/macro")
async def macro() -> dict:
    hit = _macro_cache.get("macro")
    if hit is not None and time.monotonic() - hit[0] < _MACRO_TTL:
        return hit[1]
    fred = FredProvider()
    series = await fred.get_many(["DGS2", "DGS10", "T10Y2Y", "DFF", "T10YIE", "DFII10"])
    if not series and "macro" in _macro_last_good:
        return _macro_last_good["macro"]  # FRED unreachable — serve last good
    items = []
    for sid, name in [
        ("DFF", "Effective Federal Funds Rate"),
        ("DGS2", "US 2-Year Treasury Yield"),
        ("DGS10", "US 10-Year Treasury Yield"),
        ("T10Y2Y", "10Y–2Y Spread"),
        ("DFII10", "10-Year Real Yield"),
        ("T10YIE", "10-Year Breakeven Inflation"),
    ]:
        obs = series.get(sid)
        items.append(
            {
                "series_id": sid,
                "name": name,
                "value": obs.value if obs else None,
                "observation_date": obs.observation_date.isoformat() if obs else None,
                "available_at": obs.available_at.isoformat() if obs else None,
                "source": "fred",
                "status": (obs.status.value if obs else "UNAVAILABLE"),
            }
        )
    curve = series.get("T10Y2Y")
    transmission = {
        "chain": [
            "Policy development",
            "Rates / taxes / tariffs / regulation / spending / liquidity",
            "Industry cost, demand, supply-chain, investment effects",
            "Corporate earnings & valuation",
            "Index / sector / security prices",
        ],
        "note_en": "Distinguish proposal vs. enacted policy; do not confuse rhetoric with implementation.",
        "note_ko": "제안과 시행된 정책을 구분하고, 수사(레토릭)를 실제 시행과 혼동하지 않습니다.",
        "curve_state": (
            "inverted" if curve and curve.value < 0 else "positive" if curve else "unavailable"
        ),
    }
    result = {"as_of": now_utc().isoformat(), "series": items, "policy_transmission": transmission}
    _macro_cache["macro"] = (time.monotonic(), result)
    if series:  # only retain as last-good when we actually got fresh data
        _macro_last_good["macro"] = result
    return result
