"""Async read/write helpers over the ORM models.

Read helpers are empty-safe (return ``[]`` / ``None`` when nothing is persisted)
so every surface renders an honest empty state before any pipeline has run.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import desc, select

from us_watcher.db.models import (
    AuditEvent,
    DailyBriefing,
    NewsCluster,
    OrchestratorRun,
    Recommendation,
)
from us_watcher.infrastructure.db import get_sessionmaker


# ---------------- recommendations ----------------
async def latest_recommendations(
    *, horizon: str | None = None, action: str | None = None, ticker: str | None = None
) -> list[dict[str, Any]]:
    sm = get_sessionmaker()
    async with sm() as s:
        stmt = select(Recommendation).order_by(desc(Recommendation.as_of))
        # horizon & ticker are constant within a lineage (lineage = ticker:horizon),
        # so they are safe to filter in SQL. ACTION is NOT — it changes across
        # revisions — so it must be applied AFTER picking the latest revision.
        if horizon:
            stmt = stmt.where(Recommendation.horizon == horizon)
        if ticker:
            stmt = stmt.where(Recommendation.ticker == ticker.upper())
        rows = (await s.execute(stmt)).scalars().all()
    # Keep only the latest revision per lineage FIRST. Filtering by action in SQL
    # would surface a STALE revision whose old action matched (e.g. a name now rated
    # "sell" reappearing under ?action=reduce with its pre-revision target) — which
    # is exactly how an out-of-date target could contradict the current call.
    seen: dict[str, Recommendation] = {}
    for r in rows:
        cur = seen.get(r.lineage_id)
        if cur is None or r.revision > cur.revision:
            seen[r.lineage_id] = r
    latest = list(seen.values())
    if action:
        latest = [r for r in latest if r.action == action]
    return [r.payload | {"_id": r.id, "_revision": r.revision} for r in latest]


async def recommendation_lineage(ticker: str) -> list[dict[str, Any]]:
    sm = get_sessionmaker()
    async with sm() as s:
        stmt = (
            select(Recommendation)
            .where(Recommendation.ticker == ticker.upper())
            .order_by(Recommendation.lineage_id, Recommendation.revision)
        )
        rows = (await s.execute(stmt)).scalars().all()
    return [
        {
            "id": r.id,
            "lineage_id": r.lineage_id,
            "revision": r.revision,
            "change_type": r.change_type,
            "action": r.action,
            "horizon": r.horizon,
            "total_score": r.total_score,
            "as_of": r.as_of.isoformat(),
        }
        for r in rows
    ]


async def save_recommendation(
    rec: dict, *, ticker: str, horizon: str, action: str, total_score: float, confidence: float,
    one_line: str, asset_type: str, company_name: str, as_of: datetime,
    expires_at: datetime | None = None,
    data_freshness: str = "mixed", orchestrator_run_id: str | None = None,
) -> dict:
    """Append a recommendation revision (immutable; never overwrite, spec §32.5).

    lineage = ticker:horizon. If the latest revision's action differs, this row
    is an upgrade/downgrade; if same, a reaffirmation; if none exists, initial.
    """
    import uuid

    lineage_id = f"{ticker.upper()}:{horizon}"
    sm = get_sessionmaker()
    async with sm() as s:
        stmt = (
            select(Recommendation)
            .where(Recommendation.lineage_id == lineage_id)
            .order_by(desc(Recommendation.revision))
            .limit(1)
        )
        prev = (await s.execute(stmt)).scalars().first()
        if prev is None:
            revision, change_type = 1, "initial"
        else:
            revision = prev.revision + 1
            change_type = _change_type(prev.action, action)
        row = Recommendation(
            id=uuid.uuid4().hex, lineage_id=lineage_id, revision=revision, change_type=change_type,
            ticker=ticker.upper(), company_name=company_name, asset_type=asset_type, horizon=horizon,
            action=action, total_score=total_score, confidence=confidence, one_line_thesis=one_line,
            as_of=as_of, expires_at=expires_at, data_freshness=data_freshness, payload=rec,
            orchestrator_run_id=orchestrator_run_id,
        )
        s.add(row)
        await s.commit()
    return {"id": row.id, "lineage_id": lineage_id, "revision": revision, "change_type": change_type}


_ACTION_RANK = {
    "avoid": 0, "sell": 1, "reduce": 2, "watch": 3, "hold": 4,
    "accumulate": 5, "buy": 6, "strong_buy": 7,
}


def _change_type(old: str, new: str) -> str:
    if old == new:
        return "reaffirm"
    return "upgrade" if _ACTION_RANK.get(new, 0) > _ACTION_RANK.get(old, 0) else "downgrade"


# ---------------- news ----------------
async def list_news_clusters(*, limit: int = 40) -> list[dict[str, Any]]:
    sm = get_sessionmaker()
    async with sm() as s:
        stmt = select(NewsCluster).order_by(desc(NewsCluster.last_seen)).limit(limit)
        rows = (await s.execute(stmt)).scalars().all()
    return [
        {
            "id": c.id,
            "headline": c.headline,
            "summary": c.summary,
            "importance": c.importance,
            "article_count": c.article_count,
            "last_seen": c.last_seen.isoformat(),
            "related": c.related,
        }
        for c in rows
    ]


async def get_news_cluster(cluster_id: str) -> dict[str, Any] | None:
    sm = get_sessionmaker()
    async with sm() as s:
        c = await s.get(NewsCluster, cluster_id)
    if c is None:
        return None
    return {
        "id": c.id,
        "headline": c.headline,
        "summary": c.summary,
        "importance": c.importance,
        "article_count": c.article_count,
        "first_seen": c.first_seen.isoformat(),
        "last_seen": c.last_seen.isoformat(),
        "related": c.related,
    }


# ---------------- briefings ----------------
async def latest_briefing(*, language: str = "en", briefing_type: str = "full") -> dict[str, Any] | None:
    sm = get_sessionmaker()
    async with sm() as s:
        stmt = (
            select(DailyBriefing)
            .where(DailyBriefing.language == language, DailyBriefing.briefing_type == briefing_type)
            .order_by(desc(DailyBriefing.briefing_date))
            .limit(1)
        )
        row = (await s.execute(stmt)).scalars().first()
    return _briefing_dict(row)


async def briefing_by_date(date: str, *, language: str = "en", briefing_type: str = "full") -> dict[str, Any] | None:
    sm = get_sessionmaker()
    async with sm() as s:
        stmt = select(DailyBriefing).where(
            DailyBriefing.briefing_date == date,
            DailyBriefing.language == language,
            DailyBriefing.briefing_type == briefing_type,
        )
        row = (await s.execute(stmt)).scalars().first()
    return _briefing_dict(row)


async def briefing_archive(*, language: str = "en", limit: int = 30) -> list[dict[str, Any]]:
    sm = get_sessionmaker()
    async with sm() as s:
        stmt = (
            select(DailyBriefing)
            .where(DailyBriefing.language == language)
            .order_by(desc(DailyBriefing.briefing_date))
            .limit(limit)
        )
        rows = (await s.execute(stmt)).scalars().all()
    return [
        {
            "briefing_date": r.briefing_date,
            "briefing_type": r.briefing_type,
            "headline": r.headline,
            "language": r.language,
        }
        for r in rows
    ]


def _briefing_dict(row: DailyBriefing | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "briefing_date": row.briefing_date,
        "briefing_type": row.briefing_type,
        "language": row.language,
        "headline": row.headline,
        "payload": row.payload,
        "generated_by": row.generated_by,
        "created_at": row.created_at.isoformat(),
    }


# ---------------- orchestrator runs ----------------
async def list_orchestrator_runs(*, limit: int = 20) -> list[dict[str, Any]]:
    sm = get_sessionmaker()
    async with sm() as s:
        stmt = select(OrchestratorRun).order_by(desc(OrchestratorRun.started_at)).limit(limit)
        rows = (await s.execute(stmt)).scalars().all()
    return [
        {
            "id": r.id,
            "objective": r.objective,
            "trigger": r.trigger,
            "status": r.status,
            "selected_agents": r.selected_agents,
            "runtime": r.runtime,
            "token_usage": r.token_usage,
            "started_at": r.started_at.isoformat(),
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        }
        for r in rows
    ]


async def latest_orchestrator_run_full() -> dict[str, Any] | None:
    sm = get_sessionmaker()
    async with sm() as s:
        stmt = select(OrchestratorRun).order_by(desc(OrchestratorRun.started_at)).limit(1)
        r = (await s.execute(stmt)).scalars().first()
    if r is None:
        return None
    return {
        "id": r.id, "objective": r.objective, "runtime": r.runtime,
        "started_at": r.started_at.isoformat(), "payload": r.payload,
    }


async def get_orchestrator_run(run_id: str) -> dict[str, Any] | None:
    sm = get_sessionmaker()
    async with sm() as s:
        r = await s.get(OrchestratorRun, run_id)
    if r is None:
        return None
    return {
        "id": r.id,
        "objective": r.objective,
        "trigger": r.trigger,
        "status": r.status,
        "selected_agents": r.selected_agents,
        "runtime": r.runtime,
        "token_usage": r.token_usage,
        "cost_usd": r.cost_usd,
        "started_at": r.started_at.isoformat(),
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        "payload": r.payload,
    }


# ---------------- pipeline locks (idempotency / duplicate-run prevention) ----------------
async def try_acquire_lock(key: str, *, holder: str, ttl_seconds: int = 1800) -> bool:
    """Best-effort lock: acquire if absent or expired. Returns True if acquired.

    Prevents duplicate/concurrent pipeline runs (spec §37). Not a hard
    distributed lock, but sufficient for a single-worker deployment and a guard
    against overlap.
    """
    from datetime import UTC, timedelta

    from us_watcher.db.models import PipelineLock
    from us_watcher.domain.time import now_utc

    now = now_utc()
    sm = get_sessionmaker()
    async with sm() as s:
        existing = await s.get(PipelineLock, key)
        # SQLite stores DateTime tz-naive; coerce to aware UTC before comparing.
        if existing is not None:
            exp = existing.expires_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=UTC)
            if exp > now:
                return False
        if existing is not None:
            existing.holder = holder
            existing.acquired_at = now
            existing.expires_at = now + timedelta(seconds=ttl_seconds)
        else:
            s.add(PipelineLock(key=key, holder=holder, acquired_at=now,
                               expires_at=now + timedelta(seconds=ttl_seconds)))
        await s.commit()
    return True


async def release_lock(key: str) -> None:
    from us_watcher.db.models import PipelineLock

    sm = get_sessionmaker()
    async with sm() as s:
        existing = await s.get(PipelineLock, key)
        if existing is not None:
            await s.delete(existing)
            await s.commit()


# ---------------- big-bets weekly snapshot ----------------
async def record_big_bets_weekly(iso_week: str, picks: list[dict[str, Any]], *, as_of: str) -> bool:
    """Persist the week's Big-Bet (🐋 대어) picks ONCE per ISO week (idempotent).

    Long-horizon conviction calls should not churn daily, so the list is frozen
    per ISO week; the first pipeline run of a new week writes it and later runs
    no-op. Returns True if a new snapshot was written, False if it already existed.
    """
    sm = get_sessionmaker()
    async with sm() as s:
        existing = (await s.execute(
            select(AuditEvent)
            .where(AuditEvent.action == "big_bets.weekly", AuditEvent.entity_id == iso_week)
            .limit(1)
        )).scalars().first()
        if existing is not None:
            return False
        s.add(AuditEvent(
            action="big_bets.weekly", entity_type="recommendations", entity_id=iso_week,
            summary=f"Big-Bet weekly snapshot {iso_week}: {len(picks)} picks",
            payload={"iso_week": iso_week, "as_of": as_of, "picks": picks},
        ))
        await s.commit()
        return True


async def latest_big_bets() -> dict[str, Any] | None:
    """The most recent weekly Big-Bet snapshot payload (``None`` until first run)."""
    sm = get_sessionmaker()
    async with sm() as s:
        row = (await s.execute(
            select(AuditEvent)
            .where(AuditEvent.action == "big_bets.weekly")
            .order_by(desc(AuditEvent.created_at))
            .limit(1)
        )).scalars().first()
    return row.payload if row is not None else None


# ---------------- audit ----------------
async def add_audit_event(
    action: str, summary: str, *, entity_type: str | None = None, entity_id: str | None = None,
    payload: dict | None = None,
) -> None:
    sm = get_sessionmaker()
    async with sm() as s:
        s.add(AuditEvent(
            action=action, summary=summary, entity_type=entity_type,
            entity_id=entity_id, payload=payload or {},
        ))
        await s.commit()


async def utcnow() -> datetime:  # convenience for callers needing a tz-aware now
    from us_watcher.domain.time import now_utc

    return now_utc()
