"""Data-integrity regressions: Yahoo retry/backoff + the recommendation mock gate.

Both guard against the incident where a burst rate-limit silently degraded the
ENTIRE recommendation board to synthetic MOCK prices (which then scored as
all-avoid / all-watch and was served as if real).
"""

from __future__ import annotations

import httpx

import us_watcher.infrastructure.marketdata.yahoo as ymod
from us_watcher.agent_service.recommendation_pipeline import mock_data_gate
from us_watcher.domain.enums import DataStatus
from us_watcher.infrastructure.marketdata.yahoo import YahooProvider


def _chart_payload() -> dict:
    """A minimal but valid ``/v8/finance/chart`` body (enough bars to build a series)."""
    n = 80
    base = 1_700_000_000
    return {"chart": {"result": [{
        "meta": {"regularMarketPrice": 101.0, "chartPreviousClose": 100.0, "currency": "USD",
                 "regularMarketTime": base + n * 86_400},
        "timestamp": [base + i * 86_400 for i in range(n)],
        "indicators": {"quote": [{
            "open": [100.0 + i * 0.1 for i in range(n)],
            "high": [100.5 + i * 0.1 for i in range(n)],
            "low": [99.5 + i * 0.1 for i in range(n)],
            "close": [100.0 + i * 0.1 for i in range(n)],
            "volume": [1_000_000 for _ in range(n)],
        }]},
    }]}}


async def _noop_sleep(*_a: object, **_k: object) -> None:
    return None


def _patch_transport(monkeypatch, handler) -> None:
    monkeypatch.setattr(ymod, "new_async_client",
                        lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(ymod.asyncio, "sleep", _noop_sleep)  # don't actually back off in tests


# --- Yahoo retry/backoff ---------------------------------------------------------

async def test_yahoo_retries_then_succeeds_on_429(monkeypatch):
    calls = {"n": 0}

    def handler(_req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429)  # transient rate-limit on first try
        return httpx.Response(200, json=_chart_payload())

    _patch_transport(monkeypatch, handler)
    agg = await YahooProvider(max_attempts=3).get_aggregates("SPY")
    assert agg is not None and agg.source == "yahoo"
    assert calls["n"] == 2  # retried exactly once, then succeeded


async def test_yahoo_gives_up_after_max_attempts(monkeypatch):
    calls = {"n": 0}

    def handler(_req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429)

    _patch_transport(monkeypatch, handler)
    agg = await YahooProvider(max_attempts=3).get_aggregates("SPY")
    assert agg is None  # exhausted -> caller falls back to labelled MOCK
    assert calls["n"] == 3


async def test_yahoo_does_not_retry_non_retryable_status(monkeypatch):
    calls = {"n": 0}

    def handler(_req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(404)  # a real "no such symbol" — retrying is pointless

    _patch_transport(monkeypatch, handler)
    agg = await YahooProvider(max_attempts=3).get_aggregates("NOPE")
    assert agg is None
    assert calls["n"] == 1


# --- Recommendation mock-data gate ----------------------------------------------

def test_mock_gate_aborts_when_mostly_mock_in_live_mode():
    statuses = [DataStatus.MOCK] * 7 + [DataStatus.DELAYED] * 3  # 70% mock
    abort, mock_n, total, frac = mock_data_gate(statuses, live_mode=True)
    assert abort is True
    assert mock_n == 7 and total == 10 and frac == 0.7


def test_mock_gate_allows_mostly_live():
    statuses = [DataStatus.DELAYED] * 8 + [DataStatus.MOCK] * 2  # 20% mock
    abort, _mock_n, _total, frac = mock_data_gate(statuses, live_mode=True)
    assert abort is False and frac == 0.2


def test_mock_gate_aborts_on_empty_in_live_mode():
    abort, _mock_n, total, _frac = mock_data_gate([], live_mode=True)
    assert abort is True and total == 0


def test_mock_gate_never_aborts_in_explicit_mock_mode():
    # Offline/demo mode: mock is intentional and honest, so we still generate.
    statuses = [DataStatus.MOCK] * 10
    abort, _mock_n, _total, frac = mock_data_gate(statuses, live_mode=False)
    assert abort is False and frac == 1.0
