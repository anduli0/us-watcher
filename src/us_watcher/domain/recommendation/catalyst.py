"""News-catalyst component score (spec §24, §28).

Turns a stock's recent ticker-tagged news clusters into the ``news_catalyst``
component (previously wired but never fed). Deterministic and keyless — an LLM
never scores news:

* **Magnitude** = how much high-importance, RECENT coverage the name is drawing
  (the "explosive attention / new-launch buzz" the desk asked to reflect).
* **Direction** = the market's OWN recent price reaction, because no per-article
  sentiment is computed keyless. A heavily-covered catalyst the market is BUYING
  scores well above 50; the same attention into a FALLING price scores below 50;
  attention with a flat price stays ~50 (noted, but direction unknown).

No coverage → ``None`` (reweighted out of the score, never a silent 0/50).
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

from us_watcher.domain.time import now_utc


def _recency(last_seen: str | datetime | None, ref: datetime) -> float:
    """0..1 weight, ~2-day half-life — a catalyst goes stale fast."""
    if last_seen is None:
        return 0.0
    ts = datetime.fromisoformat(last_seen) if isinstance(last_seen, str) else last_seen
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)  # stored values are UTC; SQLite drops the tzinfo
    age_h = max(0.0, (ref - ts).total_seconds() / 3600.0)
    return math.exp(-age_h / 48.0)


def news_catalyst_score(
    clusters: list[dict],
    price_reaction_5d: float | None,
    *,
    as_of: datetime | None = None,
) -> float | None:
    """Score a stock's ``news_catalyst`` (0-100) from its tagged clusters.

    ``clusters`` — recent news clusters tagged to this ticker, each a dict with
    ``importance`` (0-100), ``article_count``, and ``last_seen`` (iso string or
    tz-aware datetime). ``price_reaction_5d`` — the stock's 5-session return
    fraction (the market's reaction). Returns ``None`` when the name has no
    tagged coverage.
    """
    if not clusters:
        return None
    ref = as_of or now_utc()
    attn = 0.0
    for c in clusters:
        imp = float(c.get("importance") or 0.0) / 100.0                 # 0..1
        count = float(c.get("article_count") or 1)
        confirm = 1.0 + min(1.0, (count - 1) / 8.0)                     # many outlets = real
        attn += imp * confirm * _recency(c.get("last_seen"), ref)
    attn01 = min(1.0, attn / 1.5)                                       # saturate
    if attn01 < 0.02:
        return None                                                     # only stale/negligible coverage
    react = price_reaction_5d if price_reaction_5d is not None else 0.0
    tilt = max(-45.0, min(45.0, react * 100.0 * 3.0))                  # ±15% over 5d -> ±45
    return round(max(0.0, min(100.0, 50.0 + attn01 * tilt)), 1)
