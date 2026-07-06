"""Static snapshot generator — bakes every API response the web UI needs into
JSON files under ``apps/web/public/data`` so the site can be served as a fully
static bundle from a CDN (GitHub Pages), independent of any running server.

Two source modes (same output):

* **live** (default when ``SNAPSHOT_API_BASE`` is set, e.g. the local
  ``http://127.0.0.1:8088``): snapshot an already-running API. Fast, and picks
  up the real subscription-Claude prose the live server already generated.
* **in-process** (CI / no server): boot the FastAPI app in-process, run the
  deterministic pipelines (news → orchestrator → recommendations → daily brief)
  against keyless live data, then dump every endpoint via an ASGI transport.

The file layout mirrors the request URLs so a tiny client shim can map a live
API path to its baked file (see ``apps/web/lib/api.ts`` static mode). Query
strings are encoded deterministically as ``path__key-value__key2-value2.json``
(keys sorted) — the exact same encoding the client computes.

Run locally against the live API:
    set SNAPSHOT_API_BASE=http://127.0.0.1:8088
    .venv\\Scripts\\python -m apps.snapshot.main
CI (in-process):
    python -m apps.snapshot.main            # no SNAPSHOT_API_BASE
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
# Output dir: the web app's static data folder by default; override with
# SNAPSHOT_OUT (e.g. to a temp dir when testing without touching the committed
# snapshot).
OUT = Path(os.environ["SNAPSHOT_OUT"]) if os.environ.get("SNAPSHOT_OUT") else (
    ROOT / "apps" / "web" / "public" / "data"
)

# Endpoints the web UI calls (see grep of apps/web for api.*). Query params must
# match what the client sends so the baked filename matches the client's lookup.
STATIC_GETS: list[tuple[str, dict[str, str]]] = [
    ("/health", {}),
    ("/health/providers", {}),
    ("/api/v1/market/overview", {}),
    ("/api/v1/market/regime", {}),
    ("/api/v1/market/cross-assets", {}),
    ("/api/v1/indices/sp500", {}),
    ("/api/v1/indices/nasdaq", {}),
    ("/api/v1/indices/dow", {}),
    ("/api/v1/indices/nyse", {}),
    ("/api/v1/rotation", {}),
    ("/api/v1/macro", {}),
    ("/api/v1/recommendations", {}),
    ("/api/v1/recommendations", {"horizon": "short"}),
    ("/api/v1/recommendations", {"horizon": "medium"}),
    ("/api/v1/recommendations", {"horizon": "medium_long"}),
    ("/api/v1/recommendations/big-bets", {}),
    ("/api/v1/news", {"limit": "60"}),
    ("/api/v1/agents/org", {}),
    ("/api/v1/agents/runs", {}),
    ("/api/v1/accuracy", {}),
    ("/api/v1/methodology", {}),
    ("/api/v1/briefings/latest", {"language": "en", "briefing_type": "full"}),
    ("/api/v1/briefings/latest", {"language": "ko", "briefing_type": "full"}),
    ("/api/v1/briefings/archive", {"language": "en"}),
    ("/api/v1/briefings/archive", {"language": "ko"}),
]


def encode_file(path: str, params: dict[str, str]) -> str:
    """Deterministic file path for (url path, query) — must match the TS client."""
    rel = path.lstrip("/")
    if params:
        q = "__".join(f"{k}-{params[k]}" for k in sorted(params))
        rel = f"{rel}__{q}"
    return f"{rel}.json"


def _write(rel_file: str, data: Any) -> None:
    dest = OUT / rel_file
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def _merge_archive(lang: str, fresh: list[dict]) -> list[dict]:
    """Union the freshly-generated brief archive with the one already baked in
    the repo, so a fresh-DB cloud run never drops historical briefs from the
    list. Keyed by (date, type); fresh entries win on conflict; newest first."""
    existing_file = OUT / encode_file("/api/v1/briefings/archive", {"language": lang})
    prior: list[dict] = []
    if existing_file.exists():
        try:
            prior = json.loads(existing_file.read_text(encoding="utf-8")).get("archive", [])
        except (json.JSONDecodeError, OSError):
            prior = []
    by_key: dict[tuple[str, str], dict] = {}
    for item in [*prior, *fresh]:  # fresh last -> overrides prior
        key = (str(item.get("briefing_date")), str(item.get("briefing_type")))
        by_key[key] = item
    return sorted(by_key.values(), key=lambda i: str(i.get("briefing_date")), reverse=True)


async def _run_pipelines() -> None:
    """CI path: populate a fresh DB from keyless live data + subscription prose."""
    from us_watcher.agent_service.orchestrator import run_orchestrator
    from us_watcher.agent_service.recommendation_pipeline import generate_recommendations
    from us_watcher.briefing.service import generate_daily_brief
    from us_watcher.db.seed import seed_instruments
    from us_watcher.domain.enums import BriefingType
    from us_watcher.infrastructure.db import create_all
    from us_watcher.newsfeed.service import sync_news

    await create_all()
    await seed_instruments()
    print("[pipelines] news sync…")
    await sync_news()
    print("[pipelines] orchestrator (chief house view)…")
    run = await run_orchestrator(objective="market_overview", trigger="snapshot")
    chief = (run or {}).get("chief", {})
    print(f"  chief model={chief.get('model')} is_mock={chief.get('is_mock')}")
    print("[pipelines] recommendations…")
    recs = await generate_recommendations()
    print(f"  generated={recs.get('generated')} skipped={recs.get('skipped')}")
    print("[pipelines] daily brief (EN+KO)…")
    await generate_daily_brief(BriefingType.FULL)


async def _client(base: str | None) -> tuple[httpx.AsyncClient, Any]:
    if base:
        return httpx.AsyncClient(base_url=base.rstrip("/"), timeout=30.0), None
    # In-process ASGI (no network server). Lifespan is NOT run by ASGITransport,
    # so we seed/prewarm explicitly via _run_pipelines() beforehand.
    from us_watcher.api.app import create_app

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://snapshot", timeout=60.0), app


async def main() -> None:
    from us_watcher.domain.time import now_utc

    base = os.environ.get("SNAPSHOT_API_BASE")  # live API if set, else in-process
    mode = "live" if base else "in-process"
    print(f"[snapshot] mode={mode} out={OUT}")

    if not base:
        # keyless providers + subscription prose (falls back to deterministic).
        os.environ.setdefault("MARKET_DATA_PROVIDER", "yahoo")
        os.environ.setdefault("NEWS_PROVIDER", "google")
        if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
            os.environ.setdefault("AGENT_RUNTIME", "llm")
            os.environ.setdefault("LLM_PROVIDER", "claude_cli")
        await _run_pipelines()

    client, _app = await _client(base)
    ok = 0
    failed: list[str] = []
    try:
        # discover archived briefings (date × type) to bake per-date views.
        # A cloud (CI) run has a fresh, empty DB — so its archive only holds
        # today's briefs. To avoid the site's "past briefs" list shrinking on
        # every cloud refresh, MERGE the fresh archive with the one already baked
        # in the repo (their byDate files persist on disk from prior runs).
        gets = list(STATIC_GETS)
        for lang in ("en", "ko"):
            r = await client.get("/api/v1/briefings/archive", params={"language": lang})
            fresh = r.json().get("archive", []) if r.status_code == 200 else []
            merged = _merge_archive(lang, fresh)
            _write(encode_file("/api/v1/briefings/archive", {"language": lang}), {"archive": merged})
            for item in merged:
                gets.append(("/api/v1/briefings/" + str(item["briefing_date"]),
                             {"language": lang, "briefing_type": str(item["briefing_type"])}))
        # archive endpoints are now pre-written (merged) — don't re-dump them.
        gets = [g for g in gets if g[0] != "/api/v1/briefings/archive"]

        for path, params in gets:
            rel = encode_file(path, params)
            try:
                resp = await client.get(path, params=params)
            except Exception as exc:  # network/ASGI error
                failed.append(f"{path} {params}: {exc!r}"[:200])
                continue
            if resp.status_code != 200:
                # A historical brief absent from a fresh CI DB (404) but already
                # baked on disk from a prior run is fine — keep the existing file.
                if resp.status_code == 404 and (OUT / rel).exists():
                    ok += 1
                    continue
                failed.append(f"{path} {params}: HTTP {resp.status_code}")
                continue
            _write(rel, resp.json())
            ok += 1

        # Data-health signal so a cloud refresh can refuse to publish a snapshot
        # built on MOCK prices (invariant 2): count non-live cards in the overview.
        mock_cards = total_cards = 0
        try:
            ov = await client.get("/api/v1/market/overview")
            cards = ov.json().get("cards", []) if ov.status_code == 200 else []
            total_cards = len(cards)
            mock_cards = sum(1 for c in cards if str(c.get("status")) == "MOCK")
        except Exception as exc:  # data-health probe is best-effort
            print(f"[snapshot] data-health probe failed: {exc!r}"[:200])
        mock_fraction = (mock_cards / total_cards) if total_cards else 1.0
        live_data = total_cards > 0 and mock_fraction < 0.5

        # A static "refresh status" so the nav can show the last update time.
        _write("api/v1/refresh/status.json", {
            "running": False, "started_at": None, "finished_at": now_utc().isoformat(),
            "ok": True, "detail": "static snapshot", "last_success_at": now_utc().isoformat(),
            "cooldown_remaining_seconds": 0, "llm": "static", "static": True,
        })
        _write("meta.json", {"generated_at": now_utc().isoformat(), "mode": mode,
                             "files": ok, "failed": failed, "live_data": live_data,
                             "mock_cards": mock_cards, "total_cards": total_cards})
    finally:
        await client.aclose()

    print(f"[snapshot] wrote {ok} files → {OUT}")
    if failed:
        print(f"[snapshot] {len(failed)} endpoint(s) failed:")
        for f in failed:
            print("  -", f)


if __name__ == "__main__":
    asyncio.run(main())
