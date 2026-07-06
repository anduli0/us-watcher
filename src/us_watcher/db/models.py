"""ORM models (point-in-time integrity, append-only audit).

Dialect-agnostic: ``String`` for ids/decimals, ``JSON`` for structured payloads,
``DateTime(timezone=True)`` for timestamps — one schema runs on both SQLite
(aiosqlite) and Postgres (asyncpg). Recommendations are NEVER overwritten; the
history/outcome tables append (spec §32.5).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from us_watcher.db.types import DecimalString
from us_watcher.domain.time import now_utc
from us_watcher.infrastructure.db import Base


def _now() -> datetime:
    return now_utc()


class Instrument(Base):
    __tablename__ = "instruments"

    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    group: Mapped[str] = mapped_column(String(32))
    asset_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    market: Mapped[str | None] = mapped_column(String(32), nullable=True)
    gics: Mapped[str | None] = mapped_column(String(64), nullable=True)
    yahoo_symbol: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_proxy: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class MacroObservationRow(Base):
    """Point-in-time macro observations (spec §15: vintage preservation)."""

    __tablename__ = "macro_observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    series_id: Mapped[str] = mapped_column(String(64), index=True)
    observation_date: Mapped[str] = mapped_column(String(16))  # ISO date
    value: Mapped[float] = mapped_column(Float)
    vintage_date: Mapped[str | None] = mapped_column(String(16), nullable=True)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(32), default="fred")
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (Index("ix_macro_series_obs", "series_id", "observation_date", "vintage_date"),)


class RegimeSnapshot(Base):
    __tablename__ = "regime_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    score: Mapped[float] = mapped_column(Float)
    regime: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[float] = mapped_column(Float)
    coverage: Mapped[float] = mapped_column(Float)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class NewsArticle(Base):
    __tablename__ = "news_articles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # content hash
    title: Mapped[str] = mapped_column(Text)
    normalized_title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    canonical_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    publisher: Mapped[str] = mapped_column(String(160))
    language: Mapped[str] = mapped_column(String(8), default="en")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    importance: Mapped[float] = mapped_column(Float, default=0.0)
    reliability: Mapped[float] = mapped_column(Float, default=0.5)
    sentiment: Mapped[float | None] = mapped_column(Float, nullable=True)
    cluster_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("news_clusters.id"), nullable=True)
    related: Mapped[dict] = mapped_column(JSON, default=dict)  # indices/sectors/securities/macro
    content_hash: Mapped[str] = mapped_column(String(64), index=True)


class NewsCluster(Base):
    __tablename__ = "news_clusters"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    headline: Mapped[str] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    importance: Mapped[float] = mapped_column(Float, default=0.0)
    article_count: Mapped[int] = mapped_column(Integer, default=1)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    related: Mapped[dict] = mapped_column(JSON, default=dict)


class OrchestratorRun(Base):
    __tablename__ = "orchestrator_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    objective: Mapped[str] = mapped_column(String(64))
    trigger: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default="running")
    selected_agents: Mapped[dict] = mapped_column(JSON, default=list)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    runtime: Mapped[str] = mapped_column(String(16), default="mock")
    token_usage: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


class AgentRunRow(Base):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    orchestrator_run_id: Mapped[str] = mapped_column(String(64), ForeignKey("orchestrator_runs.id"), index=True)
    agent_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default="ok")
    direction: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    token_usage: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    output: Mapped[dict] = mapped_column(JSON, default=dict)  # SpecialistOpinion
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Recommendation(Base):
    """A recommendation is immutable once written; changes append a new row with
    a shared ``lineage_id`` and a new ``revision`` (spec §32.5)."""

    __tablename__ = "recommendations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    lineage_id: Mapped[str] = mapped_column(String(64), index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    # initial | upgrade | downgrade | reaffirm | withdraw | expire | invalidate
    change_type: Mapped[str] = mapped_column(String(24), default="initial")
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    company_name: Mapped[str] = mapped_column(String(160))
    asset_type: Mapped[str] = mapped_column(String(32))
    horizon: Mapped[str] = mapped_column(String(16), index=True)
    action: Mapped[str] = mapped_column(String(16), index=True)
    total_score: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    one_line_thesis: Mapped[str] = mapped_column(Text)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    data_freshness: Mapped[str] = mapped_column(String(16), default="mixed")
    payload: Mapped[dict] = mapped_column(JSON)  # full Recommendation schema
    orchestrator_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class RecommendationOutcome(Base):
    __tablename__ = "recommendation_outcomes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recommendation_id: Mapped[str] = mapped_column(String(64), ForeignKey("recommendations.id"), index=True)
    lineage_id: Mapped[str] = mapped_column(String(64), index=True)
    horizon_days: Mapped[int] = mapped_column(Integer)  # 1,5,20,60,120,252
    entry_price: Mapped[str | None] = mapped_column(DecimalString, nullable=True)
    exit_price: Mapped[str | None] = mapped_column(DecimalString, nullable=True)
    abs_return_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    benchmark: Mapped[str | None] = mapped_column(String(32), nullable=True)
    excess_return_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class DailyBriefing(Base):
    __tablename__ = "daily_briefings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    briefing_date: Mapped[str] = mapped_column(String(16), index=True)  # ET calendar day
    briefing_type: Mapped[str] = mapped_column(String(16))
    language: Mapped[str] = mapped_column(String(8))
    headline: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSON)
    generated_by: Mapped[str] = mapped_column(String(16), default="deterministic")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (
        Index("ux_briefing_unique", "briefing_date", "briefing_type", "language", unique=True),
    )


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    pipeline: Mapped[str] = mapped_column(String(48), index=True)
    status: Mapped[str] = mapped_column(String(24), default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class PipelineLock(Base):
    """Distributed-ish lock (one row per pipeline key) to prevent duplicate runs."""

    __tablename__ = "pipeline_locks"

    key: Mapped[str] = mapped_column(String(96), primary_key=True)
    holder: Mapped[str] = mapped_column(String(64))
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ModelUsage(Base):
    __tablename__ = "model_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(24))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AuditEvent(Base):
    """Append-only audit log. No update/delete path in app code (spec §41)."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(48), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)


class DataQualityEvent(Base):
    __tablename__ = "data_quality_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(48), index=True)  # stale|unavailable|mock|provider_outage
    symbol: Mapped[str | None] = mapped_column(String(32), nullable=True)
    detail: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
