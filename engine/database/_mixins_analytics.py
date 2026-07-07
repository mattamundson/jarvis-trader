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

        Queries ``paper_trades`` for trade counts, P&L totals and the
        trade-level derived metrics the dashboard/API surface
        (``StatsSummaryResponse``) expects, plus ``daily_pnl`` for
        best/worst day and active-day count.

        Previously this method only returned counts, ``total_pnl`` and the
        day-level extremes; the API response model also declares
        ``win_rate``, ``avg_win``, ``avg_loss``, ``profit_factor``,
        ``best_trade`` and ``worst_trade``, which were never computed and so
        defaulted to 0.0 on the live ``/portfolio/stats/summary`` endpoint
        (e.g. a 0% win rate / 0 profit factor shown over 19 real trades).

        Returns
        -------
        dict with keys:
            total_trades      -- int, all closed trades
            winning_trades    -- int, closed trades where pnl > 0
            losing_trades     -- int, closed trades where pnl < 0
            win_rate          -- float, winning_trades / total_trades (0-1)
            total_pnl         -- float, sum of pnl for all closed trades
            avg_win           -- float, mean pnl across winning trades
            avg_loss          -- float, mean pnl across losing trades (<= 0)
            profit_factor     -- float, gross_profit / abs(gross_loss);
                                 0.0 when there are no losing trades
            best_trade        -- float, single best closed-trade pnl
            worst_trade       -- float, single worst closed-trade pnl
            best_day          -- float, highest single-day realized_pnl
            worst_day         -- float, lowest single-day realized_pnl
            active_days       -- int, number of rows in daily_pnl
        """
        sql_trades = """
            SELECT
                COUNT(*)                              AS total_trades,
                SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS winning_trades,
                SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) AS losing_trades,
                COALESCE(SUM(pnl), 0.0)              AS total_pnl,
                COALESCE(SUM(CASE WHEN pnl > 0 THEN pnl ELSE 0 END), 0.0) AS gross_profit,
                COALESCE(SUM(CASE WHEN pnl < 0 THEN pnl ELSE 0 END), 0.0) AS gross_loss,
                COALESCE(AVG(CASE WHEN pnl > 0 THEN pnl END), 0.0)        AS avg_win,
                COALESCE(AVG(CASE WHEN pnl < 0 THEN pnl END), 0.0)        AS avg_loss,
                COALESCE(MAX(pnl), 0.0)              AS best_trade,
                COALESCE(MIN(pnl), 0.0)             AS worst_trade
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

        total_trades = int(tr["total_trades"]) if tr and tr["total_trades"] else 0
        winning_trades = int(tr["winning_trades"]) if tr and tr["winning_trades"] else 0
        losing_trades = int(tr["losing_trades"]) if tr and tr["losing_trades"] else 0
        gross_profit = float(tr["gross_profit"]) if tr and tr["gross_profit"] is not None else 0.0
        # gross_loss is the sum of negative pnls, so it is <= 0.
        gross_loss = float(tr["gross_loss"]) if tr and tr["gross_loss"] is not None else 0.0

        win_rate = (winning_trades / total_trades) if total_trades > 0 else 0.0
        profit_factor = (gross_profit / abs(gross_loss)) if gross_loss < 0 else 0.0

        return {
            "total_trades": total_trades,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "win_rate": round(win_rate, 4),
            "total_pnl": float(tr["total_pnl"]) if tr else 0.0,
            "avg_win": float(tr["avg_win"]) if tr and tr["avg_win"] is not None else 0.0,
            "avg_loss": float(tr["avg_loss"]) if tr and tr["avg_loss"] is not None else 0.0,
            "profit_factor": round(profit_factor, 4),
            "best_trade": float(tr["best_trade"]) if tr and tr["best_trade"] is not None else 0.0,
            "worst_trade": float(tr["worst_trade"]) if tr and tr["worst_trade"] is not None else 0.0,
            # Day-level extras retained for backward compatibility (stripped by
            # StatsSummaryResponse but consumed by ad-hoc callers / tests).
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
        dict carrying both the ``DrawdownResponse`` (api/models.py) API field
        names and the legacy dollar-denominated keys. The API field names were
        previously absent, so ``/portfolio/stats/drawdown`` silently served 0.0
        for all four (peak_equity / current_equity / *_pct) over a real curve.

            current_drawdown_pct      -- float, current_drawdown / peak_equity * 100
            max_drawdown_pct          -- float, max_dd / (peak at that trough) * 100
            peak_equity               -- float, highest ending_balance ever recorded
            current_equity            -- float, latest ending_balance
            current_drawdown          -- float, dollars below peak (>= 0) [legacy]
            peak_balance              -- float, == peak_equity [legacy]
            max_historical_drawdown   -- float, worst peak-to-trough drop, $ [legacy]
            drawdown_pct              -- float, == current_drawdown_pct [legacy]
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
                "current_drawdown_pct": 0.0,
                "max_drawdown_pct": 0.0,
                "peak_equity": 0.0,
                "current_equity": 0.0,
                # Legacy keys (backward compatibility).
                "current_drawdown": 0.0,
                "peak_balance": 0.0,
                "max_historical_drawdown": 0.0,
                "drawdown_pct": 0.0,
            }

        peak: float = 0.0
        max_dd: float = 0.0
        max_dd_peak: float = 0.0
        latest_balance: float = 0.0

        for row in rows:
            balance = float(row["ending_balance"] or 0.0)
            latest_balance = balance
            if balance > peak:
                peak = balance
            dd = peak - balance
            if dd > max_dd:
                max_dd = dd
                max_dd_peak = peak

        current_dd = max(0.0, peak - latest_balance)
        current_dd_pct = (current_dd / peak * 100.0) if peak > 0 else 0.0
        # Percentage relative to the peak in force at the worst trough, not the
        # global peak, so a later-recovered curve still reports its true max DD.
        max_dd_pct = (max_dd / max_dd_peak * 100.0) if max_dd_peak > 0 else 0.0

        return {
            # Fields declared by DrawdownResponse (api/models.py) -- previously
            # absent from this dict, so /portfolio/stats/drawdown served 0.0 for
            # all four over a real equity curve.
            "current_drawdown_pct": round(current_dd_pct, 4),
            "max_drawdown_pct": round(max_dd_pct, 4),
            "peak_equity": round(peak, 4),
            "current_equity": round(latest_balance, 4),
            # Legacy dollar-denominated keys retained for backward compatibility.
            "current_drawdown": round(current_dd, 4),
            "peak_balance": round(peak, 4),
            "max_historical_drawdown": round(max_dd, 4),
            "drawdown_pct": round(current_dd_pct, 4),
        }
