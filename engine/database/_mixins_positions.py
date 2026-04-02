"""
JARVIS TRADER — Positions Mixin
=================================
DatabaseManager mixin providing CRUD methods for the positions table.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from ._helpers import _utcnow

logger = logging.getLogger("jarvis_trader.database")


class PositionsMixin:
    """Methods for the ``positions`` table."""

    def upsert_position(
        self,
        *,
        symbol: str,
        quantity: float,
        entry_price: float,
        entry_time: Optional[str] = None,
        current_price: Optional[float] = None,
        unrealized_pnl: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> None:
        """
        Insert or replace a position row for the given symbol.

        The ``positions`` table holds one row per symbol representing the
        current open position.  Calling this with quantity=0 does NOT
        delete the row; use ``delete_position`` to remove a closed position.
        """
        ts = entry_time or _utcnow()
        sql = """
            INSERT OR REPLACE INTO positions
                (symbol, quantity, entry_price, entry_time, current_price,
                 unrealized_pnl, stop_loss, take_profit)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            symbol.upper(),
            quantity,
            entry_price,
            ts,
            current_price,
            unrealized_pnl,
            stop_loss,
            take_profit,
        )
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(sql, params)
                conn.commit()
                logger.debug(
                    f"[DB] upsert_position symbol={symbol} qty={quantity} "
                    f"entry={entry_price} unrealized_pnl={unrealized_pnl}"
                )
            finally:
                conn.close()

    def update_position_price(
        self,
        *,
        symbol: str,
        current_price: float,
        unrealized_pnl: float,
    ) -> bool:
        """
        Update only the ``current_price`` and ``unrealized_pnl`` for an
        existing position (used during intraday price ticks).

        Returns True if the symbol was found, False if it was not.
        """
        sql = """
            UPDATE positions
            SET current_price  = ?,
                unrealized_pnl = ?
            WHERE symbol = ?
        """
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(sql, (current_price, unrealized_pnl, symbol.upper()))
                conn.commit()
                return cur.rowcount > 0
            finally:
                conn.close()

    def delete_position(self, symbol: str) -> bool:
        """
        Remove a position row (call this when a position is fully closed).
        Returns True if a row was deleted, False if symbol was not found.
        """
        sql = "DELETE FROM positions WHERE symbol = ?"
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(sql, (symbol.upper(),))
                conn.commit()
                deleted = cur.rowcount > 0
                if deleted:
                    logger.debug(f"[DB] delete_position symbol={symbol}")
                return deleted
            finally:
                conn.close()

    def get_all_positions(self) -> List[Dict]:
        """Return all current open positions ordered by symbol."""
        sql = "SELECT * FROM positions ORDER BY symbol ASC"
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(sql).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    def get_position(self, symbol: str) -> Optional[Dict]:
        """Return a single position row for the given symbol, or None."""
        sql = "SELECT * FROM positions WHERE symbol = ?"
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(sql, (symbol.upper(),)).fetchone()
                return dict(row) if row else None
            finally:
                conn.close()
