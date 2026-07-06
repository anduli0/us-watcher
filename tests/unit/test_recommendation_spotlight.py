"""Unit tests for the curated house-spotlight overlay (HOT/Big-Bet floors).

The spotlight is an explicitly-labelled editorial input (NOT market data): its
``heat`` floors the hotness/HOT ranking and its ``conviction`` floors the
moonshot/Big-Bet ranking, so a genuinely in-focus name (a turnaround, a fresh
spin-off, a pre-revenue disruptor) with thin keyless signals still surfaces.
"""

from __future__ import annotations

from datetime import UTC, datetime

from us_watcher.agent_service.recommendation_pipeline import (
    _hotness,
    _moonshot,
    _price_is_corrupt,
    rank_big_bets,
)
from us_watcher.domain.analytics.features import FeatureSet
from us_watcher.domain.universe import SpotlightEntry, get_universe


def _feat(*, r20: float = 0.01, dist_from_high: float = 0.0, above_ma200: bool = True) -> FeatureSet:
    """A minimal FeatureSet with deliberately weak keyless signals."""
    return FeatureSet(
        symbol="TEST",
        as_of=datetime.now(UTC),
        n_bars=300,
        last_close=100.0,
        returns={"r20": r20, "r60": 0.0},
        moving_averages={"ma50": 100.0, "ma200": 100.0},
        ma200_slope=0.0,
        rsi14=50.0,
        macd_hist=0.0,
        atr14=1.0,
        realized_vol_20=0.25,
        max_drawdown=-0.1,
        distance_from_52w_high=dist_from_high,
        above_ma50=True,
        above_ma200=above_ma200,
    )


def test_spotlight_heat_floors_hotness():
    feat = _feat(r20=0.01)  # tiny move, no fundamentals → naturally low heat
    plain = _hotness(feat, None, None, 50.0)
    spot = _hotness(feat, None, None, 50.0, spotlight=SpotlightEntry(symbol="INTC", heat=88.0))
    assert plain < 20.0  # keyless-only heat is low
    assert spot >= 88.0  # the house heat floor lifts it into HOT
    assert spot > plain


def test_spotlight_conviction_floors_moonshot():
    feat = _feat(dist_from_high=0.0)  # no fundamentals → growth story absent
    plain = _moonshot(feat, None, None)
    spot = _moonshot(feat, None, None, spotlight=SpotlightEntry(symbol="SNDK", conviction=80.0))
    assert plain < 5.0  # without a growth story or conviction it scores ~0
    assert spot >= 60.0  # the house conviction floor surfaces it as a Big Bet
    assert spot > plain


def test_spotlight_conviction_amplified_by_cheapness():
    # The further below its 52-week high, the more the conviction floor is amplified.
    entry = SpotlightEntry(symbol="OKLO", conviction=70.0)
    at_high = _moonshot(_feat(dist_from_high=0.0), None, None, spotlight=entry)
    beaten = _moonshot(_feat(dist_from_high=-0.35, above_ma200=False), None, None, spotlight=entry)
    assert beaten > at_high


def test_no_spotlight_leaves_scores_unchanged():
    feat = _feat(r20=0.01)
    assert _hotness(feat, None, None, 50.0, spotlight=None) == _hotness(feat, None, None, 50.0)
    assert _moonshot(feat, None, None, spotlight=None) == _moonshot(feat, None, None)


def test_universe_spotlight_loaded_and_consistent():
    u = get_universe()
    assert u.spotlight, "spotlight overlay should be populated from universe.yml"
    assert "INTC" in u.spotlight, "Intel must be on the spotlight (the user's HOT example)"
    assert "MU" in u.spotlight, "MU should carry the memory-cycle (SanDisk-type) Big-Bet theme"
    stock_syms = {s.symbol for s in u.stocks}
    for sym, entry in u.spotlight.items():
        # Every spotlight name must exist in the stock universe, else it is never built.
        assert sym in stock_syms, f"spotlight {sym} missing from stocks:"
        assert entry.note_ko and entry.note_en, f"spotlight {sym} needs a bilingual note"
        assert 0.0 <= entry.heat <= 100.0 and 0.0 <= entry.conviction <= 100.0


def test_rank_big_bets_dedupes_filters_and_caps():
    recs = [
        {"ticker": "SNDK", "asset_type": "stock", "moonshot_score": 60},
        {"ticker": "SNDK", "asset_type": "stock", "moonshot_score": 82},   # higher wins for the ticker
        {"ticker": "OKLO", "asset_type": "stock", "moonshot_score": 80},
        {"ticker": "AAPL", "asset_type": "stock", "moonshot_score": 0},     # zero filtered out
        {"ticker": "SPY", "asset_type": "etf", "moonshot_score": 95},       # ETFs excluded
    ]
    out = rank_big_bets(recs, n=6)
    tickers = [r["ticker"] for r in out]
    assert tickers == ["SNDK", "OKLO"]            # sorted desc, deduped, no zeros, no ETF
    assert out[0]["moonshot_score"] == 82          # kept the higher SNDK row


def test_rank_big_bets_caps_to_n():
    recs = [{"ticker": f"T{i}", "asset_type": "stock", "moonshot_score": i + 1} for i in range(10)]
    assert len(rank_big_bets(recs, n=6)) == 6


def test_price_corruption_guard():
    # A chart price wildly out of line with the analyst target = corrupt source data.
    assert _price_is_corrupt(1134.0, 150.0)        # "$1,134 Micron" vs ~$150 target → corrupt
    assert _price_is_corrupt(2184.0, 50.0)         # "$2,184 SanDisk" → corrupt
    assert not _price_is_corrupt(56.55, 68.0)      # IonQ vs target → fine
    assert not _price_is_corrupt(1099.0, 1000.0)   # legit high-price (Eli Lilly) → fine
    assert not _price_is_corrupt(100.0, None)      # no analyst target → can't judge → trust
    assert not _price_is_corrupt(None, 50.0)       # no price → not "corrupt"


def test_every_universe_symbol_is_a_string():
    # Guards the YAML-1.1-boolean trap: a bare ON/OFF/YES/NO ticker parses to a
    # Python bool and detonates deep in a live fetch. ON Semiconductor must stay "ON".
    u = get_universe()
    for inst in u.all_instruments():
        assert isinstance(inst.symbol, str), f"{inst.name}: symbol {inst.symbol!r} is not a str"
        assert inst.yahoo_symbol is None or isinstance(inst.yahoo_symbol, str)
    assert "ON" in {s.symbol for s in u.stocks}, "ON Semiconductor should be present and a string"
