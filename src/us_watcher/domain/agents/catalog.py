"""Specialist agent pool + supervisory layer (spec §16).

A pool of 23 specialist roles grouped into desks, plus 3 supervisory roles. The
router (spec §17) dynamically activates ~7-12 specialists per run; not every
agent runs every time. This module is pure data — the runtime behaviour lives in
:mod:`us_watcher.domain.agents.base` / ``llm_agent``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class AgentSpec:
    id: str
    name: str
    desk: str
    category: str
    scope: str
    # Tags the router matches against event/entity/market signals.
    triggers: tuple[str, ...] = ()
    default_weight: float = 1.0


@dataclass(frozen=True, slots=True)
class Desk:
    id: str
    name: str
    weight: float
    agent_ids: tuple[str, ...]


SUPERVISORS: list[AgentSpec] = [
    AgentSpec("orchestrator", "Market Intelligence Orchestrator", "SUPERVISORY", "ORCHESTRATION",
              "Freeze snapshot, select agents, build evidence packs, run in parallel, manage budget."),
    AgentSpec("chief", "Chief Investment Analyst", "SUPERVISORY", "SYNTHESIS",
              "Integrate specialist opinions, separate horizons, produce final classification + recommendations."),
    AgentSpec("editorial_gate", "Evidence, Risk & Editorial Gate", "SUPERVISORY", "GATE",
              "Reject unsupported claims, flag stale evidence, confirm risks & invalidation, approve KO/EN."),
]

SPECIALISTS: list[AgentSpec] = [
    # Market desks
    AgentSpec("sp500_analyst", "S&P 500 Analyst", "MARKET", "INDEX",
              "Breadth, concentration, equal vs cap weight, GICS contribution.",
              ("sp500", "breadth", "concentration", "equity"), 1.1),
    AgentSpec("nasdaq_analyst", "Nasdaq Analyst", "MARKET", "INDEX",
              "Nasdaq-100/Composite, semis, software, duration risk, mega-cap.",
              ("nasdaq", "tech", "semiconductor", "growth", "duration"), 1.1),
    AgentSpec("dow_analyst", "Dow Jones Analyst", "MARKET", "INDEX",
              "Price-weighted contribution, industrials, transports/utilities confirmation.",
              ("dow", "industrials", "transports", "dividend")),
    AgentSpec("nyse_breadth_analyst", "NYSE Breadth Analyst", "MARKET", "BREADTH",
              "Advance-decline, new highs/lows, participation, internal strength.",
              ("nyse", "breadth", "participation", "liquidity"), 1.05),
    # Macro & policy desks
    AgentSpec("fed_rates_analyst", "Fed, Rates & Liquidity Analyst", "MACRO", "RATES",
              "Policy rate path, real yields, curve, liquidity.",
              ("fed", "fomc", "rates", "yields", "liquidity", "bank"), 1.15),
    AgentSpec("inflation_growth_analyst", "Inflation, Labor & Growth Analyst", "MACRO", "MACRO",
              "CPI/PCE, employment, consumption, growth surprises.",
              ("inflation", "cpi", "jobs", "labor", "growth", "gdp")),
    AgentSpec("fiscal_trade_analyst", "Fiscal, Trade & Regulation Analyst", "MACRO", "POLICY",
              "Deficit/issuance, tax, tariffs, antitrust, industrial policy.",
              ("fiscal", "tariff", "trade", "regulation", "tax", "antitrust", "policy")),
    AgentSpec("cross_asset_analyst", "Cross-Asset Analyst", "MACRO", "CROSS_ASSET",
              "Dollar, oil, gold, credit, rates confirmation/divergence.",
              ("dollar", "oil", "gold", "credit", "cross-asset"), 1.05),
    AgentSpec("geopolitics_analyst", "Geopolitical Scenario Analyst", "MACRO", "GEOPOLITICS",
              "Conflict, sanctions, elections, supply routes.",
              ("geopolitics", "war", "sanctions", "election", "oil")),
    # Sector & industry desks
    AgentSpec("sector_rotation_analyst", "Sector Rotation Analyst", "SECTOR", "ROTATION",
              "11 GICS sectors, relative strength, rotation quadrant, style leadership.",
              ("sector", "rotation", "style", "breadth"), 1.05),
    AgentSpec("semi_ai_analyst", "Semiconductor & AI Infrastructure Analyst", "SECTOR", "SEMI_AI",
              "Semis, AI infra, data centers, networking, memory, capex cycle.",
              ("semiconductor", "ai", "datacenter", "memory", "nvidia", "capex"), 1.15),
    AgentSpec("software_cloud_analyst", "Software, Cloud & Internet Analyst", "SECTOR", "SOFTWARE",
              "SaaS, cloud, internet platforms, durations, margins.",
              ("software", "cloud", "saas", "internet", "platform")),
    AgentSpec("industrial_energy_analyst", "Industrial, Energy & Materials Analyst", "SECTOR", "CYCLICAL",
              "Industrials, energy, materials, capex, commodities.",
              ("industrial", "energy", "materials", "oil", "commodity")),
    AgentSpec("financials_reit_analyst", "Financials & REITs Analyst", "SECTOR", "FINANCIALS",
              "Banks, NIM, credit, insurance, REIT rate sensitivity.",
              ("financials", "bank", "credit", "reit", "insurance", "rates")),
    # Security & product desks
    AgentSpec("fundamental_quality_analyst", "Fundamental Quality Analyst", "SECURITY", "QUALITY",
              "Margins, FCF, balance sheet, moat, execution.",
              ("fundamental", "quality", "moat", "balance-sheet")),
    AgentSpec("valuation_analyst", "Valuation Analyst", "SECURITY", "VALUATION",
              "Multiples vs growth, scenario value, false-precision guard.",
              ("valuation", "multiple", "pe", "dcf")),
    AgentSpec("earnings_revision_analyst", "Earnings & Revision Analyst", "SECURITY", "EARNINGS",
              "Estimate revisions, surprise, guidance, breadth of revisions.",
              ("earnings", "revision", "guidance", "estimate", "results"), 1.05),
    AgentSpec("technical_flow_analyst", "Technical, Flow & Volatility Analyst", "SECURITY", "TECHNICAL",
              "Trend, momentum, options positioning, flow, volatility.",
              ("technical", "flow", "options", "volatility", "momentum")),
    AgentSpec("etf_covered_call_analyst", "ETF & Covered-Call Analyst", "SECURITY", "ETF",
              "ETF structure, covered-call methodology, NAV erosion, distribution vs total return.",
              ("etf", "covered-call", "income", "distribution", "yield")),
    # Structural growth desks
    AgentSpec("capital_migration_analyst", "Capital Migration Analyst", "STRUCTURAL", "CAPITAL_MIGRATION",
              "Structural capital flows: capex, backlog/RPO, institutional/ETF flows, policy.",
              ("capex", "capital", "flow", "backlog", "rpo", "structural"), 1.1),
    AgentSpec("emerging_theme_analyst", "Emerging Theme & Bottleneck Analyst", "STRUCTURAL", "THEME",
              "Underappreciated themes, strategic bottlenecks, pricing power.",
              ("theme", "bottleneck", "emerging", "pricing-power")),
    # Adversarial & validation desks
    AgentSpec("contrarian_analyst", "Contrarian & Bear-Case Analyst", "ADVERSARIAL", "CONTRARIAN",
              "Priced-in test, correlation≠causation, narrow leadership, stale evidence.",
              ("contrarian", "bear", "risk"), 1.0),
    AgentSpec("evidence_auditor", "Evidence & Model-Risk Auditor", "ADVERSARIAL", "AUDIT",
              "Numerical consistency, evidence existence, freshness, point-in-time, injection.",
              ("audit", "evidence", "risk", "validation"), 1.0),
]

DESKS: list[Desk] = [
    Desk("MARKET", "Market Desks", 0.22,
         ("sp500_analyst", "nasdaq_analyst", "dow_analyst", "nyse_breadth_analyst")),
    Desk("MACRO", "Macro & Policy Desks", 0.22,
         ("fed_rates_analyst", "inflation_growth_analyst", "fiscal_trade_analyst",
          "cross_asset_analyst", "geopolitics_analyst")),
    Desk("SECTOR", "Sector & Industry Desks", 0.20,
         ("sector_rotation_analyst", "semi_ai_analyst", "software_cloud_analyst",
          "industrial_energy_analyst", "financials_reit_analyst")),
    Desk("SECURITY", "Security & Product Desks", 0.18,
         ("fundamental_quality_analyst", "valuation_analyst", "earnings_revision_analyst",
          "technical_flow_analyst", "etf_covered_call_analyst")),
    Desk("STRUCTURAL", "Structural Growth Desks", 0.12,
         ("capital_migration_analyst", "emerging_theme_analyst")),
    Desk("ADVERSARIAL", "Adversarial & Validation Desks", 0.06,
         ("contrarian_analyst", "evidence_auditor")),
]

_BY_ID = {a.id: a for a in SPECIALISTS + SUPERVISORS}


def get_specialist(agent_id: str) -> AgentSpec | None:
    return _BY_ID.get(agent_id)


def all_specialists() -> list[AgentSpec]:
    return list(SPECIALISTS)


def org_chart() -> dict:
    """Read-only org structure for the Agents tab.

    ``AgentSpec``/``Desk`` are slotted dataclasses (no ``__dict__``), so serialise
    with :func:`dataclasses.asdict` — ``a.__dict__`` raises ``AttributeError``.
    """
    return {
        "supervisory": [asdict(a) for a in SUPERVISORS],
        "desks": [
            {
                "id": d.id,
                "name": d.name,
                "weight": d.weight,
                "agents": [asdict(spec) for aid in d.agent_ids if (spec := get_specialist(aid))],
            }
            for d in DESKS
        ],
        "specialist_count": len(SPECIALISTS),
        "supervisor_count": len(SUPERVISORS),
    }
