"""Extract us-watcher's deterministic market context (regime + index cards + rotation)
for the session-authored narrative. No Anthropic calls. Run with venv python, cwd=us-watcher."""
import json
import asyncio


def safe(o, depth=0):
    if depth > 7:
        return str(o)[:300]
    if isinstance(o, str):
        return o[:1500]
    if isinstance(o, (int, float, bool)) or o is None:
        return o
    if isinstance(o, dict):
        return {str(k): safe(v, depth + 1) for k, v in list(o.items())[:80]}
    if isinstance(o, (list, tuple)):
        return [safe(v, depth + 1) for v in list(o)[:40]]
    if hasattr(o, "model_dump"):
        try:
            return safe(o.model_dump(mode="json"), depth + 1)
        except Exception:
            pass
    if hasattr(o, "__dict__"):
        return safe(vars(o), depth + 1)
    return str(o)[:300]


async def main():
    from us_watcher.market.service import get_market_service
    svc = get_market_service()
    out = {}
    try:
        ov = await svc.build_overview()
        out["overview"] = safe(ov)
        try:
            out["regime"] = ov.pulse.model_dump(mode="json")
        except Exception as e:
            out["regime_err"] = str(e)[:200]
    except Exception as e:
        out["overview_err"] = repr(e)[:300]
    try:
        rot = await svc.build_rotation()
        out["rotation"] = safe(rot)
    except Exception as e:
        out["rotation_err"] = repr(e)[:300]

    json.dump(safe(out), open("us_context.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    reg = out.get("regime") or {}
    print("regime:", reg.get("regime"), "| score:", reg.get("score"),
          "| coverage:", reg.get("coverage"))
    print("keys:", list(out.keys()))


if __name__ == "__main__":
    asyncio.run(main())
