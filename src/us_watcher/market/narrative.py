"""Plain-language, criteria-anchored interpretation of the market regime.

This is deterministic *interpretation* of already-computed facts (CLAUDE.md
invariant 1): it never invents a number. It turns the raw regime score and
component sub-scores into a structured reading a non-expert can act on — what
the state means, which signals drove it, how the framework says to position,
what would flip the view, and how much of the picture was actually measured.

Every string is produced in both English and Korean from the same inputs.
"""

from __future__ import annotations

from us_watcher.domain.analytics.features import FeatureSet
from us_watcher.domain.enums import MarketRegime
from us_watcher.domain.regime.config import DEFAULT_REGIME_CONFIG, RegimeConfig
from us_watcher.domain.regime.score import RegimeResult
from us_watcher.market.schemas import NarrativeBlock, RegimeNarrative

# Human-readable names for the regime components (the score's building blocks).
_COMPONENT_LABELS: dict[str, tuple[str, str]] = {
    "trend": ("Trend", "추세"),
    "breadth": ("Breadth", "시장 폭"),
    "volatility": ("Volatility", "변동성"),
    "liquidity": ("Liquidity", "유동성"),
    "credit": ("Credit", "신용"),
    "earnings": ("Earnings", "실적"),
    "macro_surprise": ("Macro surprises", "경제지표 서프라이즈"),
    "valuation": ("Valuation", "밸류에이션(가치평가)"),
    "positioning": ("Positioning", "투자자 포지션"),
    "cross_asset": ("Cross-asset", "다른 자산군(금리·달러 등)"),
}


def _pct(x: float | None, digits: int = 1) -> str:
    return "n/a" if x is None else f"{x * 100:+.{digits}f}%"


def _strength_word(v: float) -> tuple[str, str]:
    """A signed sub-score in [-1, 1] -> (en, ko) strength phrase."""
    a = abs(v)
    if v >= 0:
        if a >= 0.5:
            return ("strongly positive", "강한 우호")
        if a >= 0.2:
            return ("positive", "우호")
        return ("mildly positive", "약한 우호")
    if a >= 0.5:
        return ("strongly negative", "강한 부담")
    if a >= 0.2:
        return ("negative", "부담")
    return ("mildly negative", "약한 부담")


def _conviction(result: RegimeResult) -> tuple[str, str]:
    """Headline qualifier from confidence — direction vs. how sure we are."""
    c = result.confidence
    if c >= 65:
        return ("direction and strength both clear", "방향·강도 모두 뚜렷")
    if c >= 45:
        return ("direction is clear but conviction is moderate", "방향은 또렷하나 확신은 중간")
    return ("signals are limited — treat as a tilt, not a high-conviction call",
            "신호가 제한적 — 고확신보다 '방향성 우위' 정도로 해석")


def _driver_bullets(
    result: RegimeResult,
    *,
    gap: float | None,
    vix_level: float | None,
    spx: FeatureSet | None,
    dollar_ret20: float | None,
    curve: float | None,
) -> tuple[list[str], list[str]]:
    """Concrete, number-backed bullets for each measured component."""
    comps = result.components.model_dump()
    en: list[str] = []
    ko: list[str] = []

    def add(en_s: str, ko_s: str) -> None:
        en.append(en_s)
        ko.append(ko_s)

    # Order by the magnitude of each component's contribution so the strongest
    # signal is read first.
    order = sorted(
        (n for n in result.available),
        key=lambda n: abs(comps.get(n) or 0.0),
        reverse=True,
    )
    for name in order:
        v = comps.get(name)
        if v is None:
            continue
        label_en, label_ko = _COMPONENT_LABELS.get(name, (name, name))
        sw_en, sw_ko = _strength_word(float(v))
        detail_en = ""
        detail_ko = ""
        if name == "trend" and spx is not None:
            ma = "above its 200-day average" if spx.above_ma200 else "below its 200-day average"
            ma_ko = "200일선 위" if spx.above_ma200 else "200일선 아래"
            detail_en = f" — S&P {ma}, 1-month {_pct(spx.returns.get('r20'))}"
            detail_ko = f" — S&P가 {ma_ko}, 1개월 {_pct(spx.returns.get('r20'))}"
        elif name == "volatility" and vix_level is not None:
            band_en = "elevated" if vix_level >= 20 else "calm" if vix_level <= 15 else "moderate"
            band_ko = "높음" if vix_level >= 20 else "안정" if vix_level <= 15 else "보통"
            detail_en = f" — VIX {vix_level:.1f} ({band_en})"
            detail_ko = f" — VIX {vix_level:.1f} ({band_ko})"
        elif name == "breadth" and gap is not None:
            detail_en = (
                f" — cap-weight vs equal-weight gap {_pct(gap)} "
                f"({'mega-cap-led, narrow' if gap >= 0.02 else 'broad participation'})"
            )
            detail_ko = (
                f" — 시총가중 vs 동일가중 격차 {_pct(gap)} "
                f"({'대형주 쏠림(좁음)' if gap >= 0.02 else '광범위한 참여'})"
            )
        elif name == "cross_asset":
            bits_en, bits_ko = [], []
            if dollar_ret20 is not None:
                bits_en.append(f"dollar 1-month {_pct(dollar_ret20)}")
                bits_ko.append(f"달러 1개월 {_pct(dollar_ret20)}")
            if curve is not None:
                bits_en.append(f"10Y–2Y {curve:+.2f}pp")
                bits_ko.append(f"10Y–2Y {curve:+.2f}%p")
            if bits_en:
                detail_en = " — " + ", ".join(bits_en)
                detail_ko = " — " + ", ".join(bits_ko)
        add(f"{label_en} {sw_en}{detail_en}.", f"{label_ko} {sw_ko}{detail_ko}.")
    return en, ko


