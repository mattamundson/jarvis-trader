"""
JARVIS TRADER — Actionable-Now derivation (pure).

Maps stored pipeline decisions (pending_trade_approvals rows, which carry the
Trader stage's entry/stop/target geometry in their snapshot) plus the latest
price to a live "what do I do now" board item: a status chip, distance to
entry in % and ATR, planned reward:risk, and the current R-multiple.

Ported from amo-arbitrage's `routers/actionable.py::derive_actionable` (WS4.1),
adapted to jarvis's approval-queue data model. Design rules kept intact:

- PURE — no I/O, no clock reads (``now`` is a parameter) — exhaustively testable.
- Derives from the LATEST price only; no new strategy logic, no new signals.
- Honest degradation: a missing price yields status "unknown"; missing levels
  yield null distances/R rather than fabricated values.
- Display-only. This module never routes, sizes, gates, or vetoes anything —
  approval and execution stay in the existing human-gated flow.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Optional

from data.provenance import LIVE_SOURCES
from utils.position_sizing import get_contract_multiplier

# A pending decision older than this many calendar days is stale — the pipeline
# emits fresh decisions intraday, so an old row is history, not an opportunity.
EXPIRY_DAYS = 3

# Half-width of the "at the entry level now" band, in ATR units. Within this of
# entry => triggerable; past it toward target => triggered; short of it => awaiting.
ENTRY_ZONE_ATR_FRAC = 0.25

# A snapshot price older than this cannot honestly anchor a "triggerable NOW"
# claim on a 60s-refresh board. Stale prices are still displayed (with a flag)
# but the status degrades to "unknown" rather than presenting a cached close
# as a live tick.
STALE_PRICE_MAX_S = 900.0

# Source tiers whose last_price is a market-current read at fetch time (live
# feeds plus delayed-but-fresh REST reads). Cache/static/error tiers
# (csv_cache, sqlite_cache, polygon_cache*, the "data_manager" default,
# *_unavailable/_error) are EXCLUDED: /prices/snapshot stamps as_of at FETCH
# time, so a cached close can carry a fresh timestamp over a days-old price —
# tier membership, not timestamp age, is the trustworthy discriminator.
DELAYED_OK_SOURCES = frozenset(
    {"ibkr_delayed", "ibkr_historical", "polygon", "polygon_rest"}
)
STATUS_GRADE_SOURCES = frozenset(LIVE_SOURCES) | DELAYED_OK_SOURCES

# Chip vocabulary, priority order (highest wins) — mirrors amo-arbitrage.
STATUSES = (
    "unknown",
    "invalidated",
    "target_reached",
    "expired",
    "triggered",
    "triggerable",
    "awaiting_entry",
)


def _f(value: Any) -> Optional[float]:
    """Best-effort float; None on missing/garbage."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pos(value: Any) -> Optional[float]:
    """Positive float or None. Price levels stored as 0.0 are a missing-value
    sentinel; treating them as real levels would grade e.g. a long with
    target_1=0.0 as target_reached against any positive price."""
    f = _f(value)
    return f if f is not None and f > 0 else None


def _parse_created_at(raw: Any) -> Optional[date]:
    """Parse the row's created_at into a date (None on garbage)."""
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
        except ValueError:
            return None
    return None


def derive_status(
    *,
    latest_close: Optional[float],
    entry: Optional[float],
    stop: Optional[float],
    target: Optional[float],
    atr: Optional[float],
    long: bool,
    age_days: Optional[int],
) -> str:
    """Pure status chip. Priority: unknown > invalidated > target_reached >
    expired > triggered > triggerable > awaiting_entry."""
    if latest_close is None:
        return "unknown"
    if entry is None:
        return "unknown"
    sign = 1.0 if long else -1.0
    if stop is not None and (latest_close - stop) * sign <= 0:
        return "invalidated"
    if target is not None and (target - latest_close) * sign <= 0:
        return "target_reached"
    if age_days is not None and age_days > EXPIRY_DAYS:
        return "expired"
    # Favorable-signed remaining distance to entry: positive = price still has
    # to travel to reach entry; negative = price is past entry, toward target.
    remaining = (entry - latest_close) * sign
    if atr and atr > 0 and abs(remaining) <= ENTRY_ZONE_ATR_FRAC * atr:
        return "triggerable"
    if remaining < 0:
        return "triggered"
    return "awaiting_entry"


