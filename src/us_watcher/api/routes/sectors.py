"""Sector & Rotation endpoints (spec §11, §35)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from us_watcher.market.schemas import RotationResponse
from us_watcher.market.service import get_market_service

router = APIRouter(tags=["sectors"])


@router.get("/rotation", response_model=RotationResponse)
async def rotation() -> RotationResponse:
    return await get_market_service().build_rotation()


@router.get("/sectors", response_model=RotationResponse)
async def sectors() -> RotationResponse:
    return await get_market_service().build_rotation()


@router.get("/sectors/{symbol}")
async def sector_detail(symbol: str) -> dict:
    rot = await get_market_service().build_rotation()
    for row in rot.sectors:
        if row.symbol.upper() == symbol.upper():
            return row.model_dump()
    raise HTTPException(404, f"Sector {symbol} not found.")
