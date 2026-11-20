"""Broker-confirmed equity basis for the drawdown kill switch.

Equity = INITIAL_CAPITAL + realized P&L of closed paper_trades rows that the IB
paper broker actually carried (a broker stop child was attached:
``stop_order_id`` set). Rows booked by the in-process simulator, phantom rows,
and cancelled rows are excluded. The peak is the high-water mark of this same
curve (never below INITIAL_CAPITAL), so equity and peak share one basis.

Why: through 2026-10-26 every ledger row was a simulated fill, and the
drawdown peak was read from daily_pnl history built on that simulated balance.
Mixing a broker-confirmed equity with a simulated peak would read a false
-35% drawdown; keeping both simulated means the halt guards money that was
never at the broker. This module changes only the *input*; the -8% / -20%
thresholds and the kill-switch logic in safety_layer.py are untouched.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

BROKER_CONFIRMED_SQL = (
    "SELECT pnl, exit_time FROM paper_trades "
    "WHERE status = 'closed' AND pnl IS NOT NULL "
    "AND stop_order_id IS NOT NULL AND stop_order_id != '' "
    "ORDER BY exit_time ASC, id ASC"
)


@dataclass(frozen=True)
class EquityState:
    equity: float
    peak: float
    daily_pnl: float
    trade_count: int

    @property
    def drawdown_pct(self) -> float:
        """Negative fraction below peak (e.g. -0.08), 0.0 at or above peak."""
        if self.peak <= 0:
            return 0.0
        return min(0.0, (self.equity - self.peak) / self.peak)


def broker_confirmed_equity_state(
    db_path: str, initial_capital: float, today: Optional[str] = None
) -> EquityState:
    """Read the broker-confirmed equity curve. Raises on DB errors so callers
    can fall back explicitly rather than reading a silent zero."""
    today = today or datetime.now(timezone.utc).date().isoformat()
    uri = f"file:{Path(db_path).as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        rows = conn.execute(BROKER_CONFIRMED_SQL).fetchall()

    equity = float(initial_capital)
    peak = equity
    daily = 0.0
    for pnl, exit_time in rows:
        equity += float(pnl)
        peak = max(peak, equity)
        if str(exit_time or "")[:10] == today:
            daily += float(pnl)
    return EquityState(equity=equity, peak=peak, daily_pnl=daily, trade_count=len(rows))