def derive_actionable_item(
    row: dict,
    latest_close: Optional[float],
    price_as_of: Optional[float],
    *,
    now: date,
    price_is_live: Optional[bool] = None,
    price_stale: bool = False,
) -> dict:
    """Map one pending_trade_approvals row + latest price to a board item.

    ``row`` is the dict shape returned by the DB mixin (with parsed
    ``pipeline_snapshot``). Missing geometry degrades to nulls — never invented.
    A stale price (``price_stale``) is kept for display but excluded from all
    status/distance/R derivation, so the item honestly reads "unknown".
    """
    # Status and math must never run off a stale price; display keeps it.
    usable_close = None if price_stale else latest_close
    snap = row.get("pipeline_snapshot") or {}
    td = snap.get("trade_decision") or {}
    if not isinstance(td, dict):
        td = {}

    symbol = (row.get("symbol") or "").upper()
    action = (row.get("action") or "").lower()
    long = action != "sell"
    sign = 1.0 if long else -1.0

    entry = (
        _pos(td.get("entry_price"))
        or _pos(td.get("limit_price"))
        or _pos(row.get("entry_price"))
    )
    stop = _pos(td.get("stop_price"))
    target = _pos(td.get("target_1"))
    atr = _pos(td.get("atr_used"))

    age_days: Optional[int] = None
    created = _parse_created_at(row.get("created_at"))
    if created is not None:
        age_days = (now - created).days

    distance_abs = distance_pct = distance_atr = None
    if usable_close is not None and entry is not None and usable_close != 0:
        distance_abs = round((entry - usable_close) * sign, 6)
        distance_pct = round(distance_abs / usable_close * 100, 4)
        if atr and atr > 0:
            distance_atr = round(distance_abs / atr, 4)

    risk_per_unit = planned_rr = current_r = None
    if entry is not None and stop is not None:
        risk_per_unit = abs(entry - stop)
        if risk_per_unit > 0:
            if target is not None:
                planned_rr = round(abs(target - entry) / risk_per_unit, 2)
            if usable_close is not None:
                current_r = round((usable_close - entry) * sign / risk_per_unit, 3)

    notional_per_contract = None
    if usable_close is not None:
        notional_per_contract = round(usable_close * get_contract_multiplier(symbol), 2)

    status = derive_status(
        latest_close=usable_close, entry=entry, stop=stop, target=target,
        atr=atr, long=long, age_days=age_days,
    )

    return {
        "approval_id": row.get("approval_id"),
        "symbol": symbol,
        "direction": "long" if long else "short",
        "action": action,
        "approval_status": row.get("status"),
        "quantity": _f(row.get("quantity")),
        "confidence": _f(td.get("confidence")),
        "timeframe": row.get("timeframe"),
        "created_at": row.get("created_at"),
        "age_days": age_days,
        "status": status,
        "entry_price": entry,
        "stop_loss": stop,
        "target_1": target,
        "atr": atr,
        "latest_price": latest_close,
        "price_as_of": price_as_of,
        "price_is_live": price_is_live,
        "price_stale": price_stale,
        "distance_abs": distance_abs,
        "distance_pct": distance_pct,
        "distance_atr": distance_atr,
        "planned_rr": planned_rr,
        "current_r": current_r,
        "notional_per_contract": notional_per_contract,
    }


def derive_actionable_board(
    rows: list[dict],
    prices: dict[str, dict],
    *,
    now: Optional[date] = None,
    now_ts: Optional[float] = None,
) -> dict:
    """Derive the full board from recent approval rows + a price snapshot.

    Only directional (buy/sell), unresolved-or-recently-resolved rows appear;
    one item per (symbol, direction) — the newest — so re-scans don't stack
    duplicates. ``prices`` is the /prices/snapshot shape keyed by symbol; a
    price whose ``as_of`` is older than STALE_PRICE_MAX_S (vs ``now_ts``,
    epoch seconds) is treated as stale — displayed but never used to derive a
    status. Missing ``as_of``/``now_ts`` counts as stale (conservative).
    """
    if now is None:
        now = datetime.now(tz=timezone.utc).date()
    if now_ts is None:
        now_ts = datetime.now(tz=timezone.utc).timestamp()

    items: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        action = (row.get("action") or "").lower()
        if action not in ("buy", "sell"):
            continue
        # Rejected/errored decisions are history, not opportunities.
        if (row.get("status") or "").lower() in ("rejected", "error"):
            continue
        symbol = (row.get("symbol") or "").upper()
        key = (symbol, action)
        if key in seen:
            continue  # rows arrive newest-first; keep only the latest per side
        seen.add(key)

        p = prices.get(symbol) or {}
        last_price = _f(p.get("last_price"))
        as_of = _f(p.get("as_of"))
        source = (p.get("source") or "").lower()
        stale = last_price is not None and (
            source not in STATUS_GRADE_SOURCES
            or as_of is None
            or (now_ts - as_of) > STALE_PRICE_MAX_S
        )
        items.append(
            derive_actionable_item(
                row,
                last_price,
                as_of,
                now=now,
                price_is_live=bool(p.get("is_live")) if last_price is not None else None,
                price_stale=stale,
            )
        )

    # Actionable first: triggerable/triggered ahead of awaiting, dead last.
    order = {s: i for i, s in enumerate(
        ("triggerable", "triggered", "awaiting_entry", "target_reached",
         "invalidated", "expired", "unknown")
    )}
    items.sort(key=lambda it: (order.get(it["status"], 99), -(it.get("confidence") or 0.0)))
    return {"items": items, "count": len(items), "available": True}
