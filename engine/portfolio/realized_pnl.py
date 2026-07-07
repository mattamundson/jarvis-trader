"""
JARVIS TRADER — Realized P&L Utilities
========================================
Computes realized equity and running realized peak from closed trades only,
deliberately excluding unrealized mark-to-market on open positions.

Why this exists
---------------
The safety-layer ``peak_equity`` column (written by SafetyLayer._persist_pnl_snapshot)
tracks MTM equity including unrealized P&L from open positions.  This is the
correct metric for the kill switch (-10% drawdown halt) because an open short
position with a big paper profit that then reverses *is* a real intraday risk.

However, the Phase 3 C5 readiness criterion measures *strategy quality over 60
calendar days*, not intraday exposure management.  Using MTM peak for C5 creates
phantom drawdowns: if an open position is temporarily deep in-the-money and then
the market recovers, equity "drops" relative to the MTM peak even though every
closed trade was profitable.  The 2026-05-11 incident saw a 40.2% phantom
drawdown triggered entirely by this mechanism while realized P&L was +$60,617.

The fix is additive:
  - ``realized_peak_equity`` (new column, migration 029) tracks only closed P&L.
  - C5 uses ``realized_peak_equity``; kill switch continues to use ``peak_equity``.
  - ``safety_layer.py`` is NOT imported or modified here.

Public API
----------
compute_realized_equity(closed_trades, starting_capital) -> float
    Equity from closed trades only.

compute_realized_peak(snapshots) -> float
    Running maximum of realized_equity across a time series.

Both functions are pure (no I/O) so they are trivially testable.
"""

from __future__ import annotations

import logging
from typing import List

logger = logging.getLogger(__name__)


def compute_realized_equity(
    closed_trades: List[dict],
    starting_capital: float,
) -> float:
    """
    Compute equity considering ONLY closed (realized) trades.

    Parameters
    ----------
    closed_trades:
        List of trade dicts.  Each must have a ``pnl`` key (REAL, may be
        None for open/cancelled trades — those are silently skipped).
        Typically rows from ``paper_trades WHERE status = 'closed'``.
    starting_capital:
        Account starting capital (e.g. 10_000.0).  The baseline before
        any trades are considered.

    Returns
    -------
    float
        starting_capital + sum(pnl for all closed trades with a non-None pnl).
    """
    if starting_capital <= 0.0:
        logger.warning(
            "compute_realized_equity: starting_capital=%.2f is non-positive; "
            "result may be misleading",
            starting_capital,
        )

    total_realized = sum(float(t["pnl"]) for t in closed_trades if t.get("pnl") is not None)
    return starting_capital + total_realized


def compute_realized_peak(snapshots: List[dict]) -> float:
    """
    Return the running maximum realized_peak_equity across a time series.

    Parameters
    ----------
    snapshots:
        List of snapshot dicts ordered oldest-first.  Each dict must have a
        ``realized_equity`` key (the value returned by compute_realized_equity
        for that snapshot's timestamp).

    Returns
    -------
    float
        The maximum realized_equity seen so far (monotonically non-decreasing
        when processed in time order).  Returns 0.0 on an empty list.

    Notes
    -----
    Unlike mark-to-market peak_equity (which can swing intraday with open
    positions), realized_peak is monotonically non-decreasing because realized
    P&L only grows as trades close.  It NEVER resets across engine restarts —
    if you need to reset realized_peak (e.g., after an account drawdown reset),
    clear the pnl_snapshots table explicitly.
    """
    if not snapshots:
        return 0.0

    peak = 0.0
    for snap in snapshots:
        eq = float(snap.get("realized_equity") or 0.0)
        if eq > peak:
            peak = eq
    return peak
