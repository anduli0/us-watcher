"""Dynamic agent router (spec §17).

Selects ~7-12 specialists for a run from the pool of 23, based on the objective,
the affected markets/entities, and the current market state. The Contrarian and
the Evidence Auditor are ALWAYS included (adversarial review is mandatory).
"""

from __future__ import annotations

from us_watcher.domain.agents.catalog import SPECIALISTS, AgentSpec

_ALWAYS = {"contrarian_analyst", "evidence_auditor"}

# Objective -> seed agents that are always relevant for that objective.
_OBJECTIVE_SEEDS: dict[str, set[str]] = {
    "market_overview": {
        "sp500_analyst", "nasdaq_analyst", "nyse_breadth_analyst",
        "fed_rates_analyst", "cross_asset_analyst", "sector_rotation_analyst",
        "technical_flow_analyst",
    },
    "semiconductor_shock": {
        "nasdaq_analyst", "sp500_analyst", "semi_ai_analyst", "earnings_revision_analyst",
        "technical_flow_analyst", "capital_migration_analyst", "cross_asset_analyst",
    },
    "banking_stress": {
        "sp500_analyst", "nyse_breadth_analyst", "financials_reit_analyst",
        "fed_rates_analyst", "cross_asset_analyst", "fiscal_trade_analyst",
    },
    "rotation_review": {
        "sector_rotation_analyst", "sp500_analyst", "technical_flow_analyst",
        "semi_ai_analyst", "financials_reit_analyst", "industrial_energy_analyst",
    },
}


def select_agents(
    objective: str,
    *,
    keywords: list[str] | None = None,
    max_agents: int = 12,
    min_agents: int = 7,
) -> list[AgentSpec]:
    """Return the activated specialist specs for this run."""
    selected: set[str] = set(_ALWAYS)
    selected |= _OBJECTIVE_SEEDS.get(objective, _OBJECTIVE_SEEDS["market_overview"])

    kw = {k.lower() for k in (keywords or [])}
    if kw:
        for spec in SPECIALISTS:
            if any(t in kw or any(t in k for k in kw) for t in spec.triggers):
                selected.add(spec.id)

    specs = [s for s in SPECIALISTS if s.id in selected]
    # Ensure bounds: pad with highest-weight generalists if under min.
    if len(specs) < min_agents:
        for s in sorted(SPECIALISTS, key=lambda x: x.default_weight, reverse=True):
            if s.id not in {sp.id for sp in specs}:
                specs.append(s)
            if len(specs) >= min_agents:
                break
    if len(specs) > max_agents:
        # Keep adversarial + highest-weight specialists.
        specs.sort(key=lambda x: (x.id in _ALWAYS, x.default_weight), reverse=True)
        specs = specs[:max_agents]
    return specs