def _stance(result: RegimeResult) -> tuple[str, str]:
    """Framework-level positioning implication for the regime (analysis, not advice)."""
    r = result.regime
    table: dict[MarketRegime, tuple[str, str]] = {
        MarketRegime.STRONG_UPTREND: (
            "Risk-on. The framework favours staying invested and adding to leaders on "
            "pullbacks rather than chasing; lead with relative-strength sectors and scale "
            "entries in. Trend-following works best here.",
            "위험선호 국면. 일반적으로 위험자산 비중을 유지~확대하고, 주도(상대강도 상위) 섹터 "
            "중심으로 눌림목에서 분할 매수하는 전략이 유효합니다. 추세추종이 잘 통하는 구간입니다.",
        ),
        MarketRegime.MODERATE_UPTREND: (
            "Selective risk-on. A constructive but less forceful tape — favour quality "
            "leaders, keep some dry powder, and avoid over-paying for laggards hoping they "
            "catch up.",
            "선별적 위험선호. 우호적이지만 강도는 약한 국면 — 우량 주도주 위주로 접근하고 "
            "현금 여력을 일부 남기며, 뒤처진 종목의 '따라잡기'에 무리하게 베팅하지 않는 편이 낫습니다.",
        ),
        MarketRegime.SELECTIVE_BULL: (
            "Risk-on but narrow. The advance is mega-cap-led, so breadth is thin — favour the "
            "leaders actually driving the index, be wary that a stumble in a few names hits the "
            "tape hard, and don't assume the rally is broadly healthy.",
            "위험선호이나 폭이 좁음. 상승이 대형주 주도라 시장 폭이 얇습니다 — 실제로 지수를 "
            "끌어올리는 주도주 중심으로 접근하되, 소수 종목이 흔들리면 지수 충격이 크다는 점을 "
            "감안하고, 상승이 '전반적으로 건강하다'고 단정하지 마세요.",
        ),
        MarketRegime.OVERHEATED_RALLY: (
            "Risk-on but fragile. Strong tape with elevated volatility — the framework leans "
            "toward trimming into strength, tightening risk limits, and considering hedges "
            "rather than adding aggressively.",
            "위험선호이나 취약. 강세이지만 변동성이 높은 국면 — 일반적으로 강세 구간에서 일부 "
            "차익실현, 리스크 한도 축소, 헤지 고려가 우선이며 공격적 추가매수는 신중해야 합니다.",
        ),
        MarketRegime.NEUTRAL_RANGE: (
            "Balanced / range tactics. No durable trend — favour quality and income, buy "
            "support / sell resistance rather than breakouts, and wait for a confirmed move "
            "out of the range before pressing direction.",
            "중립 / 박스권 전술. 지속적 추세가 없는 국면 — 우량·인컴 위주로, 돌파 추격보다 "
            "지지에서 매수·저항에서 매도가 유효하며, 박스권 이탈이 '확인'된 뒤 방향에 무게를 "
            "싣는 편이 안전합니다.",
        ),
        MarketRegime.CORRECTION: (
            "Risk-off. The framework favours reducing exposure, raising cash, leaning to "
            "defensives, and waiting for stabilisation (volatility easing, price reclaiming key "
            "averages) before re-engaging.",
            "위험회피 국면. 일반적으로 위험노출을 줄이고 현금 비중을 높이며 방어주로 기울이고, "
            "변동성 진정·주요 이동평균선 회복 등 '안정 신호'를 확인한 뒤 재진입하는 전략이 유효합니다.",
        ),
        MarketRegime.BEAR_MARKET: (
            "Defensive / capital preservation. A structural downtrend — the framework "
            "prioritises protecting capital: minimal risk exposure, quality and defensives only, "
            "and patience for a confirmed bottoming process.",
            "방어 / 자본 보존 국면. 구조적 하락추세 — 자본 보존이 최우선입니다. 위험노출 최소화, "
            "우량·방어주 위주, 그리고 '바닥 형성'이 확인될 때까지 인내가 필요합니다.",
        ),
    }
    base_en, base_ko = table.get(
        r,
        (
            "Signals are insufficient for a firm stance — wait for more data before pressing "
            "direction.",
            "스탠스를 정하기엔 신호가 부족합니다 — 데이터가 더 쌓일 때까지 방향 베팅을 미루세요.",
        ),
    )
    # Size to conviction: low coverage / confidence means smaller, slower.
    if result.confidence < 45 or result.coverage < 0.5:
        base_en += (
            " Because only part of the picture is measured, size positions smaller and lean on "
            "your own confirmation."
        )
        base_ko += (
            " 다만 그림의 일부만 측정됐으므로 포지션은 작게, 본인의 추가 확인을 곁들이는 것이 "
            "바람직합니다."
        )
    return base_en, base_ko


