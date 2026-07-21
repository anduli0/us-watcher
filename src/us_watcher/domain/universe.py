"""Instrument-universe registry, loaded from ``config/universe.yml``.

Single source of truth for what we track and how each internal symbol maps to a
keyless Yahoo symbol / FRED series. Loaded once and cached.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_UNIVERSE_PATH = Path(__file__).resolve().parents[3] / "config" / "universe.yml"


@dataclass(frozen=True, slots=True)
class Instrument:
    symbol: str
    name: str
    group: str
    yahoo_symbol: str | None = None
    fred_series: str | None = None
    market: str | None = None
    asset_type: str | None = None
    gics: str | None = None
    sub_industry: str | None = None
    style: str | None = None
    is_proxy: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SpotlightEntry:
    """Curated editorial "house spotlight" overlay — NOT market data.

    A labelled house input (the same category as a regime/policy override) that
    captures the desk's *current focus*: a name drawing fresh attention
    (``heat``) and/or carrying a high-conviction asymmetric-upside thesis
    (``conviction``), each 0-100. It keeps the keyless-only scorers from burying
    a genuinely in-focus turnaround or a still-cheap "next big thing" under names
    that merely have richer keyless fundamentals. ``heat`` floors the HOT ranking;
    ``conviction`` floors the Big-Bet (moonshot) ranking. Never presented as a
    live market signal — the UI shows the ``note`` so the reader sees *why*.
    """

    symbol: str
    heat: float = 0.0
    conviction: float = 0.0
    theme_ko: str = ""
    theme_en: str = ""
    note_ko: str = ""
    note_en: str = ""


@dataclass(frozen=True, slots=True)
class Universe:
    indices: list[Instrument]
    cross_assets: list[Instrument]
    etfs_core: list[Instrument]
    sectors: list[Instrument]
    styles: list[Instrument]
    stocks: list[Instrument]
    covered_call_etfs: list[Instrument]
    benchmarks: dict[str, str]
    spotlight: dict[str, SpotlightEntry] = field(default_factory=dict)
    # Tickers whose keyless price feed is systematically corrupt — still recommended,
    # but their absolute target band is suppressed (see config/universe.yml).
    price_untrusted: frozenset[str] = field(default_factory=frozenset)

    def all_instruments(self) -> list[Instrument]:
        return [
            *self.indices,
            *self.cross_assets,
            *self.etfs_core,
            *self.sectors,
            *self.styles,
            *self.stocks,
            *self.covered_call_etfs,
        ]

    def by_symbol(self, symbol: str) -> Instrument | None:
        for inst in self.all_instruments():
            if inst.symbol == symbol:
                return inst
        return None

    def sub_industry_members(self) -> dict[str, list[str]]:
        """Map each ``sub_industry`` label to the stock symbols carrying it.

        Only stocks classified in ``universe.yml`` appear; unclassified names are
        omitted (they simply get no sub-industry cycle signal). Used to compute a
        keyless, deterministic sub-industry relative-strength (cycle) read so a
        rolling-over group — e.g. memory in a downcycle — drags its members and a
        strengthening one lifts them, independent of each name's trailing data.
        """
        groups: dict[str, list[str]] = {}
        for inst in self.stocks:
            if inst.sub_industry:
                groups.setdefault(inst.sub_industry, []).append(inst.symbol)
        return groups

    def yahoo_symbols(self, instruments: list[Instrument]) -> dict[str, str]:
        return {i.symbol: i.yahoo_symbol for i in instruments if i.yahoo_symbol}


def _mk(d: dict[str, Any], group: str) -> Instrument:
    known = {"symbol", "name", "yahoo_symbol", "fred_series", "market", "asset_type", "gics", "style", "is_proxy"}
    return Instrument(
        symbol=d["symbol"],
        name=d["name"],
        group=d.get("group", group),
        yahoo_symbol=d.get("yahoo_symbol"),
        fred_series=d.get("fred_series"),
        market=d.get("market"),
        asset_type=d.get("asset_type"),
        gics=d.get("gics"),
        style=d.get("style"),
        is_proxy=bool(d.get("is_proxy", False)),
        extra={k: v for k, v in d.items() if k not in known},
    )


def _mk_stock(d: dict[str, Any]) -> Instrument:
    """Stock entries default yahoo_symbol to the ticker; `sector` is the GICS ETF."""
    return Instrument(
        symbol=d["symbol"],
        name=d["name"],
        group="stock",
        yahoo_symbol=d.get("yahoo_symbol", d["symbol"]),
        asset_type="stock",
        gics=d.get("sector"),
        sub_industry=d.get("sub_industry"),
        extra={"benchmark": d.get("benchmark", "SPY"), "sector_etf": d.get("sector")},
    )


def _mk_covered_call(d: dict[str, Any]) -> Instrument:
    return Instrument(
        symbol=d["symbol"],
        name=d["name"],
        group="covered_call",
        yahoo_symbol=d.get("yahoo_symbol", d["symbol"]),
        asset_type="covered_call_etf",
        extra={"benchmark": d.get("underlying", "SPY"), "underlying": d.get("underlying", "SPY")},
    )


def _mk_spotlight(d: dict[str, Any]) -> SpotlightEntry:
    return SpotlightEntry(
        symbol=d["symbol"],
        heat=float(d.get("heat", 0.0)),
        conviction=float(d.get("conviction", 0.0)),
        theme_ko=str(d.get("theme_ko", "")),
        theme_en=str(d.get("theme_en", "")),
        note_ko=str(d.get("note_ko", "")),
        note_en=str(d.get("note_en", "")),
    )


def _validate(u: Universe) -> Universe:
    """Fail fast on a mangled symbol. YAML 1.1 booleans (``on``/``off``/``yes``/
    ``no``) silently parse bare tickers like ``ON`` into ``True`` — quote them in
    the YAML. Catch it here with a clear message instead of a cryptic
    ``'bool' object has no attribute 'encode'`` 200s into a live fetch."""
    for inst in u.all_instruments():
        if not isinstance(inst.symbol, str):
            raise ValueError(
                f"universe symbol {inst.symbol!r} ({inst.name!r}) is {type(inst.symbol).__name__}, "
                "not str — quote it in universe.yml (e.g. a bare ON/OFF/YES/NO is a YAML bool)."
            )
        if inst.yahoo_symbol is not None and not isinstance(inst.yahoo_symbol, str):
            raise ValueError(f"universe yahoo_symbol for {inst.symbol!r} is not a str — quote it in universe.yml.")
    return u


@lru_cache
def get_universe() -> Universe:
    raw = yaml.safe_load(_UNIVERSE_PATH.read_text(encoding="utf-8"))
    return _validate(Universe(
        indices=[_mk(d, "index") for d in raw.get("indices", [])],
        cross_assets=[_mk(d, "cross_asset") for d in raw.get("cross_assets", [])],
        etfs_core=[_mk(d, "etf") for d in raw.get("etfs_core", [])],
        sectors=[_mk(d, "sector") for d in raw.get("sectors", [])],
        styles=[_mk(d, "style") for d in raw.get("styles", [])],
        stocks=[_mk_stock(d) for d in raw.get("stocks", [])],
        covered_call_etfs=[_mk_covered_call(d) for d in raw.get("covered_call_etfs", [])],
        benchmarks=raw.get("benchmarks", {}),
        spotlight={d["symbol"]: _mk_spotlight(d) for d in raw.get("spotlight", [])},
        price_untrusted=frozenset(str(s) for s in raw.get("price_untrusted", [])),
    ))
