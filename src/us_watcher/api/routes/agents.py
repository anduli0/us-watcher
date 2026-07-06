"""Agent org + orchestrator-run endpoints (spec §16-19, §34, §35, §36 SSE)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from us_watcher.api.deps import require_operator
from us_watcher.db.repositories import (
    get_orchestrator_run,
    latest_orchestrator_run_full,
    list_orchestrator_runs,
)
from us_watcher.domain.agents.catalog import org_chart

router = APIRouter(tags=["agents"])


@router.get("/agents/stream")
async def agents_stream() -> StreamingResponse:
    """Server-Sent Events: replay the latest committee run agent-by-agent (spec
    §34/§36). Read-only; the UI uses a polling fallback if the stream is buffered
    (e.g. behind a proxy)."""

    async def gen() -> AsyncIterator[str]:
        run = await latest_orchestrator_run_full()
        if run is None:
            yield f"data: {json.dumps({'type': 'empty'})}\n\n"
            return
        payload = run.get("payload") or {}
        start = {"type": "start", "run_id": run["id"], "objective": run["objective"], "runtime": run["runtime"]}
        yield f"data: {json.dumps(start)}\n\n"
        for a in payload.get("agents", []):
            yield f"data: {json.dumps({'type': 'agent', **a})}\n\n"
            await asyncio.sleep(0.25)
        done = {"type": "done", "aggregate": payload.get("aggregate", {}), "chief": payload.get("chief", {})}
        yield f"data: {json.dumps(done)}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.get("/agents/org")
async def agents_org() -> dict:
    return org_chart()


@router.get("/agents/runs")
async def agent_runs(limit: int = Query(default=20, le=100)) -> dict:
    return {"runs": await list_orchestrator_runs(limit=limit)}


@router.get("/runs/{run_id}")
async def run_detail(run_id: str) -> dict:
    run = await get_orchestrator_run(run_id)
    if run is None:
        raise HTTPException(404, "Run not found.")
    return run


@router.post("/orchestrator/run", dependencies=[Depends(require_operator)])
async def orchestrator_run(objective: str = Query(default="market_overview")) -> dict:
    from us_watcher.agent_service.orchestrator import run_orchestrator

    return await run_orchestrator(objective=objective, trigger="manual")
