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

    # Write-time plausibility guard (2026-06-12). The daily_pnl table was
    # corrupted by writers with mismatched balance bases (a $10k-anchored
    # writer vs a ~$50k monitor-state writer), producing phantom ±$40k
    # "realized" days and stale rows where ending != starting + realized.
    # A refused snapshot is recoverable (rewritten next run / backfilled);
    # a poisoned row chains into every later row via starting-balance
    # lookups, so refusing is the fail-safe direction.

    # No strategy in paper validation risks more than a few percent per day;
    # a single-day realized move beyond half the book is a basis flip or
    # contaminated mark, not trading.
    MAX_DAILY_REALIZED_FRACTION = 0.5
    # ending must equal starting + realized (values arrive rounded to 4dp).
    BALANCE_IDENTITY_TOLERANCE = 0.01

    def _daily_pnl_rejection(
        self,
        starting_balance: float,
        ending_balance: float,
        realized_pnl: float,
    ) -> Optional[str]:
        """Return a rejection reason for an implausible snapshot, or None."""
        if starting_balance <= 0 or ending_balance <= 0:
            return (
                f"non-positive balance (starting={starting_balance}, "
                f"ending={ending_balance})"
            )
        if abs(realized_pnl) > self.MAX_DAILY_REALIZED_FRACTION * starting_balance:
            return (
                f"|realized_pnl|={abs(realized_pnl):.2f} exceeds "
                f"{self.MAX_DAILY_REALIZED_FRACTION:.0%} of starting balance "
                f"{starting_balance:.2f} — basis flip or contaminated mark"
            )
        if abs((starting_balance + realized_pnl) - ending_balance) > self.BALANCE_IDENTITY_TOLERANCE:
            return (
                f"balance identity violated: starting {starting_balance:.2f} "
                f"+ realized {realized_pnl:.2f} != ending {ending_balance:.2f}"
            )
        return None

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
    ) -> bool:
        """
        Insert or replace the P&L snapshot for the given date (YYYY-MM-DD).

        Uses INSERT OR REPLACE so repeated end-of-day snapshots overwrite
        the previous row for the same date.

        Implausible snapshots (basis flips, balance-identity violations) are
        REFUSED and logged instead of written — returns False in that case,
        True when the row was persisted.
        """
        reason = self._daily_pnl_rejection(starting_balance, ending_balance, realized_pnl)
        if reason:
            logger.error(
                "[DB] upsert_daily_pnl REFUSED for %s — %s "
                "(start=%.2f end=%.2f realized=%+.2f trades=%d)",
                date, reason, starting_balance, ending_balance,
                realized_pnl, total_trades,
            )
            return False

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
        return True

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
        realized_peak_equity: Optional[float] = None,
    ) -> None:
        """
        Insert or replace the intraday P&L snapshot for the given date.

        Called by SafetyLayer every time daily_pnl updates so state
        survives engine restarts mid-session.

        Parameters
        ----------
        date:
            YYYY-MM-DD date string.
        daily_pnl:
            Realized P&L for the current trading day.
        portfolio_equity:
            Current total equity including unrealized MTM on open positions.
            Used by the kill-switch drawdown halt — DO NOT conflate with
            realized_peak_equity.
        peak_equity:
            Running maximum of portfolio_equity (MTM).  The safety layer
            kill switch reads this column for the -10% drawdown halt.
            MUST remain unchanged and match SafetyLayer._equity_peak.
        consecutive_losses:
            Count of consecutive losing trades for the loss-streak halt.
        realized_peak_equity:
            Running maximum of equity computed from CLOSED trades only
            (excludes unrealized MTM).  Used exclusively by Phase 3 C5
            readiness criterion.  When None, the column is not updated
            (legacy callers that do not supply this value are safe).
        """
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

        if realized_peak_equity is not None:
            # migration_029 column is available — write it explicitly
            sql = """
                INSERT OR REPLACE INTO pnl_snapshots
                    (date, daily_pnl, portfolio_equity, peak_equity,
                     consecutive_losses, updated_at, realized_peak_equity)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """
            params = (
                date,
                daily_pnl,
                portfolio_equity,
                peak_equity,
                consecutive_losses,
                now_utc,
                realized_peak_equity,
            )
        else:
            # Legacy path: realized_peak_equity column not supplied.
            # Use ON CONFLICT DO UPDATE (not INSERT OR REPLACE) so the existing
            # realized_peak_equity value is preserved rather than being reset to
            # NULL by the implicit DELETE that INSERT OR REPLACE performs.
            sql = """
                INSERT INTO pnl_snapshots
                    (date, daily_pnl, portfolio_equity, peak_equity, consecutive_losses, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    daily_pnl          = excluded.daily_pnl,
                    portfolio_equity   = excluded.portfolio_equity,
                    peak_equity        = excluded.peak_equity,
                    consecutive_losses = excluded.consecutive_losses,
                    updated_at         = excluded.updated_at
            """
            params = (date, daily_pnl, portfolio_equity, peak_equity, consecutive_losses, now_utc)

        with self._lock:
            conn = self._connect()
            try:
                conn.execute(sql, params)
                conn.commit()
                logger.debug(
                    "[DB] upsert_pnl_snapshot date=%s daily_pnl=%+.2f equity=%.2f "
                    "realized_peak=%s",
                    date,
                    daily_pnl,
                    portfolio_equity,
                    f"{realized_peak_equity:.2f}" if realized_peak_equity is not None else "n/a",
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
