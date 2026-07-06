"""Market & Index Watchers: S&P 500 / Nasdaq / Dow / NYSE (spec §7-10, §35)."""

from __future__ import annotations

from fastapi import APIRouter

from us_watcher.market.schemas import IndexWatcherResponse
from us_watcher.market.service import get_market_service

router = APIRouter(tags=["indices"])


@router.get("/indices/sp500", response_model=IndexWatcherResponse)
async def sp500() -> IndexWatcherResponse:
    return await get_market_service().build_index_watcher("SP500")


@router.get("/indices/nasdaq", response_model=IndexWatcherResponse)
async def nasdaq() -> IndexWatcherResponse:
    return await get_market_service().build_index_watcher("NASDAQ")


@router.get("/indices/dow", response_model=IndexWatcherResponse)
async def dow() -> IndexWatcherResponse:
    return await get_market_service().build_index_watcher("DOW")


@router.get("/indices/nyse", response_model=IndexWatcherResponse)
async def nyse() -> IndexWatcherResponse:
    return await get_market_service().build_index_watcher("NYSE")