def _watch(
    result: RegimeResult, *, vix_level: float | None, gap: float | None, config: RegimeConfig
) -> tuple[list[str], list[str]]:
    """Concrete, threshold-based invalidation signals — the decision criteria."""
    en: list[str] = []
    ko: list[str] = []
    score = result.score

    # Nearest band boundary that would change the regime label.
    if score >= 35:
        en.append("Composite dropping below +35 downgrades 'strong' to 'moderate' uptrend.")
        ko.append("종합점수가 +35 아래로 내려오면 '강한 상승'→'완만한 상승'으로 한 단계 약화.")
    elif score >= 10:
        en.append("Composite above +35 confirms a strong uptrend; below +10 slips to neutral.")
        ko.append("종합점수 +35 상향 돌파 시 '강한 상승' 확정, +10 하향 이탈 시 '중립'으로 후퇴.")
    elif score > -9:
        en.append("A break above +10 turns the tape constructive; below −9 opens a correction.")
        ko.append("+10 상향 돌파 시 우호적 전환, −9 하향 이탈 시 '조정' 진입.")
    else:
        en.append("Reclaiming −9 would lift the regime out of correction toward neutral.")
        ko.append("−9 회복 시 '조정'에서 벗어나 '중립' 방향으로 개선.")

    en.append(f"VIX through {config.overheated_vix:.0f} flags an overheated / fragile tape.")
    ko.append(f"VIX가 {config.overheated_vix:.0f}을 넘으면 과열·취약 신호.")

    gap_pct = config.selective_breadth_gap * 100
    if gap is not None and gap >= config.selective_breadth_gap:
        en.append("Cap-weight already leads equal-weight — watch for the few leaders to roll over.")
        ko.append("이미 시총가중이 동일가중을 앞섭 — 소수 주도주의 꺾임을 주시.")
    else:
        en.append(
            f"Cap-weight leading equal-weight by ≥{gap_pct:.0f}pp would flag a narrowing, "
            "mega-cap-led advance."
        )
        ko.append(f"시총가중이 동일가중을 {gap_pct:.0f}%p 이상 앞서면 '대형주 쏠림(폭이 좁은 상승)' 경고.")
    return en, ko


