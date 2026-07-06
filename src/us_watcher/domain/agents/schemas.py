"""Structured agent output contract (spec §18).

Every agent returns a validated :class:`SpecialistOpinion` BEFORE any free-form
prose. Invalid responses are rejected/retried, never silently published. Private
chain-of-thought is never stored — only conclusion, summary reasoning, evidence,
assumptions, risks, and invalidation conditions.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from us_watcher.domain.enums import DataQuality


class EvidenceItem(BaseModel):
    """A single piece of evidence in an evidence pack (spec §19 step 4)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str  # "feature" | "macro" | "news" | "filing" | "price_reaction" | "historical"
    title: str
    detail: str
    value: float | None = None
    as_of: datetime | None = None
    source: str = "internal"
    status: str = "END_OF_DAY"


class SpecialistOpinion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    scope: str
    as_of: datetime

    direction: float = Field(ge=-1.0, le=1.0)
    confidence: float = Field(ge=0.0, le=100.0)

    thesis: str

    facts: list[str] = Field(default_factory=list)
    interpretations: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)

    catalysts: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    invalidation_conditions: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)

    data_freshness: DataQuality = DataQuality.MIXED

    # Server-filled audit fields (not produced by the model)
    model_name: str = "deterministic-mock"
    duration_ms: int = 0
    token_usage: int = 0
