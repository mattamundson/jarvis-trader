"""
JARVIS TRADER — Analytics Mixin
=================================
DatabaseManager mixin providing analytics and statistics query methods.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger("jarvis_trader.database")


class AnalyticsMixin:
    """Analytics and summary query methods."""

    def get_stats_summary(self) -> Dict[str, Any]:
        """
        Return high-level trading statistics.

        Queries ``paper_trades`` for trade counts / P&L totals and
        ``daily_pnl`` for best/worst day and active-day count.

        Returns
        -------
        dict with keys:
            total_trades      -- int, all closed trades
            winning_trades    -- int, closed trades where pnl > 0
            losing_trades     -- int, closed trades where pnl < 0
            total_pnl         -- float, sum of pnl for all closed trades
            best_day          -- float, highest single-day realized_pnl
            worst_day         -- float, lowest single-day realized_pnl
            active_days       -- int, number of rows in daily_pnl
        """
        sql_trades = """
            SELECT
                COUNT(*)                              AS total_trades,
                SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS winning_trades,
                SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) AS losing_trades,
                COALESCE(SUM(pnl), 0.0)              AS total_pnl
            FROM paper_trades
            WHERE status = 'closed'
        """
        sql_daily = """
            SELECT
                COALESCE(MAX(realized_pnl), 0.0) AS best_day,
                COALESCE(MIN(realized_pnl), 0.0) AS worst_day,
                COUNT(*)                          AS active_days
            FROM daily_pnl
        """
        with self._lock:
            conn = self._connect()
            try:
                tr = conn.execute(sql_trades).fetchone()
                dp = conn.execute(sql_daily).fetchone()
            finally:
                conn.close()

        return {
            "total_trades": int(tr["total_trades"]) if tr else 0,
            "winning_trades": int(tr["winning_trades"]) if tr and tr["winning_trades"] else 0,
            "losing_trades": int(tr["losing_trades"]) if tr and tr["losing_trades"] else 0,
            "total_pnl": float(tr["total_pnl"]) if tr else 0.0,
            "best_day": float(dp["best_day"]) if dp else 0.0,
            "worst_day": float(dp["worst_day"]) if dp else 0.0,
            "active_days": int(dp["active_days"]) if dp else 0,
        }

    def get_drawdown(self) -> Dict[str, Any]:
        """
        Compute drawdown metrics from ``daily_pnl`` snapshots.

        Algorithm:
            * Walk ``ending_balance`` rows in chronological order.
            * Track the running peak balance.
            * Current drawdown = peak - latest ending_balance.
            * Max historical drawdown = largest (peak - trough) gap seen.

        Returns
        -------
        dict with keys:
            current_drawdown          -- float, dollars below peak (>= 0)
            peak_balance              -- float, highest ending_balance ever recorded
            max_historical_drawdown   -- float, worst peak-to-trough drop ever
            drawdown_pct              -- float, current_drawdown / peak_balance * 100
                                         (0.0 if peak_balance is zero)
        """
        sql = "SELECT ending_balance FROM daily_pnl ORDER BY date ASC"
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(sql).fetchall()
            finally:
                conn.close()

        if not rows:
            return {
                "current_drawdown": 0.0,
                "peak_balance": 0.0,
                "max_historical_drawdown": 0.0,
                "drawdown_pct": 0.0,
            }

        peak: float = 0.0
        max_dd: float = 0.0
        latest_balance: float = 0.0

        for row in rows:
            balance = float(row["ending_balance"] or 0.0)
            latest_balance = balance
            if balance > peak:
                peak = balance
            dd = peak - balance
            if dd > max_dd:
                max_dd = dd

        current_dd = max(0.0, peak - latest_balance)
        dd_pct = (current_dd / peak * 100.0) if peak > 0 else 0.0

        return {
            "current_drawdown": round(current_dd, 4),
            "peak_balance": round(peak, 4),
            "max_historical_drawdown": round(max_dd, 4),
            "drawdown_pct": round(dd_pct, 4),
        }
