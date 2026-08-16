"""DOM / order-flow imbalance signal — pure computation, no I/O.

The one piece of this Phase-1 service that is actually a *signal*; everything
else (IBKR depth subscription, SQLite persistence, FastAPI endpoints) is
plumbing. Kept as a pure function so it can be unit-tested with known book
inputs and reused by Phase 2 without dragging in IBKR or storage.

Per the Phase-1 spec: imbalance_ratio = bid_volume / (bid_volume + ask_volume)
over the top-N book levels (N=5 by default, configurable).
"""

from __future__ import annotations

from typing import Any, Mapping, Optional


def compute_imbalance(
    bid_levels: list[Any],
    ask_levels: list[Any],
    top_n: int = 5,
) -> float:
    """Compute bid-volume / (bid-volume + ask-volume) over the top-N levels.

    Parameters
    ----------
    bid_levels, ask_levels
        Iterables of book levels, each exposing ``size`` (a positive number).
        In practice these are ib_async ``DOMLevel`` NamedTuples
        (price, size, marketMaker); duck-typed so the pure function has zero
        dependency on ib_async.
    top_n
        Number of best levels to sum per side (default 5 per spec).

    Returns
    -------
    float
        Imbalance ratio in [0, 1]. Convention:
        - > 0.6  → bullish (bid pressure)
        - < 0.4  → bearish (ask pressure)
        - 0.5    → balanced
        - 0.0    → empty book (no bid volume), no division-by-zero
    """
    bid_vol = _sum_top_sizes(bid_levels, top_n)
    ask_vol = _sum_top_sizes(ask_levels, top_n)
    total = bid_vol + ask_vol
    if total <= 0:
        return 0.0
    return bid_vol / total


def _sum_top_sizes(levels: list[Any], top_n: int) -> float:
    """Sum ``size`` of the first ``top_n`` levels, safely.

    A level's size must be coercible to float and >= 0; malformed entries are
    skipped rather than crashing the whole snapshot (a single bad tick must
    never take down the read-only service).
    """
    total = 0.0
    for level in list(levels)[:top_n]:
        try:
            size = float(level.size)
        except (AttributeError, TypeError, ValueError):
            continue
        if size > 0:
            total += size
    return total


def imbalance_label(ratio: float, bull_threshold: float = 0.6, bear_threshold: float = 0.4) -> str:
    """Map an imbalance ratio to a coarse label for the dashboard badge.

    Mirrors the spec's dashboard convention: bull > 0.6, bear < 0.4,
    neutral in between. Thresholds are parameters so tests can pin them.
    """
    if ratio > bull_threshold:
        return "bull"
    if ratio < bear_threshold:
        return "bear"
    return "neutral"


def snapshot_payload(
    symbol: str,
    bid_levels: list[Any],
    ask_levels: list[Any],
    top_n: int = 5,
    extra: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Build the normalized snapshot dict stored every 10s and served by the API.

    Kept here (not in storage.py) so the exact payload contract is testable
    and shared between the storage layer and the /latest endpoint.
    """
    payload: dict[str, Any] = {
        "symbol": symbol,
        "imbalance_ratio": compute_imbalance(bid_levels, ask_levels, top_n),
        "label": imbalance_label(compute_imbalance(bid_levels, ask_levels, top_n)),
    }
    if extra:
        payload.update(extra)
    return payload
