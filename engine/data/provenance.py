"""
JARVIS TRADER — Data-Provenance Envelope (Phase 1)
===================================================
Canonical, server-side shape for "a value that carries where it came from and
how fresh it is". Every price/quote value the engine hands to a consumer can be
wrapped as a ``DataEnvelope`` so a number can never be shown without its source
and staleness.

`is_live` is DERIVED — from the serving tier + freshness + the IBKR data-leg
connection — and is NEVER hardcoded ``True``. A cached/delayed source (csv_cache,
Polygon REST) is never live; a live-tier value with a known-stale timestamp is
downgraded; an IBKR value whose data leg is disconnected is downgraded.

Pure module: no engine imports, no I/O. Trivially unit-testable with a fixed
``now`` so freshness gating is deterministic.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any, Optional

# Real-time / streaming tiers. A value from any of these CAN be live (subject to
# the freshness gate below). Mirrors the `source` strings emitted by
# MarketDataManager.get_current_price / get_tick_price waterfalls.
#
# `rtd_tos` is the thinkorswim desktop RTD feed (see data/tos_rtd_adapter.py) —
# a broker-direct push feed, so it belongs with the live tiers. It still has to
# clear the freshness gate: RTD is change-driven, so an unchanged cached value
# carries an `as_of` and is downgraded once it ages out.
SOURCE_TOS_RTD = "rtd_tos"
LIVE_SOURCES = frozenset(
    {"ibkr", "schwab", "tradingview", "polygon_stream", "redis_fabric", SOURCE_TOS_RTD}
)

# Explicitly cached / delayed / absent tiers — never "live" regardless of age.
STATIC_SOURCES = frozenset({"csv_cache", "polygon", "polygon_rest", "unavailable"})

# Default freshness window (seconds). A live-tier value older than this is stale.
DEFAULT_STALE_AFTER_S = 60.0


@dataclass(frozen=True)
class DataEnvelope:
    """A value plus its provenance and freshness.

    Fields:
        value: the underlying number (or None when genuinely unavailable).
        source: which data tier served it (e.g. "ibkr", "csv_cache").
        as_of: epoch seconds when the value was observed (None if unknown).
        is_live: derived — True only for a fresh, connected, live-tier value.
        stale_after_s: freshness window used to derive ``is_live``.
    """

    value: Any
    source: str
    as_of: Optional[float]
    is_live: bool
    stale_after_s: float

    def to_dict(self) -> dict:
        return asdict(self)


def derive_is_live(
    source: Optional[str],
    as_of: Optional[float],
    stale_after_s: float = DEFAULT_STALE_AFTER_S,
    *,
    ibkr_data_connected: Optional[bool] = None,
    now: Optional[float] = None,
) -> bool:
    """Derive liveness from source + freshness + IBKR connection.

    Never hardcodes True. Rules (any failing rule -> not live):
      1. source must be a real-time tier (in LIVE_SOURCES).
      2. an IBKR-served value is only live when its data leg is connected.
      3. if the observation time is known, it must be within ``stale_after_s``.
    A live-tier value with an UNKNOWN ``as_of`` cannot be disproven stale, so it
    stays live (in practice the manager always supplies a timestamp).
    """
    if not source:
        return False
    src = source.lower()
    if src not in LIVE_SOURCES:
        return False
    if src == "ibkr" and ibkr_data_connected is False:
        return False
    if as_of is not None:
        current = time.time() if now is None else now
        if (current - as_of) > stale_after_s:
            return False
    return True


def build_envelope(
    value: Any,
    source: Optional[str],
    as_of: Optional[float] = None,
    stale_after_s: float = DEFAULT_STALE_AFTER_S,
    *,
    ibkr_data_connected: Optional[bool] = None,
    now: Optional[float] = None,
) -> DataEnvelope:
    """Build a DataEnvelope, deriving ``is_live`` honestly.

    A ``None`` value is never live (nothing to be live about).
    """
    normalized_source = source or "unavailable"
    is_live = derive_is_live(
        normalized_source,
        as_of,
        stale_after_s,
        ibkr_data_connected=ibkr_data_connected,
        now=now,
    )
    if value is None:
        is_live = False
    return DataEnvelope(
        value=value,
        source=normalized_source,
        as_of=as_of,
        is_live=is_live,
        stale_after_s=stale_after_s,
    )
