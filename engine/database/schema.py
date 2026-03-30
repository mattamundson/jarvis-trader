"""
JARVIS TRADER — SQLite Database Manager
=========================================
Provides a thread-safe DatabaseManager that owns a single SQLite file and
exposes typed insert/query helpers for every table in the schema.

Design decisions
----------------
* No ORM — plain sqlite3 for zero extra dependencies.
* Connection-per-call pattern: each public method opens a connection,
  executes, commits, and closes.  This avoids shared-connection threading
  hazards without the complexity of a connection pool.
* A threading.Lock serialises concurrent writes (rare in practice, since
  FastAPI runs in one event loop, but the lock makes this safe if helpers
  are ever called from background threads or APScheduler jobs).
* WAL journal mode is set on each new connection for better read concurrency.
* All timestamps are stored as ISO-8601 UTC strings ("YYYY-MM-DDTHH:MM:SS").
* JSON blobs (signal_data_json, strategy_params) are stored as TEXT;
  callers pass pre-serialised strings or dicts (auto-serialised here).

Tables
------
  paper_trades   — individual trade records (open & closed)
  decisions      — pipeline decision log with agent reasoning
  daily_pnl      — end-of-day P&L snapshots
  positions      — current open positions (live mirror)
  settings       — key/value config store
  pipeline_runs  — history of every TradingPipeline execution
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .migrations import run_migrations

logger = logging.getLogger("jarvis_trader.database")

# ── Helpers ───────────────────────────────────────────────────────────────────


def _utcnow() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _to_json(value: Any) -> Optional[str]:
    """Serialise a dict/list to a JSON string; pass through strings/None."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, default=str)


def _from_json(value: Optional[str]) -> Any:
    """Deserialise a JSON string; return None/non-string values unchanged."""
    if value is None or not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, ValueError):
        return value  # return raw string if it is not valid JSON


# ── DatabaseManager ───────────────────────────────────────────────────────────


