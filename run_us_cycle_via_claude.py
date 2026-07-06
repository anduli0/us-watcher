"""
One-shot US-Watcher cycle driven by THIS Claude Code session (no console credits).

us-watcher's NUMBERS (regime, direction, 8-action recommendations) are deterministic —
they never needed the LLM. The only thing the dead Anthropic key broke is the chief
house-view PROSE (it silently falls back to a terse deterministic string). So reviving =
(1) re-run the deterministic pipeline so today's numbers + recommendations are fresh, and
(2) inject a real, session-authored EN/KO house-view narrative.

We monkeypatch the LLM provider factory to return a stub that serves our pre-authored
narrative (no Anthropic call), then call the worker's REAL drivers:
  * run_orchestrator(trigger="forced")  -> persists a fresh run + our narrative
  * generate_recommendations()          -> refreshes the per-asset action board (deterministic)

Run with the venv python, cwd = us-watcher:
    .venv\\Scripts\\python.exe run_us_cycle_via_claude.py
"""
import json
import os
import sqlite3
import asyncio

NARR_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "us_narrative.json")
DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "us_watcher.db")


def _load():
    with open(NARR_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


async def main():
    narr = _load()
    en = (narr.get("narrative_en") or "").strip()
    ko = (narr.get("narrative_ko") or "").strip()
    print(f"[load] narrative EN {len(en)} chars · KO {len(ko)} chars")

    from us_watcher.infrastructure.llm.base import LLMResult

    class SessionProvider:
        name = "claude-code-session"
        is_mock = False

        async def generate_text(self, system, user, *, role="editor", max_tokens=1024):
            if role == "reasoning":
                txt = en
            elif role == "editor":
                txt = ko
            else:
                txt = ko if any("가" <= ch <= "힣" for ch in (user or "")) else en
            return LLMResult(text=txt, model="claude-code-session", provider=self.name,
                             is_mock=False, input_tokens=0, output_tokens=max(1, len(txt) // 4))

        async def generate_structured(self, prompt, *, role="reasoning"):
            from us_watcher.infrastructure.llm.mock import MockLLMProvider
            return await MockLLMProvider().generate_structured(prompt, role=role)

    import us_watcher.infrastructure.llm.factory as factory
    factory.get_llm_provider = lambda: SessionProvider()

    from us_watcher.agent_service.orchestrator import run_orchestrator
    from us_watcher.agent_service.recommendation_pipeline import generate_recommendations

    print("[run] run_orchestrator(trigger='forced') ...")
    r1 = await run_orchestrator(objective="market_overview", trigger="forced")
    ch = r1.get("chief", {})
    print(f"  regime={r1.get('regime')} aggregate={r1.get('aggregate')}")
    print(f"  chief.is_mock={ch.get('is_mock')} model={ch.get('model')} agents={r1.get('agent_count')}")

    print("[run] generate_recommendations() ...")
    r2 = await generate_recommendations()
    print("  recs:", {k: r2.get(k) for k in ("generated", "skipped", "reason",
                                              "mock_fraction", "by_action", "as_of")})
    print("[done] us cycle complete.")

    # Verify from DB (read-only).
    try:
        c = sqlite3.connect(f"file:{DB_FILE}?mode=ro", uri=True)
        run = c.execute("select id, started_at, runtime, token_usage, payload "
                        "from orchestrator_runs order by started_at desc limit 1").fetchone()
        if run:
            payload = json.loads(run[4]) if run[4] else {}
            chief = payload.get("chief", {})
            print(f"  [db] latest run {run[0][:8]} @ {run[1]} runtime={run[2]} "
                  f"chief.is_mock={chief.get('is_mock')} model={chief.get('model')}")
            print(f"  [db] narrative_en starts: {str(chief.get('narrative_en'))[:90]}")
        rc = c.execute("select max(as_of) from recommendations").fetchone()
        print(f"  [db] latest recommendation as_of: {rc[0] if rc else None}")
        c.close()
    except Exception as e:
        print("  [db] verify err:", repr(e)[:200])


if __name__ == "__main__":
    asyncio.run(main())
