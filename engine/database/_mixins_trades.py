"""
JARVIS TRADER — Trades Mixin
==============================
DatabaseManager mixin providing CRUD methods for the paper_trades table
and PortfolioTracker-compatible aliases.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from utils.trade_invariants import is_inverted_stop

from ._helpers import _from_json, _to_json, _utcnow, compute_order_idempotency_key

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
        account_id: str = "A",
    ) -> int:
        """
        Insert a new trade record (typically called on trade open).

        Parameters
        ----------
        account_id:
            'A' = production config (default; backwards-compatible).
            'B' = challenger config (set by parallel_paper.dual_emit_paper_trade
            when ENABLE_PARALLEL_PAPER=1).

        Returns the auto-incremented ``id`` primary key.
        """
        entry_time = entry_time or _utcnow()
        idempotency_key = compute_order_idempotency_key(symbol, side, quantity, entry_price)
        sql = """
            INSERT INTO paper_trades
                (trade_id, symbol, side, quantity, entry_price, entry_time,
                 status, strategy_params, notes, account_id, idempotency_key)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            account_id,
            idempotency_key,
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

    def count_closed_trades_on_date(self, date: str) -> int:
        """Count ``status='closed'`` paper_trades whose exit_time falls on the
        given UTC date (YYYY-MM-DD).

        Used by the safety layer's flat daily-loss gate to avoid latching the
        kill switch on a single outlier (almost always a phantom, since a real
        single trade is capped at MAX_TRADE_LOSS_USD). Excludes
        phantom/cancelled rows via the ``status='closed'`` filter.
        """
        sql = (
            "SELECT COUNT(*) AS n FROM paper_trades "
            "WHERE status='closed' AND exit_time IS NOT NULL AND date(exit_time) = ?"
        )
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(sql, (date,)).fetchone()
                return int(row["n"]) if row else 0
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
        idempotency_key: str = "",  # REQUIRED — empty string signals a missing key at call site
    ) -> int:
        """
        Insert a new paper trade record with status='open'.

        This is a positional-argument alias for ``insert_trade`` used by
        ``PortfolioTracker``.  ``stop_loss`` and ``take_profit`` are written to
        their dedicated columns AND mirrored into ``strategy_params`` for
        backwards-compatible JSON reads.

        Idempotency guard (migration_030 / migration_032):
            ``idempotency_key`` is now a REQUIRED parameter.  The schema-level
            NOT NULL constraint added in migration_032 means a NULL key can no
            longer be stored.  Callers MUST supply a key computed by
            ``database._helpers.compute_order_idempotency_key``; omitting it
            raises TypeError at the Python layer before any DB round-trip.

            If a row with the supplied key already exists in ``paper_trades``,
            the INSERT is skipped and the existing row's SQLite ``id`` is
            returned.  A WARNING is logged so the caller can detect the
            deduplicated submission in the audit log.

        Args:
            trade_id:          UUID string from PortfolioTracker.
            symbol:            Instrument ticker (e.g. "MES").
            side:              "buy" | "sell" | "buy_to_open" | "sell_to_open".
            quantity:          Number of contracts.
            entry_price:       Fill price.
            entry_time:        ISO-8601 UTC string; defaults to current UTC time.
            stop_loss:         Stop-loss price (optional).
            take_profit:       Take-profit price (optional).
            strategy_params:   Arbitrary dict or JSON-serialisable value (optional).
            idempotency_key:   REQUIRED — 32-char hex key from
                               ``compute_order_idempotency_key``.  Passing the
                               empty-string default raises TypeError so callers
                               discover the missing argument immediately.

        Returns:
            The auto-incremented ``id`` primary key (SQLite rowid).

        Raises:
            TypeError:   If ``idempotency_key`` is the empty string (i.e. the
                         caller did not supply a key — fail-fast at the Python
                         layer before touching the DB).
            ValueError:  If ``stop_loss`` is on the wrong side of ``entry_price``
                         for the given ``side`` (inverted-stop guard).
        """
        if not idempotency_key:
            raise TypeError(
                "insert_paper_trade() requires a non-empty idempotency_key. "
                "Compute one via database._helpers.compute_order_idempotency_key() "
                "before calling this method. "
                "See migration_032 and docs/runbooks/HEALTH_API_CONTRACT.md §paper_trades."
            )

        entry_time = entry_time or _utcnow()

        if is_inverted_stop(side, entry_price, stop_loss):
            raise ValueError(
                f"Refusing to insert inverted stop: side={side} "
                f"entry_price={entry_price} stop_loss={stop_loss}. "
                "See docs/incident-notes/2026-04-09-mcl-inverted-stop.md"
            )

        # ── Idempotency + open-state pre-check ────────────────────────────────
        # Two complementary guards run BEFORE attempting INSERT.  This avoids
        # relying on UNIQUE constraint exceptions (which vary in SQLite versions)
        # and gives us a clean WARNING + early-return.
        #
        #   1. idempotency_key — collapses EXACT re-submissions that land inside
        #      the 5-second key window (see compute_order_idempotency_key).
        #   2. open-state natural key (symbol, side) — collapses RE-LOGS of a
        #      still-open position that arrive OUTSIDE the 5s window.  This is the
        #      ~6× over-count root cause: re-emissions of the same fill land
        #      42s–1h apart, so they receive DISTINCT idempotency keys and would
        #      each otherwise mint a fresh open row.  The engine holds at most one
        #      position per (symbol, side) [invariant documented in
        #      portfolio/tracker.py], so any existing status='open' row for the
        #      same pair IS this fill — return it instead of duplicating.  A
        #      genuine scale-in would need a bar/decision discriminator added
        #      here; until pyramiding exists, one-open-row-per-(symbol,side) holds.
        with self._lock:
            conn = self._connect()
            try:
                existing = conn.execute(
                    "SELECT id, trade_id FROM paper_trades WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
                dedup_reason = "idempotency_key=%s" % idempotency_key
                if existing is None:
                    existing = conn.execute(
                        "SELECT id, trade_id FROM paper_trades "
                        "WHERE symbol = ? AND side = ? AND status = 'open' "
                        "ORDER BY entry_time ASC LIMIT 1",
                        (symbol.upper(), side.lower()),
                    ).fetchone()
                    dedup_reason = "open-position (symbol=%s side=%s)" % (
                        symbol.upper(),
                        side.lower(),
                    )
            finally:
                conn.close()
        if existing is not None:
            logger.warning(
                "[DB] insert_paper_trade DEDUPLICATED — %s already exists "
                "(existing id=%s trade_id=%s). Returning existing id without INSERT.",
                dedup_reason,
                existing[0],
                existing[1][:8] if existing[1] else "?",
            )
            return existing[0]  # type: ignore[return-value]

        # Mirror stop_loss / take_profit into strategy_params for backwards
        # compatibility, while also writing them to their dedicated columns.
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
                 status, stop_loss, strategy_params, notes, idempotency_key)
            VALUES (?, ?, ?, ?, ?, ?, 'open', ?, ?, '', ?)
        """
        params = (
            trade_id,
            symbol.upper(),
            side.lower(),
            quantity,
            entry_price,
            entry_time,
            stop_loss,
            _to_json(merged_params) if merged_params else None,
            idempotency_key,
        )
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(sql, params)
                conn.commit()
                row_id: int = cur.lastrowid  # type: ignore[assignment]
                logger.debug(
                    f"[DB] insert_paper_trade id={row_id} trade_id={trade_id[:8]} "
                    f"symbol={symbol} side={side} qty={quantity} @{entry_price} "
                    f"idem_key={idempotency_key}"
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

    def update_paper_trade_strategy_params(
        self,
        trade_id: str,
        strategy_params: dict,
    ) -> bool:
        """
        Merge ``strategy_params`` into an existing paper_trades row.

        Reads the current strategy_params JSON blob, merges the supplied dict
        (supplied keys win on collision), and writes back atomically.  No-ops
        gracefully when the trade_id is not found (returns False).

        Returns True when exactly one row was updated.
        """
        sql_read = "SELECT strategy_params FROM paper_trades WHERE trade_id = ?"
        sql_write = "UPDATE paper_trades SET strategy_params = ? WHERE trade_id = ?"
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(sql_read, (trade_id,)).fetchone()
                if row is None:
                    logger.warning(
                        "[DB] update_paper_trade_strategy_params: trade_id=%s not found",
                        trade_id[:8] if trade_id else "?",
                    )
                    return False
                existing = _from_json(row[0]) if row[0] else {}
                if not isinstance(existing, dict):
                    existing = {}
                existing.update(strategy_params)
                cur = conn.execute(sql_write, (_to_json(existing), trade_id))
                conn.commit()
                return cur.rowcount == 1
            finally:
                conn.close()

    def update_paper_trade_bracket_ids(
        self,
        trade_id: str,
        stop_order_id: Optional[str],
        target_order_id: Optional[str],
        bracket_status: Optional[str],
    ) -> bool:
        """
        Write bracket order IDs (migration_031 columns) onto an existing
        paper_trades row.

        Called by approval.service.approve_pending_trade after a bracket
        submission so the stop/target order IDs are queryable directly from
        the trade row rather than requiring JSON deserialisation of
        strategy_params.

        Returns True when exactly one row was updated.  No-ops gracefully
        (returns False) when the trade_id is not found.
        """
        sql = """
            UPDATE paper_trades
               SET stop_order_id   = ?,
                   target_order_id = ?,
                   bracket_status  = ?
             WHERE trade_id = ?
        """
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(sql, (stop_order_id, target_order_id, bracket_status, trade_id))
                conn.commit()
                found = cur.rowcount == 1
                if not found:
                    logger.warning(
                        "[DB] update_paper_trade_bracket_ids: trade_id=%s not found",
                        trade_id[:8] if trade_id else "?",
                    )
                else:
                    logger.debug(
                        "[DB] update_paper_trade_bracket_ids: trade_id=%s "
                        "stop=%s target=%s status=%s",
                        trade_id[:8],
                        stop_order_id,
                        target_order_id,
                        bracket_status,
                    )
                return found
            finally:
                conn.close()

    def update_paper_trade_stop_loss(self, trade_id: str, stop_loss: float) -> bool:
        """
        Write a resolved stop_loss price onto an existing paper_trades row.

        Backfill for the "naked row" gap: some open_trade() call sites resolve
        a real stop only after the row is opened (e.g. main._monitor_open_stops()
        resolving OMSManager.resolve_stop_for_symbol() as a read-time fallback,
        or a broker-position reconcile discovering IB's own resting stop order).
        This method lets those paths persist the resolved value once, so
        subsequent reads (dashboard, other monitors) see the real number
        instead of NULL.

        Same inverted-stop guard as insert_paper_trade: this is a second write
        path onto the same safety-critical column, so it must not become a
        backdoor for persisting a backwards stop (see
        docs/incident-notes/2026-04-09-mcl-inverted-stop.md).

        Returns True when exactly one row was updated.  No-ops gracefully
        (returns False) when the trade_id is not found.

        Raises:
            ValueError: If ``stop_loss`` is on the wrong side of the row's
                        existing ``entry_price`` for its ``side`` (inverted-stop
                        guard).
        """
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT side, entry_price FROM paper_trades WHERE trade_id = ?",
                    (trade_id,),
                ).fetchone()
                if row is None:
                    logger.warning(
                        "[DB] update_paper_trade_stop_loss: trade_id=%s not found",
                        trade_id[:8] if trade_id else "?",
                    )
                    return False
                side, entry_price = row[0], row[1]

                if is_inverted_stop(side, entry_price, stop_loss):
                    raise ValueError(
                        f"Refusing to update inverted stop: trade_id={trade_id[:8]} "
                        f"side={side} entry_price={entry_price} stop_loss={stop_loss}. "
                        "See docs/incident-notes/2026-04-09-mcl-inverted-stop.md"
                    )

                cur = conn.execute(
                    "UPDATE paper_trades SET stop_loss = ? WHERE trade_id = ?",
                    (stop_loss, trade_id),
                )
                conn.commit()
                found = cur.rowcount == 1
                logger.debug(
                    "[DB] update_paper_trade_stop_loss: trade_id=%s stop_loss=%s",
                    trade_id[:8],
                    stop_loss,
                )
                return found
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
