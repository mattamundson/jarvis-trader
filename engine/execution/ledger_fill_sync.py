"""Broker fill sync for the paper_trades ledger.

Rows booked through the real IB paper broker are written at submit time with
the *quoted* entry price, and were later closed by the 5-minute price monitor
at the *theoretical* stop level. Neither is what IB filled. This module matches
IB executions back to bracketed ledger rows (entry order id from
strategy_params, stop/target child ids from the row) and overwrites the
ledger with the actual fills:

- entry_price      <- VWAP of the entry order's executions
- slippage_ticks   <- adverse ticks vs the quoted entry (positive = worse)
- exit_price/time  <- VWAP / last fill of the stop or target child
- pnl              <- gross from fills minus the commissions IB reported

The quoted entry is preserved in strategy_params.quoted_entry_price and the
broker account in strategy_params.broker_account. ``account_id`` is left
alone: it is the logical 'A'/'B' key the per-account kill switch reads.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from typing import Callable, Iterable, Optional

logger = logging.getLogger(__name__)

_QTY_EPSILON = 1e-9


@dataclass
class FillMatch:
    entry_fill_price: Optional[float] = None
    entry_filled_qty: float = 0.0
    entry_commission: Optional[float] = None
    slippage_ticks: Optional[float] = None
    broker_account: Optional[str] = None
    exit_price: Optional[float] = None
    exit_time: Optional[str] = None
    exit_filled_qty: float = 0.0
    pnl: Optional[float] = None
    closed: bool = False


def is_broker_managed(trade: dict) -> bool:
    """True when IB holds a live stop child for this row, so IB -- not a
    price-poll monitor -- owns the exit and the fill sync books it."""
    return bool(trade.get("stop_order_id"))


def _params(trade: dict) -> dict:
    raw = trade.get("strategy_params")
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}


def _aggregate(execs: list[dict]) -> tuple[float, float, Optional[float], str]:
    """Return (vwap, qty, commission_sum_or_None, last_fill_time)."""
    qty = sum(float(e.get("quantity") or 0.0) for e in execs)
    notional = sum(float(e.get("quantity") or 0.0) * float(e["price"]) for e in execs)
    commissions = [e.get("commission") for e in execs]
    commission = None if any(c is None for c in commissions) else sum(map(float, commissions))
    last_time = max(str(e.get("fill_time") or "") for e in execs)
    return notional / qty, qty, commission, last_time


def _unique(executions: Iterable[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for e in executions:
        seen[str(e.get("exec_id"))] = e
    return list(seen.values())


def match_fills(
    trade: dict, executions: Iterable[dict], multiplier: float, tick_size: float
) -> FillMatch:
    """Match IB executions to one ledger row. Pure; no I/O."""
    m = FillMatch()
    entry_oid = _params(trade).get("entry_order_id")
    if not entry_oid:
        return m
    execs = _unique(executions)
    entry = [e for e in execs if str(e.get("order_id")) == str(entry_oid)]
    if not entry:
        return m

    is_long = "buy" in str(trade.get("side") or "").lower()
    quoted = _params(trade).get("quoted_entry_price", trade.get("entry_price"))
    m.entry_fill_price, m.entry_filled_qty, m.entry_commission, _ = _aggregate(entry)
    m.broker_account = entry[0].get("account")
    if quoted is not None and tick_size > 0:
        diff = m.entry_fill_price - float(quoted)
        m.slippage_ticks = round((diff if is_long else -diff) / tick_size, 4)

    child_ids = {str(trade.get(k)) for k in ("stop_order_id", "target_order_id") if trade.get(k)}
    exits = [e for e in execs if str(e.get("order_id")) in child_ids]
    if not exits:
        return m
    m.exit_price, m.exit_filled_qty, exit_commission, m.exit_time = _aggregate(exits)
    if m.exit_filled_qty + _QTY_EPSILON < m.entry_filled_qty:
        return m

    m.closed = True
    move = m.exit_price - m.entry_fill_price
    gross = (move if is_long else -move) * m.entry_filled_qty * multiplier
    if m.entry_commission is not None and exit_commission is not None:
        m.pnl = round(gross - m.entry_commission - exit_commission, 2)
    return m


def _apply_entry(conn: sqlite3.Connection, row: dict, m: FillMatch) -> bool:
    params = _params(row)
    if params.get("entry_fill_synced"):
        return False
    params.setdefault("quoted_entry_price", row.get("entry_price"))
    params["broker_account"] = m.broker_account
    params["entry_fill_synced"] = True
    conn.execute(
        "UPDATE paper_trades SET entry_price = ?, slippage_ticks = ?, strategy_params = ? "
        "WHERE trade_id = ?",
        (m.entry_fill_price, m.slippage_ticks, json.dumps(params), row["trade_id"]),
    )
    return True


def _apply_close(conn: sqlite3.Connection, row: dict, m: FillMatch) -> bool:
    if row.get("status") != "open":
        return False
    cur = conn.execute(
        "UPDATE paper_trades SET exit_price = ?, exit_time = ?, pnl = ?, status = 'closed' "
        "WHERE trade_id = ? AND status = 'open'",
        (m.exit_price, m.exit_time, m.pnl, row["trade_id"]),
    )
    return cur.rowcount == 1


def sync_ledger_from_executions(
    db_path: str,
    executions: Iterable[dict],
    multiplier_for: Callable[[str], float],
    tick_size_for: Callable[[str], float],
) -> dict:
    """Write IB fills onto bracketed, broker-routed ledger rows.

    Idempotent: an entry is synced once (strategy_params.entry_fill_synced) and
    a close only transitions an 'open' row. Returns counts plus the trade ids
    whose bracket shows a partial exit while the ledger is still open.
    """
    execs = list(executions)
    result = {"entries_synced": 0, "closes_synced": 0, "partial_exits": []}
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM paper_trades WHERE stop_order_id IS NOT NULL "
                "AND status IN ('open', 'closed')"
            )
        ]
        for row in rows:
            sym = str(row.get("symbol") or "").upper()
            try:
                m = match_fills(row, execs, multiplier_for(sym), tick_size_for(sym))
            except Exception as exc:  # noqa: BLE001 - one bad row must not block the rest
                logger.error("[fill_sync] cannot price %s row %s: %s", sym, row["trade_id"], exc)
                continue
            if m.entry_fill_price is None:
                continue
            if _apply_entry(conn, row, m):
                result["entries_synced"] += 1
            if m.closed and _apply_close(conn, row, m):
                result["closes_synced"] += 1
            elif m.exit_filled_qty > 0 and not m.closed and row.get("status") == "open":
                result["partial_exits"].append(row["trade_id"])
        conn.commit()
    return result


def _default_multiplier(symbol: str) -> float:
    from portfolio.tracker import _resolve_multiplier

    return float(_resolve_multiplier(symbol))


def _default_tick_size(symbol: str) -> float:
    from backtest.backtester import TICK_SIZES

    return float(TICK_SIZES.get(symbol, 0.0))


async def run_fill_sync_once(gateway, db_path: str) -> Optional[dict]:
    """Scheduler entry point. Acts only on the real IB gateway: the in-process
    simulator has no get_executions() and books its own fills. Returns None
    when skipped, otherwise the sync counts."""
    get_executions = getattr(gateway, "get_executions", None)
    if gateway is None or not callable(get_executions) or not gateway.is_connected():
        return None
    executions = await get_executions()
    result = sync_ledger_from_executions(
        db_path, executions, _default_multiplier, _default_tick_size
    )
    if result["entries_synced"] or result["closes_synced"]:
        logger.info(
            "[fill_sync] entries=%d closes=%d synced from IB executions",
            result["entries_synced"],
            result["closes_synced"],
        )
    if result["partial_exits"]:
        logger.warning(
            "[fill_sync] LEDGER/BROKER MISMATCH: partial bracket exit at IB but ledger "
            "row still open for trade_ids=%s",
            result["partial_exits"],
        )
    return result
