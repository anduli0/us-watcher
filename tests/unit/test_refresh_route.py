"""Public refresh trigger — single-flight, cooldown, and status shape."""

from __future__ import annotations

import asyncio

import pytest

from us_watcher.api.routes import refresh as mod


@pytest.fixture(autouse=True)
def reset_state():
    mod._state.update(running=False, started_at=None, finished_at=None,
                      ok=None, detail="", last_success_at=None)
    mod._last_start_mono = None
    yield
    mod._last_start_mono = None


async def test_trigger_starts_then_reports_cooldown(monkeypatch):
    ran = asyncio.Event()

    async def fake_refresh():
        mod._state.update(running=False, ok=True)
        ran.set()

    monkeypatch.setattr(mod, "_do_refresh", fake_refresh)
    first = await mod.trigger_refresh()
    assert first["status"] == "started"
    await asyncio.wait_for(ran.wait(), 2)
    second = await mod.trigger_refresh()
    assert second["status"] == "cooldown"
    assert second["retry_after_seconds"] > 0


async def test_trigger_while_running_is_single_flight(monkeypatch):
    release = asyncio.Event()

    async def slow_refresh():
        await release.wait()
        mod._state.update(running=False)

    monkeypatch.setattr(mod, "_do_refresh", slow_refresh)
    first = await mod.trigger_refresh()
    assert first["status"] == "started"
    second = await mod.trigger_refresh()
    assert second["status"] == "running"
    release.set()
    await asyncio.sleep(0)


async def test_status_shape():
    st = await mod.refresh_status()
    for key in ("running", "last_success_at", "cooldown_remaining_seconds", "llm"):
        assert key in st
