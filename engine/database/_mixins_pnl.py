"""
JARVIS TRADER — Daily P&L Mixin
=================================
DatabaseManager mixin providing CRUD methods for the daily_pnl table.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

logger = logging.getLogger("jarvis_trader.database")


class DailyPnLMixin:
    """Methods for the ``daily_pnl`` table."""

    def upsert_daily_pnl(
        self,
        *,
        date: str,
        starting_balance: float,
        ending_balance: float,
        realized_pnl: float,
        unrealized_pnl: float,
        total_trades: int,
        winning_trades: int,
        losing_trades: int,
        max_drawdown: float,
    ) -> None:
        """
        Insert or replace the P&L snapshot for the given date (YYYY-MM-DD).

        Uses INSERT OR REPLACE so repeated end-of-day snapshots overwrite
        the previous row for the same date.
        """
        sql = """
            INSERT OR REPLACE INTO daily_pnl
                (date, starting_balance, ending_balance, realized_pnl,
                 unrealized_pnl, total_trades, winning_trades, losing_trades,
                 max_drawdown)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            date,
            starting_balance,
            ending_balance,
            realized_pnl,
            unrealized_pnl,
            total_trades,
            winning_trades,
            losing_trades,
            max_drawdown,
        )
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(sql, params)
                conn.commit()
                logger.debug(f"[DB] upsert_daily_pnl date={date} realized={realized_pnl:+.2f}")
            finally:
                conn.close()

    def get_daily_pnl(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        days: Optional[int] = None,
    ) -> List[Dict]:
        """
        Return daily P&L rows, optionally filtered by date range (YYYY-MM-DD).

        If ``days`` is set and ``start_date`` is not, rows on or after
        (today UTC − ``days`` calendar days) are returned.
        Results are ordered oldest-first (ascending date).
        """
        clauses = []
        params: list = []
        if start_date:
            clauses.append("date >= ?")
            params.append(start_date)
        elif days is not None:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=int(days))).date().isoformat()
            clauses.append("date >= ?")
            params.append(cutoff)
        if end_date:
            clauses.append("date <= ?")
            params.append(end_date)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT * FROM daily_pnl {where} ORDER BY date ASC"

        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(sql, params).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    def get_latest_daily_pnl(self) -> Optional[Dict]:
        """Return the most recent daily P&L snapshot row, or None."""
        sql = "SELECT * FROM daily_pnl ORDER BY date DESC LIMIT 1"
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(sql).fetchone()
                return dict(row) if row else None
            finally:
                conn.close()

    # ── P&L Snapshots (safety layer persistence) ──────────────────────────────────────

    def upsert_pnl_snapshot(
        self,
        *,
        date: str,
        daily_pnl: float,
        portfolio_equity: float,
        peak_equity: float = 0.0,
        consecutive_losses: int = 0,
    ) -> None:
        """
        Insert or replace the intraday P&L snapshot for the given date.

        Called by SafetyLayer every time daily_pnl updates so state
        survives engine restarts mid-session.
        """
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        sql = """
            INSERT OR REPLACE INTO pnl_snapshots
                (date, daily_pnl, portfolio_equity, peak_equity, consecutive_losses, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(sql, (date, daily_pnl, portfolio_equity, peak_equity, consecutive_losses, now_utc))
                conn.commit()
                logger.debug(
                    "[DB] upsert_pnl_snapshot date=%s daily_pnl=%+.2f equity=%.2f",
                    date, daily_pnl, portfolio_equity,
                )
            finally:
                conn.close()

    def get_pnl_snapshot(self, date: str) -> Optional[Dict]:
        """
        Return the P&L snapshot for the given date (YYYY-MM-DD), or None.
        Used by SafetyLayer on startup to restore intraday state.
        """
        sql = "SELECT * FROM pnl_snapshots WHERE date = ? LIMIT 1"
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(sql, (date,)).fetchone()
                return dict(row) if row else None
            finally:
                conn.close()
