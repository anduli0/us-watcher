"""Unit tests for fundamentals-driven recommendation features (spec §24, §25)."""

from __future__ import annotations

from us_watcher.domain.analytics.features import build_features
from us_watcher.domain.analytics.series import Bar
from us_watcher.domain.fundamentals import EdgarFacts, FundamentalSnapshot
from us_watcher.domain.recommendation.features import (
    build_component_scores,
    capital_migration_components,
    earnings_revision_score,
    fundamental_quality_score,
    risk_score,
    valuation_score,
)
from us_watcher.domain.time import now_utc


def _fund(**kw) -> FundamentalSnapshot:
    base = dict(symbol="TEST", as_of=now_utc())
    base.update(kw)
    return FundamentalSnapshot(**base)


def _bars(closes: list[float]) -> list[Bar]:
    now = now_utc()
    return [Bar(as_of=now, open=c, high=c * 1.01, low=c * 0.99, close=c, volume=2_000_000) for c in closes]


def test_quality_high_for_strong_company():
    f = _fund(profit_margin=0.30, return_on_equity=0.40, gross_margin=0.70, free_cashflow=1e9, debt_to_equity=30)
    s = fundamental_quality_score(f)
    assert s is not None and s > 70


def test_quality_low_for_weak_company():
    f = _fund(profit_margin=-0.10, return_on_equity=-0.05, gross_margin=0.15, free_cashflow=-1e8, debt_to_equity=300)
    s = fundamental_quality_score(f)
    assert s is not None and s < 45


def test_quality_none_without_inputs():
    assert fundamental_quality_score(_fund()) is None


def test_valuation_cheap_growth_scores_high():
    cheap = valuation_score(_fund(peg_ratio=0.6, forward_pe=15, price_to_book=4))
    rich = valuation_score(_fund(peg_ratio=3.0, forward_pe=80, price_to_book=25))
    assert cheap is not None and rich is not None and cheap > rich


def test_earnings_revision_up_beats_down():
    up = earnings_revision_score(_fund(eps_rev_up_30d=8, eps_rev_down_30d=1, recommendation_mean=1.5))
    down = earnings_revision_score(_fund(eps_rev_up_30d=1, eps_rev_down_30d=8, recommendation_mean=3.8))
    assert up is not None and down is not None and up > down


def test_cms_components_real_and_partial():
    f = _fund(revenue_growth=0.5, eps_rev_up_30d=6, eps_rev_down_30d=1, gross_margin=0.65,
              return_on_equity=0.35, target_mean=120.0)
    comps = capital_migration_components(f, current_price=100.0)
    assert "revenue_accel_revisions" in comps
    assert "moat_barriers" in comps
    assert "valuation_upside" in comps  # 120 vs 100 -> upside
    # capex/backlog are NOT fabricated:
    assert "capex_growth" not in comps and "backlog_rpo_adoption" not in comps


def test_risk_penalises_microcap_and_losses():
    feat = build_features("TEST", _bars([100.0 + i for i in range(120)]), now_utc())
    big = risk_score(feat, _fund(market_cap=5e11, profit_margin=0.25))
    micro_loss = risk_score(feat, _fund(market_cap=8e8, profit_margin=-0.2, avg_volume=100_000))
    assert micro_loss > big


def test_build_component_scores_stock_populates_fundamentals_and_cms():
    feat = build_features("TEST", _bars([100.0 + i * 0.5 for i in range(260)]), now_utc())
    f = _fund(profit_margin=0.3, revenue_growth=0.4, return_on_equity=0.35, gross_margin=0.65,
              peg_ratio=0.9, forward_pe=22, eps_rev_up_30d=7, eps_rev_down_30d=1,
              recommendation_mean=1.6, target_mean=160.0, market_cap=8e11)
    scores, cms = build_component_scores(
        feat, _bars([100.0 + i * 0.5 for i in range(260)]),
        regime_score=40.0, rel_strength_1m=0.03, fund=f, current_price=130.0)
    assert scores.fundamental_quality is not None
    assert scores.valuation is not None
    assert scores.earnings_revision is not None
    assert scores.capital_migration is not None
    assert cms["score"] is not None and 0 < cms["coverage"] <= 1.0


def test_edgar_adds_capex_and_rnd_to_cms():
    f = _fund(revenue_growth=0.4, gross_margin=0.6, return_on_equity=0.3, target_mean=120.0)
    edgar = EdgarFacts(ticker="TEST", cik="0000000001", as_of=now_utc(),
                       capex_growth_yoy=0.5, rnd_growth_yoy=0.3)
    without = capital_migration_components(f, 100.0)
    with_edgar = capital_migration_components(f, 100.0, edgar)
    assert "capex_growth" not in without
    assert "capex_growth" in with_edgar and "hiring_rnd_patents" in with_edgar
    assert with_edgar["capex_growth"] > 50  # +50% capex growth -> elevated


def test_edgar_raises_cms_coverage():
    feat = build_features("TEST", _bars([100.0 + i * 0.5 for i in range(260)]), now_utc())
    f = _fund(profit_margin=0.3, revenue_growth=0.4, gross_margin=0.6, target_mean=160.0)
    bars = _bars([100.0 + i * 0.5 for i in range(260)])
    edgar = EdgarFacts(ticker="TEST", cik="0000000001", as_of=now_utc(),
                       capex_growth_yoy=0.4, rnd_growth_yoy=0.25)
    _, cms_no = build_component_scores(feat, bars, regime_score=40.0, rel_strength_1m=0.03,
                                       fund=f, current_price=130.0)
    _, cms_yes = build_component_scores(feat, bars, regime_score=40.0, rel_strength_1m=0.03,
                                        fund=f, edgar=edgar, current_price=130.0)
    assert cms_yes["coverage"] > cms_no["coverage"]


def test_build_component_scores_etf_leaves_fundamentals_none():
    feat = build_features("XLK", _bars([100.0 + i * 0.5 for i in range(260)]), now_utc())
    scores, cms = build_component_scores(
        feat, _bars([100.0 + i * 0.5 for i in range(260)]),
        regime_score=40.0, rel_strength_1m=0.03, fund=None, current_price=130.0)
    assert scores.fundamental_quality is None
    assert scores.capital_migration is None
    assert cms["score"] is None
