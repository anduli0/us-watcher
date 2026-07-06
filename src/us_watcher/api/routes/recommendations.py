"""AI Recommendations endpoints (spec §21-26, §35).

Reads the immutable recommendation history and returns the latest revision per
lineage. Generation is a protected pipeline (POST /pipelines/recommendations).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from us_watcher.api.deps import require_operator
from us_watcher.db.repositories import (
    latest_big_bets,
    latest_recommendations,
    recommendation_lineage,
)

router = APIRouter(tags=["recommendations"])


@router.get("/recommendations")
async def recommendations(
    horizon: str | None = Query(default=None),
    action: str | None = Query(default=None),
    ticker: str | None = Query(default=None),
    language: str = Query(default="en"),
) -> dict:
    items = await latest_recommendations(horizon=horizon, action=action, ticker=ticker)
    return {
        "count": len(items),
        "language": language,
        "recommendations": items,
        "empty_note": None if items else "No recommendations generated yet. Run the recommendation pipeline.",
    }


@router.get("/recommendations/big-bets")
async def big_bets() -> dict:
    """The weekly 🐋 대어 (Big-Bet) snapshot — frozen per ISO week, refreshed on the
    first recommendation run of each new week (defined before /{ticker} so it is not
    matched as a ticker)."""
    snap = await latest_big_bets()
    if snap is None:
        return {"iso_week": None, "as_of": None, "picks": []}
    return snap


@router.get("/recommendations/{ticker}")
async def recommendation_detail(ticker: str) -> dict:
    items = await latest_recommendations(ticker=ticker)
    return {"ticker": ticker.upper(), "recommendations": items}


@router.get("/recommendations/history/{ticker}")
async def recommendation_history(ticker: str) -> dict:
    history = await recommendation_lineage(ticker)
    return {"ticker": ticker.upper(), "history": history}


@router.post("/pipelines/recommendations", dependencies=[Depends(require_operator)])
async def run_recommendations() -> dict:
    from us_watcher.agent_service.recommendation_pipeline import generate_recommendations

    result = await generate_recommendations()
    return result
