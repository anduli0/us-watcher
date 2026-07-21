"""News ingestion: fetch → sanitize → dedup → cluster → importance → persist.

Implements spec §28. Stores only titles + metadata (no full text). Twenty
articles about one event become ONE cluster. Importance is multi-factor (not
sentiment/popularity alone). Injection-flagged items are kept as data, logged,
and never executed.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
import uuid
from collections.abc import Iterable
from datetime import datetime, timedelta
from functools import lru_cache

from sqlalchemy import select

from us_watcher.config import get_settings
from us_watcher.db.models import DataQualityEvent, NewsArticle, NewsCluster
from us_watcher.db.repositories import add_audit_event
from us_watcher.domain.time import now_utc
from us_watcher.infrastructure.db import get_sessionmaker
from us_watcher.infrastructure.news.base import RawNewsItem
from us_watcher.infrastructure.news.factory import get_news_provider
from us_watcher.security.sanitize import sanitize_text

_STOP = {"the", "a", "an", "to", "of", "in", "on", "as", "is", "are", "for", "and", "with", "at", "by", "ahead"}
_WORD_RE = re.compile(r"[a-z0-9]+")

# Entity dictionaries for tagging (spec §28.2).
_INDEX_TAGS = {"s&p": "SPX", "sp 500": "SPX", "nasdaq": "NDX", "dow": "DJI", "russell": "RUT", "nyse": "NYA"}
_SECTOR_TAGS = {
    "semiconductor": "XLK", "chip": "XLK", "tech": "XLK", "software": "XLK", "ai": "XLK",
    "bank": "XLF", "financial": "XLF", "energy": "XLE", "oil": "XLE", "health": "XLV",
    "utility": "XLU", "industrial": "XLI", "real estate": "XLRE",
}
_MACRO_TAGS = {"fed": "fed", "interest rate": "rates", "inflation": "inflation", "cpi": "inflation",
               "jobs": "labor", "treasury": "rates", "yield": "rates", "tariff": "trade"}


def normalize_title(title: str) -> str:
    tokens = [t for t in _WORD_RE.findall(title.lower()) if t not in _STOP and len(t) > 2]
    return " ".join(sorted(set(tokens)))


def _token_set(title: str) -> set[str]:
    return {t for t in _WORD_RE.findall(title.lower()) if t not in _STOP and len(t) > 2}


def _content_hash(norm: str) -> str:
    return hashlib.sha256(norm.encode()).hexdigest()[:32]


def _extract_entities(title: str) -> dict:
    low = title.lower()
    return {
        "indices": sorted({v for k, v in _INDEX_TAGS.items() if k in low}),
        "sectors": sorted({v for k, v in _SECTOR_TAGS.items() if k in low}),
        "macro": sorted({v for k, v in _MACRO_TAGS.items() if k in low}),
        "securities": [],  # ticker tags are attributed from the fetch topic, not the title
    }


@lru_cache(maxsize=1)
def _stock_query_map(limit: int) -> dict[str, str]:
    """Map ``"<name> stock"`` query -> ticker for the first ``limit`` stock-universe
    names. The provider echoes the query as each article's ``topic``, so returned
    articles attribute unambiguously to that ticker (no fuzzy name matching)."""
    from us_watcher.domain.universe import get_universe

    out: dict[str, str] = {}
    for inst in get_universe().stocks[: max(0, limit)]:
        out[f"{inst.name} stock"] = inst.symbol
    return out


def _entity_importance(related: dict) -> float:
    return min(1.0, 0.2 * len(related["indices"]) + 0.15 * len(related["sectors"]) + 0.1 * len(related["macro"]))


def _recency_weight(published_at: datetime) -> float:
    age_h = max(0.0, (now_utc() - published_at).total_seconds() / 3600.0)
    return math.exp(-age_h / 36.0)  # ~half-life over a day and a half


def _importance(reliability: float, related: dict, cluster_size: int, published_at: datetime) -> float:
    confirm = min(1.0, math.log(cluster_size + 1, 4))
    score = (
        0.30 * reliability
        + 0.30 * _entity_importance(related)
        + 0.20 * confirm
        + 0.20 * _recency_weight(published_at)
    )
    return round(score * 100.0, 1)


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


async def sync_news() -> dict:
    settings = get_settings()
    provider = get_news_provider()
    # Macro/theme topics + per-stock name queries (topic → ticker map). Company
    # news is what lets the news_catalyst component see product launches & guidance.
    stock_map = _stock_query_map(settings.news_stock_query_limit)
    topics = [*settings.news_topics, *stock_map.keys()]

    raw_lists = await asyncio.gather(*(provider.fetch(t) for t in topics), return_exceptions=True)
    raw_items: list[RawNewsItem] = []
    for r in raw_lists:
        if isinstance(r, BaseException):
            continue
        raw_items.extend(r)

    # sanitize + dedup
    seen: dict[str, dict] = {}
    injection_flags = 0
    for raw in raw_items:
        clean_title, hits = sanitize_text(raw.title)
        if hits:
            injection_flags += 1
        norm = normalize_title(clean_title)
        if not norm:
            continue
        chash = _content_hash(norm)
        if chash in seen:
            continue
        related = _extract_entities(clean_title)
        ticker = stock_map.get(raw.topic)
        if ticker:
            related["securities"] = [ticker]
        seen[chash] = {
            "id": chash, "title": clean_title, "normalized_title": norm, "url": raw.url,
            "publisher": raw.publisher, "published_at": raw.published_at, "related": related,
            "tokens": _token_set(clean_title), "injection": bool(hits),
            "reliability": 0.5 if raw.publisher else 0.4,
        }

    # greedy clustering by token overlap within a time window
    clusters = _cluster(seen.values())

    pruned = await _persist(seen, clusters, injection_flags, settings.news_retention_days)
    await add_audit_event("news.synced", f"Ingested {len(seen)} articles in {len(clusters)} clusters",
                          payload={"injection_flags": injection_flags, "pruned": pruned})
    return {
        "fetched": len(raw_items), "stored_articles": len(seen), "clusters": len(clusters),
        "injection_flags": injection_flags, "pruned": pruned, "as_of": now_utc().isoformat(),
        "provider": provider.name,
    }


def _cluster(articles: Iterable[dict]) -> list[dict]:
    arts = sorted(articles, key=lambda a: a["published_at"], reverse=True)
    clusters: list[dict] = []
    for art in arts:
        placed = False
        for cl in clusters:
            within = abs((art["published_at"] - cl["anchor_time"]).total_seconds()) < 36 * 3600
            if within and _jaccard(art["tokens"], cl["tokens"]) >= 0.5:
                cl["members"].append(art)
                cl["tokens"] |= art["tokens"]
                placed = True
                break
        if not placed:
            clusters.append({
                "id": uuid.uuid4().hex[:16], "anchor_time": art["published_at"],
                "tokens": set(art["tokens"]), "members": [art],
            })
    return clusters


async def _persist(seen: dict, clusters: list[dict], injection_flags: int, retention_days: int) -> int:
    sm = get_sessionmaker()
    cutoff = now_utc() - timedelta(days=retention_days)
    async with sm() as s:
        # prune old articles (retention, spec §28.1)
        old = (await s.execute(select(NewsArticle).where(NewsArticle.published_at < cutoff))).scalars().all()
        pruned = len(old)
        for a in old:
            await s.delete(a)

        for cl in clusters:
            members = cl["members"]
            size = len(members)
            related = _merge_related([m["related"] for m in members])
            importance = max(_importance(m["reliability"], m["related"], size, m["published_at"]) for m in members)
            headline = max(members, key=lambda m: len(m["title"]))["title"]
            last_seen = max(m["published_at"] for m in members)
            existing = await s.get(NewsCluster, cl["id"])
            if existing is None:
                s.add(NewsCluster(
                    id=cl["id"], headline=headline, summary=None, importance=importance,
                    article_count=size, last_seen=last_seen, related=related))
            for m in members:
                if await s.get(NewsArticle, m["id"]) is not None:
                    continue
                s.add(NewsArticle(
                    id=m["id"], title=m["title"], normalized_title=m["normalized_title"],
                    url=m["url"], publisher=m["publisher"], published_at=m["published_at"],
                    importance=importance, reliability=m["reliability"], cluster_id=cl["id"],
                    related=m["related"], content_hash=m["id"]))
                if m["injection"]:
                    s.add(DataQualityEvent(kind="prompt_injection_flagged", detail=m["title"][:300]))
        await s.commit()
    return pruned


def _merge_related(items: list[dict]) -> dict:
    out: dict[str, set[str]] = {"indices": set(), "sectors": set(), "macro": set(), "securities": set()}
    for it in items:
        for k in out:
            out[k].update(it.get(k, []))
    return {k: sorted(v) for k, v in out.items()}
