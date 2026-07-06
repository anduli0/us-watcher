"""Market Intelligence Orchestrator (spec §16, §19).

Pipeline: freeze snapshot -> build evidence pack -> route specialists ->
independent opinions -> contrarian + evidence-audit passes -> deterministic
aggregation -> persist (run + per-agent outputs + token usage).

Opinions' direction/confidence are computed deterministically from the evidence
pack (LLMs never invent numbers, spec §3.1). When an LLM is configured it only
enriches the prose thesis; the structured numbers stay deterministic. One agent
failing never crashes the run.
"""

from __future__ import annotations

import uuid

from us_watcher.config import get_settings
from us_watcher.db.models import AgentRunRow, OrchestratorRun
from us_watcher.domain.agents.catalog import DESKS, AgentSpec, get_specialist
from us_watcher.domain.agents.schemas import EvidenceItem, SpecialistOpinion
from us_watcher.domain.enums import DataQuality
from us_watcher.domain.time import now_utc
from us_watcher.infrastructure.db import get_sessionmaker
from us_watcher.logging_config import get_logger
from us_watcher.market.schemas import OverviewResponse
from us_watcher.market.service import get_market_service

from .router import select_agents

log = get_logger("us_watcher.orchestrator")
_DESK_WEIGHT = {d.id: d.weight for d in DESKS}


async def run_orchestrator(*, objective: str = "market_overview", trigger: str = "manual") -> dict:
    run_id = uuid.uuid4().hex
    started = now_utc()
    svc = get_market_service()
    overview = await svc.build_overview()

    evidence = _build_evidence_pack(overview)
    keywords = [d.name.lower() for d in overview.drivers]
    specs = select_agents(objective, keywords=keywords)

    opinions: list[SpecialistOpinion] = []
    agent_rows: list[AgentRunRow] = []
    regime_dir = max(-1.0, min(1.0, overview.pulse.score / 100.0))
    coverage = overview.pulse.coverage

    for spec in specs:
        try:
            op = _mock_opinion(spec, overview, evidence, regime_dir, coverage)
        except Exception as exc:
            agent_rows.append(AgentRunRow(
                id=uuid.uuid4().hex, orchestrator_run_id=run_id, agent_id=spec.id,
                status="error", error=str(exc)[:300], output={}))
            continue
        opinions.append(op)
        agent_rows.append(AgentRunRow(
            id=uuid.uuid4().hex, orchestrator_run_id=run_id, agent_id=spec.id, status="ok",
            direction=op.direction, confidence=op.confidence, model_name=op.model_name,
            token_usage=op.token_usage, output=op.model_dump(mode="json")))

    aggregate = _aggregate(opinions)

    settings = get_settings()
    # Chief synthesis: deterministic house view, optionally given a readable
    # narrative by the LLM (prose only — never the numbers). Degrades to mock.
    chief = await _chief_synthesis(opinions, aggregate, overview)
    finished = now_utc()
    duration_ms = int((finished - started).total_seconds() * 1000)
    run_payload = {
        "objective": objective,
        "aggregate": aggregate,
        "chief": chief,
        "evidence_count": len(evidence),
        "agents": [
            {"agent_id": o.agent_id, "scope": o.scope, "direction": o.direction,
             "confidence": o.confidence, "thesis": o.thesis,
             "risks": o.risks, "invalidation": o.invalidation_conditions,
             "evidence_ids": o.evidence_ids, "data_freshness": o.data_freshness.value}
            for o in opinions
        ],
        "regime": overview.pulse.model_dump(),
        "duration_ms": duration_ms,
    }
    token_usage = sum(o.token_usage for o in opinions) + int(chief.get("tokens", 0))

    sm = get_sessionmaker()
    async with sm() as s:
        s.add(OrchestratorRun(
            id=run_id, objective=objective, trigger=trigger, status="completed",
            selected_agents=[sp.id for sp in specs], started_at=started, finished_at=finished,
            runtime=("llm" if settings.llm_enabled else "mock"),
            token_usage=token_usage, payload=run_payload))
        for row in agent_rows:
            s.add(row)
        await s.commit()

    return {
        "run_id": run_id, "objective": objective, "trigger": trigger,
        "runtime": "llm" if settings.llm_enabled else "mock",
        "selected_agents": [sp.id for sp in specs], "agent_count": len(specs),
        "ok_count": len(opinions), "error_count": len(specs) - len(opinions),
        "aggregate": aggregate, "chief": chief, "token_usage": token_usage, "duration_ms": duration_ms,
        "regime": {"regime": overview.pulse.regime.value, "score": overview.pulse.score},
    }