class DatabaseManager:
    """
    Thread-safe SQLite manager for JARVIS TRADER.

    Parameters
    ----------
    db_path:
        Path to the SQLite file.  Defaults to ``data/jarvis_trader.db``
        relative to the *engine* package root (i.e. one directory above
        this file's parent).
    """

    def __init__(self, db_path: str = "data/jarvis_trader.db") -> None:
        # Resolve relative paths against the engine root (two levels up from here)
        engine_root = Path(__file__).parent.parent
        self._db_path: Path = (
            Path(db_path) if Path(db_path).is_absolute() else engine_root / db_path
        )
        self._lock = threading.Lock()
        logger.info(f"DatabaseManager initialised — db_path={self._db_path}")

    # ── Internal connection factory ────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        """
        Open a new SQLite connection to the database file.

        * Creates parent directories if they do not exist.
        * Enables WAL journal mode for better concurrent read performance.
        * Sets row_factory so rows behave like dicts (sqlite3.Row).
        * Enables foreign-key enforcement.
        """
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")  # safe with WAL, faster than FULL
        return conn

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def initialize(self) -> None:
        """
        Create tables (if not present) and run any pending migrations.

        Safe to call multiple times — all operations are idempotent.
        Should be called once at application startup before any other method.
        """
        logger.info("Initialising database schema...")
        with self._lock:
            conn = self._connect()
            try:
                run_migrations(conn)
            finally:
                conn.close()
        logger.info(f"Database ready at {self._db_path}")

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
        """
        Return the most recent closed trades, optionally filtered by symbol.
        """
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
            clauses.append("status = ?")
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
                    # Ensure pnl is always a float (NULL → 0.0)
                    d["pnl"] = float(d["pnl"]) if d.get("pnl") is not None else 0.0
                    d["strategy_params"] = _from_json(d.get("strategy_params"))
                    result.append(d)
                return result
            finally:
                conn.close()

    # ── Analytics / summary helpers ───────────────────────────────────────

    def get_stats_summary(self) -> Dict[str, Any]:
        """
        Return high-level trading statistics.

        Queries ``paper_trades`` for trade counts / P&L totals and
        ``daily_pnl`` for best/worst day and active-day count.

        Returns
        -------
        dict with keys:
            total_trades      — int, all closed trades
            winning_trades    — int, closed trades where pnl > 0
            losing_trades     — int, closed trades where pnl < 0
            total_pnl         — float, sum of pnl for all closed trades
            best_day          — float, highest single-day realized_pnl
            worst_day         — float, lowest single-day realized_pnl
            active_days       — int, number of rows in daily_pnl
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
            current_drawdown          — float, dollars below peak (>= 0)
            peak_balance              — float, highest ending_balance ever recorded
            max_historical_drawdown   — float, worst peak-to-trough drop ever
            drawdown_pct              — float, current_drawdown / peak_balance * 100
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

    # ── decisions ─────────────────────────────────────────────────────────

    def insert_decision(
        self,
        *,
        symbol: str,
        action: str,
        confidence: Optional[float] = None,
        regime: Optional[str] = None,
        signal_data: Optional[Any] = None,
        reasoning: Optional[str] = None,
        timestamp: Optional[str] = None,
    ) -> int:
        """
        Log a pipeline decision.

        Parameters
        ----------
        symbol:       Ticker symbol (e.g. "AAPL").
        action:       Decision string: "buy" | "sell" | "hold" | "exit_long" | "exit_short".
        confidence:   Agent confidence score in [0.0, 1.0].
        regime:       Market regime label at decision time (e.g. "bullish", "ranging").
        signal_data:  Dict or JSON string of raw indicator values / agent scores.
        reasoning:    Full LLM reasoning text.
        timestamp:    ISO-8601 UTC; defaults to now.

        Returns the auto-incremented ``id``.
        """
        ts = timestamp or _utcnow()
        sql = """
            INSERT INTO decisions
                (symbol, timestamp, action, confidence, regime, signal_data_json, reasoning)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            symbol.upper(),
            ts,
            action.lower(),
            confidence,
            regime,
            _to_json(signal_data),
            reasoning,
        )
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(sql, params)
                conn.commit()
                row_id: int = cur.lastrowid  # type: ignore[assignment]
                logger.debug(
                    f"[DB] insert_decision id={row_id} symbol={symbol} "
                    f"action={action} confidence={confidence}"
                )
                return row_id
            finally:
                conn.close()

    def get_decisions(
        self,
        symbol: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict]:
        """
        Query the decisions log.

        Parameters
        ----------
        symbol: Filter by ticker (optional).
        action: Filter by action type (optional).
        limit:  Maximum rows to return (default 100).

        JSON fields (signal_data_json) are deserialised before returning.
        """
        clauses = []
        params: list = []
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol.upper())
        if action:
            clauses.append("action = ?")
            params.append(action.lower())

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT * FROM decisions {where} ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(sql, params).fetchall()
                result = []
                for r in rows:
                    d = dict(r)
                    d["signal_data_json"] = _from_json(d.get("signal_data_json"))
                    result.append(d)
                return result
            finally:
                conn.close()

    # ── daily_pnl ─────────────────────────────────────────────────────────

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

    # ── positions ─────────────────────────────────────────────────────────

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

    # ── settings ──────────────────────────────────────────────────────────

    def set_setting(self, key: str, value: Any) -> None:
        """
        Store a key/value setting.

        ``value`` can be any JSON-serialisable type.  Dicts and lists are
        automatically serialised.  The row is inserted or replaced.
        """
        sql = """
            INSERT OR REPLACE INTO settings (key, value, updated_at)
            VALUES (?, ?, ?)
        """
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(sql, (key, _to_json(value), _utcnow()))
                conn.commit()
                logger.debug(f"[DB] set_setting key={key!r}")
            finally:
                conn.close()

    def get_setting(self, key: str, default: Any = None) -> Any:
        """
        Retrieve a setting by key.

        Returns ``default`` if the key does not exist.  JSON values are
        automatically deserialised.
        """
        sql = "SELECT value FROM settings WHERE key = ?"
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(sql, (key,)).fetchone()
                if row is None:
                    return default
                return _from_json(row["value"])
            finally:
                conn.close()

    def get_all_settings(self) -> Dict[str, Any]:
        """Return all settings as a plain dict {key: value}."""
        sql = "SELECT key, value FROM settings ORDER BY key ASC"
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(sql).fetchall()
                return {r["key"]: _from_json(r["value"]) for r in rows}
            finally:
                conn.close()

    def delete_setting(self, key: str) -> bool:
        """Delete a setting by key.  Returns True if it existed."""
        sql = "DELETE FROM settings WHERE key = ?"
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(sql, (key,))
                conn.commit()
                return cur.rowcount > 0
            finally:
                conn.close()

    # ── trade_journal ─────────────────────────────────────────────────────

    def add_journal_entry(
        self,
        trade_id: str,
        note: str,
        tags: Optional[str] = None,
        mood: Optional[str] = None,
        lesson: Optional[str] = None,
        timestamp: Optional[str] = None,
    ) -> int:
        """
        Insert a new journal entry linked to a trade.

        Parameters
        ----------
        trade_id:   UUID of the associated paper trade (soft FK, not enforced).
        note:       Free-text journal body.
        tags:       Comma-separated tag string, e.g. "missed_entry,good_setup".
        mood:       One of "confident", "uncertain", "frustrated", "neutral".
        lesson:     What was learned from this trade.
        timestamp:  ISO-8601 UTC; defaults to now.

        Returns the auto-incremented ``id`` of the new row.
        """
        ts = timestamp or _utcnow()
        sql = """
            INSERT INTO trade_journal
                (trade_id, timestamp, note, tags, mood, lesson)
            VALUES (?, ?, ?, ?, ?, ?)
        """
        params = (trade_id, ts, note, tags, mood, lesson)
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(sql, params)
                conn.commit()
                row_id: int = cur.lastrowid  # type: ignore[assignment]
                logger.debug(f"[DB] add_journal_entry id={row_id} trade_id={trade_id[:8]}")
                return row_id
            finally:
                conn.close()

    def get_journal_entries(
        self,
        trade_id: Optional[str] = None,
        tag: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict]:
        """
        Return journal entries, optionally filtered by trade_id and/or tag.

        Parameters
        ----------
        trade_id:  If provided, return only entries for this trade UUID.
        tag:       If provided, return only entries whose tags column contains
                   this exact tag token (case-insensitive substring match on
                   comma-separated list).
        limit:     Maximum number of rows to return (default 50).

        Results are ordered newest-first.
        """
        clauses: list = []
        params: list = []
        if trade_id:
            clauses.append("trade_id = ?")
            params.append(trade_id)
        if tag:
            # Match the tag anywhere in the comma-separated tags field.
            clauses.append("(',' || LOWER(tags) || ',') LIKE ?")
            params.append(f"%,{tag.lower()},%")

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT * FROM trade_journal {where} ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(sql, params).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    def get_journal_tags(self) -> List[str]:
        """
        Return a sorted list of unique tag tokens used across all journal entries.

        Tags are stored as comma-separated strings; this method splits every
        row and deduplicates the individual tokens.
        """
        sql = "SELECT tags FROM trade_journal WHERE tags IS NOT NULL AND tags != ''"
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(sql).fetchall()
            finally:
                conn.close()

        seen: set = set()
        for row in rows:
            for token in row["tags"].split(","):
                stripped = token.strip()
                if stripped:
                    seen.add(stripped)
        return sorted(seen)

    def update_journal_entry(
        self,
        entry_id: int,
        note: Optional[str] = None,
        tags: Optional[str] = None,
        mood: Optional[str] = None,
        lesson: Optional[str] = None,
    ) -> bool:
        """
        Partially update a journal entry.  Only supplied (non-None) fields
        are changed.  Returns True if the row existed, False otherwise.
        """
        set_clauses: list = []
        params: list = []
        if note is not None:
            set_clauses.append("note = ?")
            params.append(note)
        if tags is not None:
            set_clauses.append("tags = ?")
            params.append(tags)
        if mood is not None:
            set_clauses.append("mood = ?")
            params.append(mood)
        if lesson is not None:
            set_clauses.append("lesson = ?")
            params.append(lesson)

        if not set_clauses:
            return True  # nothing to update, treat as no-op success

        params.append(entry_id)
        sql = f"UPDATE trade_journal SET {', '.join(set_clauses)} WHERE id = ?"

        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(sql, params)
                conn.commit()
                updated = cur.rowcount > 0
                if updated:
                    logger.debug(f"[DB] update_journal_entry id={entry_id}")
                return updated
            finally:
                conn.close()

    def delete_journal_entry(self, entry_id: int) -> bool:
        """
        Delete a journal entry by its integer primary key.
        Returns True if a row was deleted, False if id was not found.
        """
        sql = "DELETE FROM trade_journal WHERE id = ?"
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(sql, (entry_id,))
                conn.commit()
                deleted = cur.rowcount > 0
                if deleted:
                    logger.debug(f"[DB] delete_journal_entry id={entry_id}")
                return deleted
            finally:
                conn.close()

    # ── journal_notes ─────────────────────────────────────────────────────

    def insert_journal_note(
        self,
        note_type: str,
        title: str,
        body: str = "",
        tags: Optional[List] = None,
        trade_id: Optional[str] = None,
    ) -> int:
        """
        Insert a new journal note.

        Parameters
        ----------
        note_type:  One of "observation", "lesson", "alert".
        title:      Short title for the note (required).
        body:       Free-text body (optional).
        tags:       List of tag strings; stored as JSON array.
        trade_id:   Optional UUID of a linked paper trade (soft FK).

        Returns the auto-incremented ``id`` of the new row.
        """
        now = _utcnow()
        sql = """
            INSERT INTO journal_notes
                (trade_id, note_type, title, body, tags, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            trade_id,
            note_type,
            title,
            body,
            json.dumps(tags or []),
            now,
            now,
        )
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(sql, params)
                conn.commit()
                row_id: int = cur.lastrowid  # type: ignore[assignment]
                logger.debug(
                    f"[DB] insert_journal_note id={row_id} type={note_type} title={title!r}"
                )
                return row_id
            finally:
                conn.close()

    def get_journal_notes(
        self,
        limit: int = 50,
        note_type: Optional[str] = None,
        trade_id: Optional[str] = None,
    ) -> List[Dict]:
        """
        Return journal notes, newest first.

        Parameters
        ----------
        limit:      Maximum rows to return (default 50, capped at 200).
        note_type:  Filter by type — "observation" | "lesson" | "alert".
        trade_id:   Filter to notes linked to a specific paper trade.

        ``tags`` is deserialised from JSON array before returning.
        """
        conditions: list = []
        params: list = []
        if note_type:
            conditions.append("note_type = ?")
            params.append(note_type)
        if trade_id:
            conditions.append("trade_id = ?")
            params.append(trade_id)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params.append(min(limit, 200))

        with self._lock:
            conn = self._connect()
            try:
                cursor = conn.execute(
                    f"SELECT * FROM journal_notes {where} ORDER BY created_at DESC LIMIT ?",
                    params,
                )
                col_names = [d[0] for d in cursor.description]
                notes = []
                for row in cursor.fetchall():
                    note = dict(zip(col_names, row, strict=False))
                    try:
                        note["tags"] = json.loads(note.get("tags") or "[]")
                    except Exception:
                        note["tags"] = []
                    notes.append(note)
                return notes
            finally:
                conn.close()

    def delete_journal_note(self, note_id: int) -> bool:
        """
        Delete a journal note by its integer primary key.
        Returns True if a row was deleted, False if id was not found.
        """
        sql = "DELETE FROM journal_notes WHERE id = ?"
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(sql, (note_id,))
                conn.commit()
                deleted = cur.rowcount > 0
                if deleted:
                    logger.debug(f"[DB] delete_journal_note id={note_id}")
                return deleted
            finally:
                conn.close()

    # ── alert_log ─────────────────────────────────────────────────────────

    def insert_alert_log(
        self,
        alert_type: str,
        message: str,
        channel: str = "whatsapp",
        symbol: Optional[str] = None,
        status: str = "sent",
        error: Optional[str] = None,
    ) -> int:
        """
        Insert an alert log row and return the new auto-incremented id.

        Parameters
        ----------
        alert_type:
            Category of alert — e.g. 'trade_opened', 'trade_closed',
            'morning_briefing', 'vix_alert', 'circuit_breaker', 'notification'.
        message:
            The full message text that was sent (or attempted).
        channel:
            Delivery channel, default 'whatsapp'.
        symbol:
            Optional ticker symbol (None for non-trade alerts).
        status:
            'sent' | 'failed' | 'suppressed'
        error:
            Error text when status='failed', None otherwise.
        """
        created_at = _utcnow()
        sql = """
            INSERT INTO alert_log (alert_type, symbol, message, channel, status, error, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        params = (alert_type, symbol, message, channel, status, error, created_at)
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(sql, params)
                conn.commit()
                new_id = cur.lastrowid
                logger.debug(
                    f"[DB] insert_alert_log id={new_id} type={alert_type} "
                    f"status={status} symbol={symbol}"
                )
                return new_id
            finally:
                conn.close()

    def get_alert_history(
        self,
        limit: int = 100,
        alert_type: Optional[str] = None,
    ) -> List[Dict]:
        """
        Return alert log rows ordered newest-first.

        Parameters
        ----------
        limit:
            Maximum rows to return (default 100, hard-capped by the caller).
        alert_type:
            If supplied, filter to rows with this alert_type value.

        Returns
        -------
        list[dict]
            Each dict contains: id, alert_type, symbol, message, channel,
            status, error, created_at.
        """
        conditions: list = []
        params: list = []
        if alert_type:
            conditions.append("alert_type = ?")
            params.append(alert_type)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params.append(min(limit, 500))

        sql = f"""
            SELECT id, alert_type, symbol, message, channel, status, error, created_at
            FROM alert_log
            {where}
            ORDER BY created_at DESC
            LIMIT ?
        """
        with self._lock:
            conn = self._connect()
            try:
                cursor = conn.execute(sql, params)
                col_names = [d[0] for d in cursor.description]
                return [dict(zip(col_names, row, strict=False)) for row in cursor.fetchall()]
            finally:
                conn.close()

    # ── pipeline_runs ─────────────────────────────────────────────────────

    def insert_pipeline_run(self, run_data: dict) -> int:
        """
        Insert a pipeline run record and return the auto-incremented rowid.

        Expected keys in run_data
        -------------------------
        run_id          str   — 8-char UUID prefix (required)
        symbol          str   — ticker (required)
        status          str   — "completed" | "error" | "skipped" (required)
        webhook_action  str   — "LONG" | "SHORT" | "CLOSE" | None
        source          str   — default "tradingview"
        final_action    str   — "buy" | "sell" | "hold" | "pending_human_approval"
        final_quantity  int   — contract / share count
        requires_human  bool  — whether human approval is needed
        summary         str   — human-readable one-liner from pipeline
        error_message   str   — populated when status="error"
        duration_ms     float — elapsed milliseconds for the full run
        created_at      str   — ISO-8601 UTC; defaults to now
        """
        created_at = run_data.get("created_at") or _utcnow()
        sql = """
            INSERT INTO pipeline_runs
                (run_id, symbol, webhook_action, source, final_action,
                 final_quantity, requires_human, summary, status,
                 error_message, duration_ms, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            run_data["run_id"],
            run_data["symbol"].upper(),
            run_data.get("webhook_action"),
            run_data.get("source", "tradingview"),
            run_data.get("final_action"),
            run_data.get("final_quantity"),
            int(bool(run_data.get("requires_human", False))),
            run_data.get("summary"),
            run_data["status"],
            run_data.get("error_message"),
            run_data.get("duration_ms"),
            created_at,
        )
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(sql, params)
                conn.commit()
                row_id: int = cur.lastrowid  # type: ignore[assignment]
                logger.debug(
                    f"[DB] insert_pipeline_run id={row_id} run_id={run_data['run_id']} "
                    f"symbol={run_data['symbol']} status={run_data['status']}"
                )
                return row_id
            finally:
                conn.close()

    def get_pipeline_history(
        self,
        limit: int = 50,
        symbol: Optional[str] = None,
    ) -> List[Dict]:
        """
        Return recent pipeline run records, newest first.

        Parameters
        ----------
        limit:   Maximum rows to return (default 50, capped at 200).
        symbol:  Optional ticker filter (case-insensitive).

        Returns a list of dicts with all pipeline_runs columns.
        ``requires_human`` is cast to bool before returning.
        """
        limit = min(limit, 200)
        clauses: list = []
        params: list = []
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol.upper())

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT * FROM pipeline_runs {where} ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(sql, params).fetchall()
                result = []
                for r in rows:
                    d = dict(r)
                    d["requires_human"] = bool(d.get("requires_human", 0))
                    result.append(d)
                return result
            finally:
                conn.close()

    # ── Diagnostics ───────────────────────────────────────────────────────

    def health_check(self) -> Dict[str, Any]:
        """
        Return a dict with row counts per table and the current schema version.

        Useful for the /health or /status endpoints.
        """
        tables = [
            "paper_trades",
            "decisions",
            "daily_pnl",
            "positions",
            "settings",
            "trade_journal",
            "pipeline_runs",
        ]
        counts: Dict[str, int] = {}
        schema_version: int = 0

        with self._lock:
            conn = self._connect()
            try:
                for table in tables:
                    row = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
                    counts[table] = row["n"] if row else 0
                sv_row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
                if sv_row and sv_row["v"] is not None:
                    schema_version = sv_row["v"]
            finally:
                conn.close()

        return {
            "db_path": str(self._db_path),
            "schema_version": schema_version,
            "row_counts": counts,
        }


