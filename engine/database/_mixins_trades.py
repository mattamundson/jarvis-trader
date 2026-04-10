"""
JARVIS TRADER — Trades Mixin
==============================
DatabaseManager mixin providing CRUD methods for the paper_trades table
and PortfolioTracker-compatible aliases.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ._helpers import _from_json, _to_json, _utcnow

logger = logging.getLogger("jarvis_trader.database")


class TradesMixin:
    """Methods for the ``paper_trades`` table."""

    # ── paper_trades ──────────────────────────────────────────────────────

    def insert_trade(
        self,
        *,
        trade_id: str,
        symbol: str,
        side: str,
        quantity: float,
        entry_price: float,
        entry_time: Optional[str] = None,
        status: str = "open",
        strategy_params: Optional[Any] = None,
        notes: str = "",
    ) -> int:
        """
        Insert a new trade record (typically called on trade open).

        Returns the auto-incremented ``id`` primary key.
        """
        entry_time = entry_time or _utcnow()
        sql = """
            INSERT INTO paper_trades
                (trade_id, symbol, side, quantity, entry_price, entry_time,
                 status, strategy_params, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            trade_id,
            symbol.upper(),
            side.lower(),
            quantity,
            entry_price,
            entry_time,
            status,
            _to_json(strategy_params),
            notes,
        )
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(sql, params)
                conn.commit()
                row_id: int = cur.lastrowid  # type: ignore[assignment]
                logger.debug(
                    f"[DB] insert_trade id={row_id} trade_id={trade_id[:8]} "
                    f"symbol={symbol} side={side} qty={quantity} @{entry_price}"
                )
                return row_id
            finally:
                conn.close()

    def close_trade(
        self,
        *,
        trade_id: str,
        exit_price: float,
        pnl: float,
        exit_time: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> bool:
        """
        Update an open trade to ``status='closed'`` with exit details.

        Returns True if a row was updated, False if trade_id was not found.
        """
        exit_time = exit_time or _utcnow()
        sql = """
            UPDATE paper_trades
            SET exit_price = ?,
                exit_time  = ?,
                pnl        = ?,
                status     = 'closed'
                {notes_clause}
            WHERE trade_id = ? AND status = 'open'
        """
        if notes is not None:
            sql = sql.format(notes_clause=", notes = ?")
            params: tuple = (exit_price, exit_time, pnl, notes, trade_id)
        else:
            sql = sql.format(notes_clause="")
            params = (exit_price, exit_time, pnl, trade_id)

        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(sql, params)
                conn.commit()
                updated = cur.rowcount > 0
                if updated:
                    logger.debug(
                        f"[DB] close_trade trade_id={trade_id[:8]} exit={exit_price} pnl={pnl:+.4f}"
                    )
                else:
                    logger.warning(
                        f"[DB] close_trade — no open trade found for trade_id={trade_id!r}"
                    )
                return updated
            finally:
                conn.close()

    def get_open_trades(self, symbol: Optional[str] = None) -> List[Dict]:
        """
        Return all open trades, optionally filtered by symbol.

        Results are ordered newest-entry-first.
        """
        if symbol:
            sql = (
                "SELECT * FROM paper_trades WHERE status='open' AND symbol=? "
                "ORDER BY entry_time DESC"
            )
            params: tuple = (symbol.upper(),)
        else:
            sql = "SELECT * FROM paper_trades WHERE status='open' ORDER BY entry_time DESC"
            params = ()

        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(sql, params).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    def get_closed_trades(
        self,
        symbol: Optional[str] = None,
        limit: int = 500,
    ) -> List[Dict]:
        """Return the most recent closed trades, optionally filtered by symbol."""
        if symbol:
            sql = (
                "SELECT * FROM paper_trades WHERE status='closed' AND symbol=? "
                "ORDER BY exit_time DESC LIMIT ?"
            )
            params: tuple = (symbol.upper(), limit)
        else:
            sql = "SELECT * FROM paper_trades WHERE status='closed' ORDER BY exit_time DESC LIMIT ?"
            params = (limit,)

        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(sql, params).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    def get_trade_by_id(self, trade_id: str) -> Optional[Dict]:
        """Return a single trade row by its UUID trade_id, or None."""
        sql = "SELECT * FROM paper_trades WHERE trade_id = ?"
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(sql, (trade_id,)).fetchone()
                return dict(row) if row else None
            finally:
                conn.close()

    # ── PortfolioTracker-compatible aliases ───────────────────────────────

    def insert_paper_trade(
        self,
        trade_id: str,
        symbol: str,
        side: str,
        quantity: float,
        entry_price: float,
        entry_time: Optional[str] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        strategy_params: Optional[Any] = None,
    ) -> int:
        """
        Insert a new paper trade record with status='open'.

        This is a positional-argument alias for ``insert_trade`` used by
        ``PortfolioTracker``.  ``stop_loss`` and ``take_profit`` are stored
        inside the ``strategy_params`` JSON blob because the ``paper_trades``
        table does not have dedicated columns for them.

        Returns the auto-incremented ``id`` primary key (SQLite rowid).
        """
        entry_time = entry_time or _utcnow()

        # Merge stop_loss / take_profit into strategy_params so they survive
        # the round-trip even though the table has no dedicated columns.
        merged_params: dict = {}
        if isinstance(strategy_params, dict):
            merged_params.update(strategy_params)
        elif strategy_params is not None:
            merged_params["raw"] = strategy_params
        if stop_loss is not None:
            merged_params["stop_loss"] = stop_loss
        if take_profit is not None:
            merged_params["take_profit"] = take_profit

        sql = """
            INSERT INTO paper_trades
                (trade_id, symbol, side, quantity, entry_price, entry_time,
                 status, strategy_params, notes)
            VALUES (?, ?, ?, ?, ?, ?, 'open', ?, '')
        """
        params = (
            trade_id,
            symbol.upper(),
            side.lower(),
            quantity,
            entry_price,
            entry_time,
            _to_json(merged_params) if merged_params else None,
        )
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(sql, params)
                conn.commit()
                row_id: int = cur.lastrowid  # type: ignore[assignment]
                logger.debug(
                    f"[DB] insert_paper_trade id={row_id} trade_id={trade_id[:8]} "
                    f"symbol={symbol} side={side} qty={quantity} @{entry_price}"
                )
                return row_id
            finally:
                conn.close()

    def close_paper_trade(
        self,
        trade_id: str,
        exit_price: float,
        exit_time: Optional[str] = None,
        pnl: float = 0.0,
    ) -> bool:
        """
        Close an open paper trade: set exit_price, exit_time, pnl, status='closed'.

        Returns True if exactly one row was updated, False otherwise
        (e.g. trade_id not found or already closed).
        """
        exit_time = exit_time or _utcnow()
        sql = """
            UPDATE paper_trades
            SET exit_price = ?,
                exit_time  = ?,
                pnl        = ?,
                status     = 'closed'
            WHERE trade_id = ? AND status = 'open'
        """
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(sql, (exit_price, exit_time, pnl, trade_id))
                conn.commit()
                updated = cur.rowcount == 1
                if updated:
                    logger.debug(
                        f"[DB] close_paper_trade trade_id={trade_id[:8]} "
                        f"exit={exit_price} pnl={pnl:+.4f}"
                    )
                else:
                    logger.warning(
                        f"[DB] close_paper_trade — no open trade found for "
                        f"trade_id={trade_id!r} (rowcount={cur.rowcount})"
                    )
                return updated
            finally:
                conn.close()

    def get_open_positions(self) -> List[Dict]:
        """
        Return all current open positions.

        Primary source: the ``positions`` table (rows with quantity != 0).
        Fallback: if the ``positions`` table is empty, returns open rows from
        ``paper_trades`` instead, so that PortfolioTracker always gets a
        meaningful result regardless of which table is populated.
        """
        sql_positions = "SELECT * FROM positions WHERE quantity != 0 ORDER BY symbol ASC"
        sql_paper = "SELECT * FROM paper_trades WHERE status = 'open' ORDER BY entry_time DESC"
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(sql_positions).fetchall()
                if rows:
                    return [dict(r) for r in rows]
                # Fallback to paper_trades
                rows = conn.execute(sql_paper).fetchall()
                result = []
                for r in rows:
                    d = dict(r)
                    d["strategy_params"] = _from_json(d.get("strategy_params"))
                    result.append(d)
                return result
            finally:
                conn.close()

    def get_trade_history(
        self,
        limit: int = 100,
        symbol: Optional[str] = None,
        status: str = "closed",
    ) -> List[Dict]:
        """
        Return recent trade history from ``paper_trades``.

        Parameters
        ----------
        limit:   Maximum number of rows to return (default 100).
        symbol:  Optional ticker filter (case-insensitive).
        status:  Trade status filter — 'closed' (default), 'open', or 'all'.
                 Use 'all' to skip status filtering entirely.

        ``pnl`` is cast to float before returning.  Results are ordered by
        ``entry_time DESC``.
        """
        clauses: list = []
        params: list = []

        if status != "all":
            clauses.append("LOWER(status) = LOWER(?)")
            params.append(status)
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol.upper())

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT * FROM paper_trades {where} ORDER BY entry_time DESC LIMIT ?"
        params.append(limit)

        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(sql, params).fetchall()
                result = []
                for r in rows:
                    d = dict(r)
                    # Ensure pnl is always a float (NULL -> 0.0)
                    d["pnl"] = float(d["pnl"]) if d.get("pnl") is not None else 0.0
                    d["strategy_params"] = _from_json(d.get("strategy_params"))
                    result.append(d)
                return result
            finally:
                conn.close()

    def get_paper_trades(
        self,
        limit: int = 50,
        status: Optional[str] = None,
    ) -> List[Dict]:
        """
        Return paper trades from ``paper_trades``, newest-first.

        Parameters
        ----------
        limit:  Maximum rows to return (default 50, capped at 500).
        status: Optional status filter ('open', 'closed'). None returns all.
                Comparison is case-insensitive.
        """
        effective_status = "all" if status is None else status
        return self.get_trade_history(
            limit=min(max(limit, 1), 500),
            status=effective_status,
        )
