# Agent Design

Runtime investment-analysis agents (this doc) are **separate** from the Claude
Code development subagents in `.claude/agents/`.

## Supervisory layer (3)

- **Market Intelligence Orchestrator** — freeze snapshot, select agents, build
  evidence packs, run, track failures, manage token budget, forward to Chief.
- **Chief Investment Analyst** — integrate opinions, separate horizons, produce
  final classification & recommendations, preserve dissent.
- **Evidence, Risk & Editorial Gate** — reject unsupported claims, flag stale
  evidence/excess certainty, confirm risks & invalidation, approve KO/EN.

## Specialist pool (23) — `domain/agents/catalog.py`

- **Market desks**: S&P 500, Nasdaq, Dow Jones, NYSE Breadth.
- **Macro & policy**: Fed/Rates/Liquidity, Inflation/Labor/Growth,
  Fiscal/Trade/Regulation, Cross-Asset, Geopolitics.
- **Sector & industry**: Sector Rotation, Semiconductor/AI Infra, Software/Cloud/
  Internet, Industrial/Energy/Materials, Financials/REITs.
- **Security & product**: Fundamental Quality, Valuation, Earnings/Revision,
  Technical/Flow/Volatility, ETF/Covered-Call.
- **Structural growth**: Capital Migration, Emerging Theme/Bottleneck.
- **Adversarial & validation**: Contrarian/Bear-Case, Evidence/Model-Risk Auditor.

Each spec carries `triggers` (keywords) and `default_weight`; desks carry weights.

## Dynamic activation — `agent_service/router.py`

Objective + driver keywords + affected entities select ~7–12 specialists.
Contrarian and Evidence Auditor are **always** included. Examples:
semiconductor shock → Nasdaq, S&P 500, Semi/AI, Earnings, Technical/Flow,
Capital Migration, Cross-Asset (+ adversarial). Banking stress → S&P 500, NYSE
Breadth, Financials/REITs, Fed/Rates, Cross-Asset, Fiscal (+ adversarial).

## Structured output — `domain/agents/schemas.py::SpecialistOpinion`

Validated (Pydantic, `extra="forbid"`) before any prose: `agent_id, scope, as_of,
direction[-1,1], confidence[0,100], thesis, facts[], interpretations[],
evidence_ids[], catalysts[], risks[], assumptions[], invalidation_conditions[],
unresolved_questions[], data_freshness`. Invalid responses are rejected/retried,
never silently published. Private chain-of-thought is never stored.

## Determinism & the LLM boundary

Direction/confidence are computed deterministically from the evidence pack (so
the system is reproducible and runs offline in `mock` mode). When `AGENT_RUNTIME=
llm` + a key is set, the LLM **enriches prose only** — it never produces the
numbers. The Anthropic provider forces structured output via a single tool and
**degrades to mock on any error** (a provider outage cannot crash a run).

## Aggregation — `agent_service/orchestrator.py::_aggregate`

Weighted mean of `direction` by `desk_weight × agent_weight × (confidence/100)`,
with a same-desk **correlation discount** `1/(1+0.25·(n−1))`. Adversarial desks
inform risk at reduced directional weight. Output: house direction + label
(BULLISH/BEARISH/NEUTRAL) + confidence.

## Persistence & cost

`orchestrator_runs` (objective, selected agents, runtime, token usage, payload)
and `agent_runs` (per-agent direction/confidence/output/error). Surfaced at
`GET /api/v1/agents/runs` and the **Agents** tab (committee view; no raw CoT).

## LLM provider roles (spec §20) — `config.py`

`LLM_FAST_*` (classification/extraction), `LLM_REASONING_*` (specialist analysis),
`LLM_CRITIC_*` (adversarial), `LLM_EDITOR_*` (KO/EN writing). Centralized; never
hardcoded. Defaults: reasoning/editor = `claude-opus-4-8`, fast =
`claude-haiku-4-5`, critic = `claude-sonnet-4-6`.
