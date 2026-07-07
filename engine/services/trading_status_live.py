"""Phase 1c (live-state) — per-symbol runtime state for the /trading-status surface.

Companion to ``services/trading_status.py`` (the config-reconciliation spine).
Where that module answers *"should this symbol trade?"*, this one answers
*"what is it actually doing right now?"*: last signal, last order, open
position, realized P&L.

Pure logic by design: every data source is injected as a callable, so this is
fully unit-testable without a database or a running engine. The router
(``routers/trading_status_router.py``) wires the real **sync** local reads in —
``decisions`` / ``paper_trades`` / ``daily_pnl`` tables and the in-memory
tracker. **No broker round-trips**: nothing here ever touches IB/Schwab, so the
surface stays fast and can't block on a gateway.

The normalizers deliberately project each raw row down to a small, stable,
JSON-friendly subset and use ``.get`` throughout, so an unexpected row shape
degrades to ``None`` fields rather than raising.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional


def _parse_age_seconds(ts_str: Optional[str], now: Optional[datetime]) -> Optional[float]:
    """Age of an ISO-8601 timestamp in seconds vs ``now``. None if either is
    missing or the timestamp can't be parsed — never raises."""
    if not ts_str or now is None:
        return None
    try:
        ts = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return round((now - ts).total_seconds(), 1)


def _normalize_signal(
    row: Optional[dict[str, Any]], now: Optional[datetime]
) -> Optional[dict[str, Any]]:
    """Project a ``decisions`` row to the exposed signal shape, or None."""
    if not row:
        return None
    ts = row.get("timestamp")
    return {
        "action": row.get("action"),
        "confidence": row.get("confidence"),
        "regime": row.get("regime"),
        "timestamp": ts,
        "age_seconds": _parse_age_seconds(ts, now),
    }


def _normalize_order(row: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Project a ``paper_trades`` row to the exposed last-order shape, or None."""
    if not row:
        return None
    return {
        "trade_id": row.get("trade_id"),
        "side": row.get("side"),
        "quantity": row.get("quantity"),
        "entry_price": row.get("entry_price"),
        "exit_price": row.get("exit_price"),
        "status": row.get("status"),
        "entry_time": row.get("entry_time"),
        "exit_time": row.get("exit_time"),
        "pnl": row.get("pnl"),
    }


def _normalize_position(row: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Project an open ``paper_trades`` row to the exposed position shape, or None.

    ``side`` falls back to ``action`` because the open-trade store has historically
    keyed direction under either column depending on the write path."""
    if not row:
        return None
    return {
        "trade_id": row.get("trade_id"),
        "side": row.get("side") or row.get("action"),
        "quantity": row.get("quantity"),
        "entry_price": row.get("entry_price"),
        "entry_time": row.get("entry_time"),
    }


@dataclass
class SymbolLiveState:
    """One symbol's runtime state — the 'what is it doing now' half of the surface."""

    symbol: str
    last_signal: Optional[dict[str, Any]]  # most-recent pipeline decision
    last_order: Optional[dict[str, Any]]  # most-recent paper trade (any status)
    open_position: Optional[dict[str, Any]]  # current open trade, or None
    has_open_position: bool
    realized_pnl: Optional[float]  # sum of closed-trade pnl for this symbol

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_symbol_live_state(
    symbol: str,
    *,
    last_signal_row: Optional[dict[str, Any]],
    last_order_row: Optional[dict[str, Any]],
    open_position_row: Optional[dict[str, Any]],
    realized_pnl: Optional[float],
    now: Optional[datetime] = None,
) -> SymbolLiveState:
    """Assemble one symbol's live state from raw, already-fetched rows."""
    position = _normalize_position(open_position_row)
    return SymbolLiveState(
        symbol=symbol,
        last_signal=_normalize_signal(last_signal_row, now),
        last_order=_normalize_order(last_order_row),
        open_position=position,
        has_open_position=position is not None,
        realized_pnl=realized_pnl,
    )


def build_live_status(
    symbols: list[str],
    *,
    last_signal_for: Callable[[str], Optional[dict[str, Any]]],
    last_order_for: Callable[[str], Optional[dict[str, Any]]],
    open_position_for: Callable[[str], Optional[dict[str, Any]]],
    realized_pnl_for: Callable[[str], Optional[float]],
    now: Optional[datetime] = None,
) -> list[SymbolLiveState]:
    """Build live state for a set of symbols, sorted symbol-asc and de-duplicated.

    All four sources are injected as callables so the engine wiring and the tests
    share one code path. The callables should already be resilient (the router
    wraps each in a try/except → None) since these run on every dashboard poll."""
    out: list[SymbolLiveState] = []
    for sym in sorted(set(symbols)):
        out.append(
            build_symbol_live_state(
                sym,
                last_signal_row=last_signal_for(sym),
                last_order_row=last_order_for(sym),
                open_position_row=open_position_for(sym),
                realized_pnl=realized_pnl_for(sym),
                now=now,
            )
        )
    return out


def summarize_live(states: list[SymbolLiveState]) -> dict[str, Any]:
    """Roll-up counts for the surface header."""
    return {
        "total": len(states),
        "with_open_position": sum(1 for s in states if s.has_open_position),
        "with_signal": sum(1 for s in states if s.last_signal is not None),
        "total_realized_pnl": round(sum(s.realized_pnl or 0.0 for s in states), 2),
    }
