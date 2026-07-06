"""Daily Brief endpoints (spec §30, §35)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from us_watcher.api.deps import require_operator
from us_watcher.db.repositories import (
    briefing_archive,
    briefing_by_date,
    latest_briefing,
)

router = APIRouter(tags=["briefings"])


@router.get("/briefings/latest")
async def briefings_latest(
    language: str = Query(default="en"),
    briefing_type: str = Query(default="full"),
) -> dict:
    brief = await latest_briefing(language=language, briefing_type=briefing_type)
    if brief is None:
        return {"empty_note": "No briefing generated yet. Run the daily-brief pipeline.", "briefing": None}
    return {"briefing": brief}


@router.get("/briefings/archive")
async def briefings_archive(language: str = Query(default="en"), limit: int = Query(default=30, le=180)) -> dict:
    return {"archive": await briefing_archive(language=language, limit=limit)}


@router.get("/briefings/{date}")
async def briefings_by_date(
    date: str,
    language: str = Query(default="en"),
    briefing_type: str = Query(default="full"),
) -> dict:
    brief = await briefing_by_date(date, language=language, briefing_type=briefing_type)
    if brief is None:
        raise HTTPException(404, f"No {briefing_type} briefing for {date} ({language}).")
    return {"briefing": brief}


@router.post("/pipelines/daily-brief", dependencies=[Depends(require_operator)])
async def daily_brief() -> dict:
    from us_watcher.briefing.service import generate_daily_brief

    return await generate_daily_brief()
