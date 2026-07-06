"""News Scrapbook endpoints (spec §28, §35)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from us_watcher.api.deps import require_operator
from us_watcher.db.repositories import get_news_cluster, list_news_clusters

router = APIRouter(tags=["news"])


@router.get("/news")
async def news(limit: int = Query(default=40, le=200)) -> dict:
    clusters = await list_news_clusters(limit=limit)
    return {
        "count": len(clusters),
        "clusters": clusters,
        "empty_note": None if clusters else "No news ingested yet. Run the news pipeline.",
    }


@router.get("/news/clusters/{cluster_id}")
async def news_cluster(cluster_id: str) -> dict:
    cluster = await get_news_cluster(cluster_id)
    if cluster is None:
        raise HTTPException(404, "Cluster not found.")
    return cluster


@router.post("/pipelines/news-sync", dependencies=[Depends(require_operator)])
async def news_sync() -> dict:
    from us_watcher.newsfeed.service import sync_news

    return await sync_news()
