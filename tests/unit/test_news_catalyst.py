"""Unit tests for the news_catalyst component score (spec §24, §28)."""

from __future__ import annotations

from datetime import timedelta

from us_watcher.domain.recommendation.catalyst import news_catalyst_score
from us_watcher.domain.time import now_utc


def _cluster(importance=70.0, count=6, age_h=2.0):
    return {
        "importance": importance,
        "article_count": count,
        "last_seen": (now_utc() - timedelta(hours=age_h)).isoformat(),
    }


def test_no_coverage_returns_none():
    assert news_catalyst_score([], 0.05) is None


def test_only_stale_coverage_returns_none():
    # Coverage far in the past has ~0 recency weight → treated as no live catalyst.
    assert news_catalyst_score([_cluster(age_h=1000.0)], 0.05) is None


def test_fresh_coverage_with_positive_reaction_is_bullish():
    s = news_catalyst_score([_cluster()], 0.06)  # market up 6% on the news
    assert s is not None and s > 55.0


def test_fresh_coverage_with_negative_reaction_is_bearish():
    s = news_catalyst_score([_cluster()], -0.06)
    assert s is not None and s < 45.0


def test_flat_price_reaction_is_neutral():
    # Attention noted, but the market hasn't picked a direction → ~50, never a
    # blind bullish boost from buzz alone.
    s = news_catalyst_score([_cluster()], 0.0)
    assert s == 50.0


def test_missing_price_reaction_is_neutral_not_none():
    s = news_catalyst_score([_cluster()], None)
    assert s == 50.0


def test_more_attention_amplifies_direction():
    weak = news_catalyst_score([_cluster(importance=25.0, count=1)], 0.06)
    strong = news_catalyst_score([_cluster(importance=95.0, count=12)], 0.06)
    assert strong is not None and weak is not None and strong > weak


def test_naive_last_seen_is_treated_as_utc_not_zeroed():
    # SQLite drops tzinfo on read; a naive (but UTC) last_seen must still count as a
    # live catalyst, not silently score 0 (the "all None on SQLite" regression).
    naive = now_utc().replace(tzinfo=None)
    s = news_catalyst_score(
        [{"importance": 70.0, "article_count": 6, "last_seen": naive.isoformat()}], 0.06)
    assert s is not None and s > 55.0


def test_stock_query_map_attributes_names_to_tickers():
    from us_watcher.newsfeed.service import _stock_query_map

    m = _stock_query_map(60)
    assert m.get("Tesla stock") == "TSLA"
    assert m.get("Micron Technology stock") == "MU"


def test_catalysts_surface_real_headlines_when_tagged_news_exists():
    from us_watcher.agent_service.recommendation_pipeline import _catalysts
    from us_watcher.domain.universe import Instrument

    inst = Instrument(symbol="TSLA", name="Tesla", group="stock")
    clusters = [
        {"headline": "Tesla ships FSD light for HW3 cars", "importance": 88.0, "last_seen": "2026-07-13T00:00:00+00:00"},
        {"headline": "Analysts weigh Tesla robotaxi timeline", "importance": 40.0, "last_seen": "2026-07-12T00:00:00+00:00"},
    ]
    en, ko = _catalysts(inst, None, clusters)
    assert en[0] == "📰 Tesla ships FSD light for HW3 cars"  # top by importance
    assert any("FSD light" in x for x in ko)


def test_catalysts_fall_back_to_calendar_without_news():
    from us_watcher.agent_service.recommendation_pipeline import _catalysts
    from us_watcher.domain.universe import Instrument

    inst = Instrument(symbol="TSLA", name="Tesla", group="stock")
    en, _ = _catalysts(inst, None, None)
    assert not any(x.startswith("📰") for x in en)
    assert any("earnings season" in x.lower() for x in en)
