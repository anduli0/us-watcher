"""Accuracy & Methodology endpoints (spec §32, §35)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from us_watcher.accuracy.methodology import METHODOLOGY
from us_watcher.accuracy.service import accuracy_summary
from us_watcher.api.deps import require_operator

router = APIRouter(tags=["accuracy"])


@router.get("/accuracy")
async def accuracy() -> dict:
    return await accuracy_summary()


@router.get("/methodology")
async def methodology() -> dict:
    return METHODOLOGY


@router.post("/pipelines/evaluate-recommendations", dependencies=[Depends(require_operator)])
async def evaluate() -> dict:
    from us_watcher.accuracy.evaluate import evaluate_recommendations

    return await evaluate_recommendations()