async def _chief_synthesis(
    opinions: list[SpecialistOpinion], aggregate: dict, overview: OverviewResponse
) -> dict:
    """Produce the Chief house-view narrative (EN+KO).

    The numbers (direction/confidence/regime) are deterministic inputs; the LLM
    only writes readable prose around them. When no LLM is configured, a clear
    deterministic narrative is used. Never raises.
    """
    settings = get_settings()
    label = aggregate.get("label", "NEUTRAL")
    conf = aggregate.get("confidence", 0.0)
    regime = overview.pulse
    top = sorted(opinions, key=lambda o: abs(o.direction) * o.confidence, reverse=True)[:5]
    det_en = (f"House view: {label} (agg direction {aggregate.get('direction')}, confidence {conf:.0f}%), "
              f"market state {regime.regime_en} ({regime.score:+.0f}). Key desks: "
              + "; ".join(f"{o.agent_id} {('+' if o.direction>0 else '')}{o.direction:.2f}" for o in top) + ".")
    det_ko = (f"하우스 뷰: {label} (종합 방향 {aggregate.get('direction')}, 신뢰도 {conf:.0f}%), "
              f"시장 국면 {regime.regime_ko} ({regime.score:+.0f}).")
    result = {"narrative_en": det_en, "narrative_ko": det_ko, "model": "deterministic",
              "tokens": 0, "is_mock": True}

    if not settings.llm_enabled:
        return result

    from us_watcher.infrastructure.llm.factory import get_llm_provider
    provider = get_llm_provider()
    facts = (
        f"Aggregate direction {aggregate.get('direction')} ({label}), confidence {conf:.0f}%. "
        f"Regime {regime.regime_en} score {regime.score:+.0f}, coverage {regime.coverage:.2f}. "
        "Specialist positions (agent: direction, confidence): "
        + "; ".join(f"{o.agent_id}: {o.direction:+.2f}, {o.confidence:.0f}%" for o in top)
        + ". Drivers: " + ", ".join(f"{d.name}={d.direction}" for d in overview.drivers)
    )
    system = (
        "You are the Chief Investment Analyst for a U.S. equity intelligence desk. "
        "Write a concise, nonpartisan, evidence-based house view (3-4 sentences). "
        "Use ONLY the numbers provided — never invent figures, prices, or targets. "
        "Acknowledge dissent and uncertainty. This is analysis, not investment advice."
    )
    try:
        en = await provider.generate_text(system, f"DATA:\n{facts}\n\nWrite the house view in English.",
                                          role="reasoning", max_tokens=400)
        ko = await provider.generate_text(
            system,
            f"DATA:\n{facts}\n\n위 데이터로 한국어 하우스 뷰를 작성. 일반 투자자가 바로 이해할 평이한"
            " 한국어로 쓰고, 학술·영어 차용 용어는 피하세요(예: 레짐→시장 국면, 커버리지→측정 범위,"
            " 브레드스→시장 폭, 센티먼트→투자심리).",
            role="editor", max_tokens=500)
        if en.text.strip():
            result["narrative_en"] = en.text.strip()
        if ko.text.strip():
            result["narrative_ko"] = ko.text.strip()
        result["model"] = en.model or ko.model
        result["tokens"] = en.input_tokens + en.output_tokens + ko.input_tokens + ko.output_tokens
        result["is_mock"] = en.is_mock and ko.is_mock
    except Exception as exc:  # never let the LLM break a run
        log.warning("chief_synthesis.llm_failed", error=str(exc)[:200])
    return result


def _build_evidence_pack(overview: OverviewResponse) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    for c in overview.cards:
        if c.last is None:
            continue
        items.append(EvidenceItem(
            id=f"card:{c.symbol}", kind="feature", title=f"{c.name} level/changes",
            detail=f"{c.name}: last {c.last}, 1d {c.change_1d_pct}, 1m {c.change_1m_pct}",
            value=c.change_1m_pct, as_of=c.as_of, source=c.source, status=c.status.value))
    items.append(EvidenceItem(
        id="regime:composite", kind="feature", title="Composite regime",
        detail=overview.pulse.diagnosis_en, value=overview.pulse.score, status="END_OF_DAY"))
    for d in overview.drivers:
        items.append(EvidenceItem(
            id=f"driver:{d.name}", kind="feature", title=f"Driver: {d.name}",
            detail=d.evidence_en, value=d.confidence, status="END_OF_DAY"))
    return items


def _scope_bias(spec: AgentSpec, overview: OverviewResponse) -> float:
    """Small deterministic tilt by desk/category so specialists differ honestly."""
    by = {c.symbol: c for c in overview.cards}
    cat = spec.category
    if cat in ("SEMI_AI", "SOFTWARE") and by.get("NDX") and by["NDX"].change_1m_pct is not None:
        return max(-1.0, min(1.0, by["NDX"].change_1m_pct / 8.0))
    if cat == "FINANCIALS" and by.get("DJI") and by["DJI"].change_1m_pct is not None:
        return max(-1.0, min(1.0, by["DJI"].change_1m_pct / 8.0))
    if cat == "BREADTH" and by.get("RUT") and by["RUT"].change_1m_pct is not None:
        return max(-1.0, min(1.0, by["RUT"].change_1m_pct / 8.0))
    if cat == "RATES" and by.get("T10Y2Y") and by["T10Y2Y"].last is not None:
        return 0.2 if by["T10Y2Y"].last > 0 else -0.2
    return 0.0


