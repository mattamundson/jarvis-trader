"""
JARVIS TRADER — Daily P&L Mixin
=================================
DatabaseManager mixin providing CRUD methods for the daily_pnl table.
"""

from __future__ import annotations

import logging
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
    ) -> List[Dict]:
        """
        Return daily P&L rows, optionally filtered by date range (YYYY-MM-DD).
        Results are ordered oldest-first (ascending date).
        """
        clauses = []
        params: list = []
        if start_date:
            clauses.append("date >= ?")
            params.append(start_date)
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
