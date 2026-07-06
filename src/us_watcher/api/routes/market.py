"""Market overview / regime / cross-asset endpoints (spec §6, §35)."""

from __future__ import annotations

from fastapi import APIRouter

from us_watcher.market.schemas import OverviewResponse
from us_watcher.market.service import get_market_service

router = APIRouter(tags=["market"])


@router.get("/market/overview", response_model=OverviewResponse)
async def overview() -> OverviewResponse:
    return await get_market_service().build_overview()


@router.get("/market/regime")
async def regime() -> dict:
    ov = await get_market_service().build_overview()
    return ov.pulse.model_dump()


@router.get("/market/cross-assets")
async def cross_assets() -> dict:
    ov = await get_market_service().build_overview()
    groups = {"rates", "fx", "commodity", "crypto", "vol"}
    return {
        "as_of": ov.as_of.isoformat(),
        "cards": [c.model_dump() for c in ov.cards if c.group in groups],
    }