# ── Singleton factory ──────────────────────────────────────────────────────────

_db_instance: Optional[DatabaseManager] = None
_db_lock = threading.Lock()


def init_db(db_path: Optional[str] = None) -> DatabaseManager:
    """
    Create (or return) the module-level DatabaseManager singleton and
    ensure the schema is up-to-date.

    Parameters
    ----------
    db_path:
        Path to the SQLite file.  Only used on the *first* call; subsequent
        calls return the already-created singleton regardless of db_path.
        Defaults to ``data/jarvis_trader.db`` relative to the engine root.

    Returns
    -------
    DatabaseManager
        The initialised singleton instance.
    """
    global _db_instance
    with _db_lock:
        if _db_instance is None:
            kwargs: dict = {}
            if db_path is not None:
                kwargs["db_path"] = db_path
            _db_instance = DatabaseManager(**kwargs)
            _db_instance.initialize()
            logger.info("Database singleton created and initialised.")
        return _db_instance


def get_db() -> DatabaseManager:
    """
    Return the existing DatabaseManager singleton.

    Raises
    ------
    RuntimeError
        If ``init_db()`` has not been called yet.
    """
    if _db_instance is None:
        raise RuntimeError(
            "DatabaseManager has not been initialised.  "
            "Call init_db() at application startup before calling get_db()."
        )
    return _db_instance