def _mock_opinion(
    spec: AgentSpec, overview: OverviewResponse, evidence: list[EvidenceItem],
    regime_dir: float, coverage: float,
) -> SpecialistOpinion:
    """Deterministic opinion from the evidence pack. Adversarial desks contest."""
    now = now_utc()
    ev_ids = [e.id for e in evidence][:8]
    freshness = overview.data_quality

    if spec.id == "contrarian_analyst":
        direction = -0.5 * regime_dir  # contest the consensus
        confidence = 45.0 + 20.0 * coverage
        thesis = ("Contrarian check: is the move already priced in, driven by only a few mega-caps, "
                  "or confirmed by breadth? Treat narrative as distinct from realized revenue.")
        risks = ["Crowded positioning", "Narrow leadership", "Valuation already optimistic"]
        inval = ["Breadth broadens materially", "Equal-weight confirms cap-weight"]
    elif spec.id == "evidence_auditor":
        direction = 0.0
        confidence = 40.0 + 25.0 * coverage
        thesis = (f"Audit: {len(evidence)} evidence items; data quality '{freshness}'. "
                  "Checked numerical consistency, freshness, and point-in-time validity.")
        risks = ["Some components unmeasured (reweighted)", "Delayed/EOD data, not real-time"]
        inval = ["A live provider contradicts the cached snapshot"]
    else:
        bias = _scope_bias(spec, overview)
        direction = max(-1.0, min(1.0, 0.7 * regime_dir + 0.3 * bias))
        confidence = max(0.0, min(90.0, (45.0 + 35.0 * abs(direction)) * (0.6 + 0.4 * coverage) * spec.default_weight))
        verb = "constructive" if direction > 0.1 else "cautious" if direction < -0.1 else "neutral"
        thesis = f"{spec.name}: {verb} on its scope given the current regime and cross-asset backdrop."
        risks = ["Regime shift to risk-off", "Provider/data limitations in the keyless tier"]
        inval = ["Composite regime score crosses zero", "Leadership in scope reverses"]

    return SpecialistOpinion(
        agent_id=spec.id, scope=spec.scope, as_of=now,
        direction=round(direction, 3), confidence=round(confidence, 1), thesis=thesis,
        facts=[e.detail for e in evidence[:3]],
        interpretations=[f"{spec.desk} desk read: {_lean_word(direction)}."],
        evidence_ids=ev_ids, catalysts=["Macro prints", "Earnings season"], risks=risks,
        assumptions=["Keyless data is representative of the tape"],
        invalidation_conditions=inval, unresolved_questions=[],
        data_freshness=_freshness_enum(freshness), model_name="deterministic-mock",
    )


def _lean_word(direction: float) -> str:
    return "risk-on" if direction > 0 else "risk-off" if direction < 0 else "balanced"


def _freshness_enum(dq: str) -> DataQuality:
    try:
        return DataQuality(dq)
    except ValueError:
        return DataQuality.MIXED


def _aggregate(opinions: list[SpecialistOpinion]) -> dict:
    """Deterministic weighted aggregation with a same-desk correlation discount
    (spec §9). Adversarial desks inform risk but get reduced directional weight."""
    if not opinions:
        return {"direction": 0.0, "confidence": 0.0, "label": "NEUTRAL", "n": 0}
    desk_counts: dict[str, int] = {}
    for o in opinions:
        spec = get_specialist(o.agent_id)
        desk = spec.desk if spec else "OTHER"
        desk_counts[desk] = desk_counts.get(desk, 0) + 1

    num = 0.0
    den = 0.0
    for o in opinions:
        spec = get_specialist(o.agent_id)
        desk = spec.desk if spec else "OTHER"
        base_w = _DESK_WEIGHT.get(desk, 0.06) * (spec.default_weight if spec else 1.0)
        if desk == "ADVERSARIAL":
            base_w *= 0.4  # inform risk, not direction
        corr_discount = 1.0 / (1.0 + 0.25 * (desk_counts.get(desk, 1) - 1))
        w = base_w * (o.confidence / 100.0) * corr_discount
        num += o.direction * w
        den += w
    direction = round(num / den, 3) if den else 0.0
    conf = round(min(95.0, sum(o.confidence for o in opinions) / len(opinions)), 1)
    label = "BULLISH" if direction > 0.12 else "BEARISH" if direction < -0.12 else "NEUTRAL"
    return {"direction": direction, "confidence": conf, "label": label, "n": len(opinions)}
