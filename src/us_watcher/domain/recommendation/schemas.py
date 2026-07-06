"""Recommendation output schema (spec §26).

Every recommendation carries evidence, confidence, horizon, catalysts, risks,
invalidation conditions, three scenarios, a dissenting view, and a data
timestamp. Target prices are OMITTED unless a defined valuation model with shown
assumptions and an explicit range exists (spec §26: avoid false precision) —
``target_range`` stays ``None`` otherwise.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from us_watcher.domain.enums import AssetType, Horizon, RecAction


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str  # "bull" | "base" | "bear"
    probability: float = Field(ge=0.0, le=1.0)
    narrative_en: str
    narrative_ko: str
    target_range: list[float] | None = None  # only when a valuation model exists


class Recommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str
    company_name: str
    asset_type: AssetType
    horizon: Horizon
    action: RecAction

    total_score: float = Field(ge=0.0, le=100.0)
    confidence: float = Field(ge=0.0, le=100.0)

    as_of: datetime
    expires_at: datetime | None = None

    one_line_thesis_en: str
    one_line_thesis_ko: str

    # Cohesive plain-language "why this call" narrative (weaves the thesis, the
    # decisive factors, the main risk, and what would change the view into one
    # flowing read — not just disconnected bullets).
    rationale_en: str = ""
    rationale_ko: str = ""

    reasons: list[str] = Field(default_factory=list)
    catalysts: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    invalidation_conditions: list[str] = Field(default_factory=list)
    # Korean parallels (UI shows these when the language toggle is set to KO).
    reasons_ko: list[str] = Field(default_factory=list)
    catalysts_ko: list[str] = Field(default_factory=list)
    risks_ko: list[str] = Field(default_factory=list)
    invalidation_conditions_ko: list[str] = Field(default_factory=list)

    technical_summary: str = ""
    fundamental_summary: str = ""
    fundamental_summary_ko: str = ""
    valuation_summary: str = ""
    valuation_summary_ko: str = ""
    capital_migration_summary: str | None = None
    capital_migration_summary_ko: str | None = None
    capital_migration_score: float | None = None
    # Attention/heat: analyst coverage + estimate revisions + momentum + flows.
    hotness_score: float = 0.0
    # Visionary "big bet": explosive future-growth potential while still cheap/out
    # of favour now (ignores momentum/technical strength on purpose).
    moonshot_score: float = 0.0
    # Curated house-spotlight overlay (editorial, NOT market data): the theme and
    # a short note shown in the UI when this name is on the desk's current focus
    # list (drives the HOT/Big-Bet floors). Empty for non-spotlight names.
    spotlight_theme_en: str = ""
    spotlight_theme_ko: str = ""
    spotlight_note_en: str = ""
    spotlight_note_ko: str = ""

    # Expected price band over the horizon (narrowest defensible range, with the
    # assumptions shown). None when no valuation anchor exists — never a bare
    # point estimate (CLAUDE.md invariant 4).
    target_low: float | None = None
    target_high: float | None = None
    target_basis_en: str = ""
    target_basis_ko: str = ""

    bull_scenario: Scenario
    base_scenario: Scenario
    bear_scenario: Scenario

    dissent_summary: str
    dissent_summary_ko: str = ""

    component_scores: dict[str, float | None] = Field(default_factory=dict)
    contributions: dict[str, float] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)
    data_freshness: str = "mixed"
