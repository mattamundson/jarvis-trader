"""
Paper Trade Pairing — Shared FIFO round-trip matcher.

This is the single source of truth for pairing buy/sell entries from
paper_trades.json into closed round-trips with correct dollar PnL.

Background (bug history)
------------------------
The writer (execution/paper_trade_logger.py) stamps ``pnl`` on each sell
entry, but the computation is:

    pnl = quantity * (filled_price - entry_price)   # MISSING multiplier

So stored ``pnl`` is in price-point units, not dollars.  The readers were
trusting the stored value and short-circuiting the multiplier step, which
caused every "win" to appear as ~$0 (sub-dollar price diffs) and the G2
win-rate gauge to read 0.0% regardless of real performance.

Fix: this module ALWAYS ignores ``stored_pnl`` and recomputes from
entry/exit prices × contract multiplier.  The on-disk format is unchanged.

Usage
-----
    from analytics.paper_trade_pairing import pair_trades, ClosedRoundTrip

    raw_trades: list[dict] = [...]   # from paper_trades.json "trades" list
    closed: list[ClosedRoundTrip] = pair_trades(raw_trades)

    wins   = sum(1 for t in closed if t.is_win)
    total  = len(closed)
    pnl    = sum(t.pnl for t in closed)

Notes
-----
- FIFO per symbol: buys stack up, each sell pops the oldest matching buy.
- Short positions (sell-first): ``side="sell"`` opener stacked; buy pops it;
  PnL = (entry_price - exit_price) × qty × mult.
- Unclosed positions (open at end of window) are NOT included in closed list.
- Contract multipliers: MES=5, MGC=10, MNQ=2, MCL=100, M2K=5, MGC=10.
  Override via the ``multipliers`` parameter if new contracts are added.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

# ---------------------------------------------------------------------------
# Contract multipliers (dollar value per 1-point move, 1 contract)
# ---------------------------------------------------------------------------

DEFAULT_MULTIPLIERS: dict[str, float] = {
    "MES": 5.0,
    "MGC": 10.0,
    "MNQ": 2.0,
    "MCL": 100.0,
    "M2K": 5.0,
}


# ---------------------------------------------------------------------------
# Data structure
# ---------------------------------------------------------------------------


@dataclass
class ClosedRoundTrip:
    """One completed buy→sell (long) or sell→buy (short) round-trip."""

    symbol: str
    side: str  # "buy" = entered long, "sell" = entered short
    quantity: float
    entry_price: float
    exit_price: float
    entry_time: datetime
    exit_time: datetime
    pnl: float  # dollar PnL (multiplier applied, no commission)
    slippage_ticks_entry: int = 0
    slippage_ticks_exit: int = 0

    @property
    def hold_minutes(self) -> float:
        return (self.exit_time - self.entry_time).total_seconds() / 60

    @property
    def is_win(self) -> bool:
        return self.pnl > 0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_ts(ts_str: str) -> Optional[datetime]:
    if not ts_str:
        return None
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def pair_trades(
    raw_trades: list[dict],
    *,
    multipliers: dict[str, float] | None = None,
) -> list[ClosedRoundTrip]:
    """
    Match buy/sell entries from paper_trades.json into closed round-trips.

    Parameters
    ----------
    raw_trades:
        List of trade dicts as they appear in ``paper_trades.json["trades"]``.
        Must have: symbol, side, filled_price (or trade_value), quantity,
        timestamp.  The ``pnl`` field is INTENTIONALLY IGNORED — it is
        recomputed from entry/exit prices to avoid the writer bug.

    multipliers:
        Override contract multipliers (default: DEFAULT_MULTIPLIERS).
        Keys are symbol strings (e.g. ``"MES"``).

    Returns
    -------
    list[ClosedRoundTrip]
        Only completed pairs.  Open positions (no matching exit within
        ``raw_trades``) are discarded.
    """
    from collections import defaultdict

    mults = DEFAULT_MULTIPLIERS if multipliers is None else {**DEFAULT_MULTIPLIERS, **multipliers}

    # Sort by timestamp ascending for deterministic FIFO ordering
    sorted_trades = sorted(raw_trades, key=lambda x: x.get("timestamp", ""))

    # Per-symbol stacks of open (unmatched) sides
    long_stack: dict[str, list[dict]] = defaultdict(list)  # awaiting sell-to-close
    short_stack: dict[str, list[dict]] = defaultdict(list)  # awaiting buy-to-cover

    closed: list[ClosedRoundTrip] = []

    for t in sorted_trades:
        sym = (t.get("symbol") or "").upper()
        side = (t.get("side") or "").lower()
        qty = float(t.get("quantity") or t.get("quantity") or 1.0)
        price = float(t.get("filled_price") or t.get("trade_value") or 0.0)
        ts = _parse_ts(t.get("timestamp", ""))
        slip = int(t.get("slippage_ticks") or 0)
        mult = mults.get(sym, 1.0)

        if side in ("buy", "buy_to_open"):
            # Could be entering long OR covering a short
            if short_stack[sym]:
                # Cover oldest short(s) — consume as many openers as needed for qty
                remaining_exit = qty
                while remaining_exit > 0 and short_stack[sym]:
                    opener = short_stack[sym][0]
                    opener_qty = float(opener.get("quantity") or opener.get("quantity") or 1.0)
                    entry_p = float(opener.get("filled_price") or opener.get("trade_value") or 0.0)
                    entry_ts = _parse_ts(opener.get("timestamp", ""))
                    entry_slip = int(opener.get("slippage_ticks") or 0)
                    if entry_ts is None or ts is None:
                        short_stack[sym].pop(0)
                        break
                    fill_qty = min(remaining_exit, opener_qty)
                    # Short PnL: entry (sell) price - exit (buy) price
                    pnl = (entry_p - price) * fill_qty * mult
                    closed.append(
                        ClosedRoundTrip(
                            symbol=sym,
                            side="sell",
                            quantity=fill_qty,
                            entry_price=entry_p,
                            exit_price=price,
                            entry_time=entry_ts,
                            exit_time=ts,
                            pnl=pnl,
                            slippage_ticks_entry=entry_slip,
                            slippage_ticks_exit=slip,
                        )
                    )
                    remaining_exit -= fill_qty
                    if fill_qty < opener_qty:
                        # Partial fill — push back residual opener with reduced qty
                        residual = dict(opener)
                        residual["quantity"] = opener_qty - fill_qty
                        short_stack[sym][0] = residual
                    else:
                        short_stack[sym].pop(0)
                if remaining_exit > 0:
                    # Any excess exit qty opens a new long
                    residual_t = dict(t)
                    residual_t["quantity"] = remaining_exit
                    long_stack[sym].append(residual_t)
            else:
                # Open a new long
                long_stack[sym].append(t)

        elif side in ("sell", "sell_to_close", "exit_long"):
            # Could be closing a long OR opening a short
            if long_stack[sym]:
                # Close oldest long(s) — consume as many openers as needed for qty
                remaining_exit = qty
                while remaining_exit > 0 and long_stack[sym]:
                    opener = long_stack[sym][0]
                    opener_qty = float(opener.get("quantity") or opener.get("quantity") or 1.0)
                    entry_p = float(opener.get("filled_price") or opener.get("trade_value") or 0.0)
                    entry_ts = _parse_ts(opener.get("timestamp", ""))
                    entry_slip = int(opener.get("slippage_ticks") or 0)
                    if entry_ts is None or ts is None:
                        long_stack[sym].pop(0)
                        break
                    fill_qty = min(remaining_exit, opener_qty)
                    # Long PnL: exit (sell) price - entry (buy) price
                    pnl = (price - entry_p) * fill_qty * mult
                    closed.append(
                        ClosedRoundTrip(
                            symbol=sym,
                            side="buy",
                            quantity=fill_qty,
                            entry_price=entry_p,
                            exit_price=price,
                            entry_time=entry_ts,
                            exit_time=ts,
                            pnl=pnl,
                            slippage_ticks_entry=entry_slip,
                            slippage_ticks_exit=slip,
                        )
                    )
                    remaining_exit -= fill_qty
                    if fill_qty < opener_qty:
                        # Partial fill — push back residual opener with reduced qty
                        residual = dict(opener)
                        residual["quantity"] = opener_qty - fill_qty
                        long_stack[sym][0] = residual
                    else:
                        long_stack[sym].pop(0)
                if remaining_exit > 0:
                    # Any excess exit qty opens a new short
                    residual_t = dict(t)
                    residual_t["quantity"] = remaining_exit
                    short_stack[sym].append(residual_t)
            else:
                # Open a new short
                short_stack[sym].append(t)

    return closed


def compute_metrics(closed: list[ClosedRoundTrip]) -> dict:
    """
    Return a flat metrics dict from a list of closed round-trips.

    Keys: total_trades, wins, losses, win_rate (0-1), total_pnl,
    avg_trade_pnl, biggest_win, biggest_loss, avg_hold_minutes.
    """
    if not closed:
        return {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": None,
            "total_pnl": 0.0,
            "avg_trade_pnl": None,
            "biggest_win": None,
            "biggest_loss": None,
            "avg_hold_minutes": None,
        }

    pnls = [t.pnl for t in closed]
    wins = [t for t in closed if t.is_win]
    losses = [t for t in closed if not t.is_win]
    total_pnl = sum(pnls)
    n = len(closed)

    return {
        "total_trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / n,
        "total_pnl": total_pnl,
        "avg_trade_pnl": total_pnl / n,
        "biggest_win": max(pnls) if wins else None,
        "biggest_loss": min(pnls) if losses else None,
        "avg_hold_minutes": sum(t.hold_minutes for t in closed) / n,
    }