def build_regime_narrative(
    result: RegimeResult,
    *,
    gap: float | None = None,
    vix_level: float | None = None,
    spx: FeatureSet | None = None,
    dollar_ret20: float | None = None,
    curve: float | None = None,
    config: RegimeConfig = DEFAULT_REGIME_CONFIG,
) -> RegimeNarrative:
    """Compose the full structured regime narrative from computed inputs."""
    conv_en, conv_ko = _conviction(result)
    sign_en = "up" if result.score >= 10 else "down" if result.score <= -10 else "sideways"
    sign_ko = "상승" if result.score >= 10 else "하락" if result.score <= -10 else "횡보"

    headline_en = f"{result.regime_en} — {conv_en}."
    headline_ko = f"{result.regime_ko} — {conv_ko}."

    # Summary: the score, what the label means, and the dominant signal.
    top_driver = ""
    top_driver_ko = ""
    if result.available:
        comps = result.components.model_dump()
        name = max(result.available, key=lambda n: abs(comps.get(n) or 0.0))
        lbl_en, lbl_ko = _COMPONENT_LABELS.get(name, (name, name))
        top_driver = f" The dominant signal is {lbl_en.lower()}."
        top_driver_ko = f" 가장 큰 영향을 준 신호는 '{lbl_ko}'입니다."
    summary_en = (
        f"The overall market-state score is {result.score:+.0f} on a −100…+100 scale, which puts the "
        f"market in a '{result.regime_en}' phase (a {sign_en}-leaning market). Confidence is "
        f"{result.confidence:.0f}% — {conv_en}.{top_driver}"
    )
    summary_ko = (
        f"종합 점수는 −100~+100 척도에서 {result.score:+.0f}로, 지금 시장은 '{result.regime_ko}' "
        f"국면({sign_ko} 우위)입니다. 신뢰도는 {result.confidence:.0f}%로 {conv_ko}입니다.{top_driver_ko}"
    )

    drv_en, drv_ko = _driver_bullets(
        result, gap=gap, vix_level=vix_level, spx=spx, dollar_ret20=dollar_ret20, curve=curve
    )
    stance_en, stance_ko = _stance(result)
    watch_en, watch_ko = _watch(result, vix_level=vix_level, gap=gap, config=config)

    # Coverage: be honest about what was and wasn't measured.
    measured = ", ".join(_COMPONENT_LABELS.get(n, (n, n))[0] for n in result.available) or "none"
    measured_ko = ", ".join(_COMPONENT_LABELS.get(n, (n, n))[1] for n in result.available) or "없음"
    missing_ko = ", ".join(_COMPONENT_LABELS.get(n, (n, n))[1] for n in result.unavailable)
    missing_en = ", ".join(_COMPONENT_LABELS.get(n, (n, n))[0] for n in result.unavailable)
    cov_en = (
        f"{result.coverage * 100:.0f}% of the scoring weight could be measured ({measured}). "
        + (f"Not measured (excluded): {missing_en}. " if result.unavailable else "")
        + "The score is calculated using only what was measured, so a missing input never silently "
        "drags it to zero — but the narrower the coverage, the more we hold confidence back."
    )
    cov_ko = (
        f"점수에 들어가는 항목 중 {result.coverage * 100:.0f}%만 측정됐습니다(측정: {measured_ko}). "
        + (f"측정 안 됨(제외): {missing_ko}. " if result.unavailable else "")
        + "측정된 항목만으로 점수를 다시 계산하므로 빠진 데이터가 점수를 0으로 끌어내리지는 않지만, "
        "측정된 범위가 좁을수록 신뢰도를 보수적으로 낮춥니다."
    )

    blocks = [
        NarrativeBlock(
            key="summary", label_en="What it means", label_ko="무슨 뜻인가",
            body_en=summary_en, body_ko=summary_ko,
        ),
        NarrativeBlock(
            key="drivers", label_en="Key drivers", label_ko="핵심 동인",
            bullets_en=drv_en, bullets_ko=drv_ko,
        ),
        NarrativeBlock(
            key="stance", label_en="How to position", label_ko="투자 대응",
            body_en=stance_en, body_ko=stance_ko,
        ),
        NarrativeBlock(
            key="watch", label_en="What to watch", label_ko="관전 포인트",
            bullets_en=watch_en, bullets_ko=watch_ko,
        ),
        NarrativeBlock(
            key="coverage", label_en="Data coverage", label_ko="데이터 범위",
            body_en=cov_en, body_ko=cov_ko,
        ),
    ]
    return RegimeNarrative(
        headline_en=headline_en, headline_ko=headline_ko, blocks=blocks
    )
