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
                f"non-positive balance (starting={starting_balance}, " f"ending={ending_balance})"
            )
        if abs(realized_pnl) > self.MAX_DAILY_REALIZED_FRACTION * starting_balance:
            return (
                f"|realized_pnl|={abs(realized_pnl):.2f} exceeds "
                f"{self.MAX_DAILY_REALIZED_FRACTION:.0%} of starting balance "
                f"{starting_balance:.2f} — basis flip or contaminated mark"
            )
        if (
            abs((starting_balance + realized_pnl) - ending_balance)
            > self.BALANCE_IDENTITY_TOLERANCE
        ):
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
                date,
                reason,
                starting_balance,
                ending_balance,
                realized_pnl,
                total_trades,
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

        Self-heals undercounted rows on read (GT-19, 2026-07-27):
        ``daily_pnl`` rows are write-time snapshots taken by
        ``run_eod_snapshot`` (20:05 UTC) and corrected by
        ``run_session_flatten`` (20:45 UTC) — but a trade that closes after
        both of those scheduler jobs ran (or on a day the engine was
        offline during either window) is silently excluded from the served
        row until some LATER scheduled job happens to rebuild the table.
        That is silent data loss on every read in between, not merely a
        display bug: a real closed trade (P&L, trade count) is simply
        missing from what the dashboard shows. Confirmed live case:
        2026-07-23's row served ``{realized_pnl: -208.7054, total_trades: 3}``
        for at least a day after a 4th trade (MGC +$18.50, closed
        2026-07-23T20:45:00.563999+00:00) was already committed to
        ``paper_trades``.

        This patches ONLY the specific failure mode: a date where the
        closed-trade ledger now has MORE trades than the stored row
        recorded (``_self_heal_undercounted_daily_pnl``). It intentionally
        does NOT run the broader ``reconcile_daily_pnl`` / full
        ``repair_daily_pnl`` rebuild on every read — that also deletes
        "orphan" rows (a stored date with no matching closed trade) and
        rewrites every date's balance chain, which is safe as a deliberate
        scheduled/manual operation but too broad a side effect to trigger
        implicitly from a GET request. Never raises — a heal failure here
        must not turn a read endpoint into a 500.
        """
        try:
            patched = self._self_heal_undercounted_daily_pnl()
            if patched:
                logger.warning(
                    "[DB] get_daily_pnl self-heal — patched %d undercounted row(s): %s",
                    len(patched),
                    ", ".join(patched),
                )
        except Exception as exc:
            logger.error("[DB] get_daily_pnl self-heal failed (serving as-is): %s", exc)

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

    def _self_heal_undercounted_daily_pnl(self) -> List[str]:
        """Patch ``daily_pnl`` rows strictly undercounted vs. the closed-trade ledger.

        Companion to ``reconcile_daily_pnl`` / ``repair_daily_pnl`` (2026-07-02,
        2026-07-09) — GT-19 (2026-07-27) narrows the same anchoring formula to a
        read-safe, additive-only patch: a date is touched ONLY when
        ``COUNT(closed paper_trades for that date) > stored daily_pnl.total_trades``,
        i.e. a trade genuinely closed after the snapshot was written and is
        missing from what's served. Unlike ``repair_daily_pnl`` this NEVER
        deletes an orphan row (a stored date with no closed trades — e.g. a
        manually-seeded or pre-ledger row) and never rewrites a date whose
        stored count already matches or exceeds the ledger, so it is safe to
        call unconditionally on every read.

        Uses ``INSERT OR REPLACE`` with the same absolute-anchoring formula as
        ``repair_daily_pnl``/``_collect_db_trade_metrics`` (initial_capital +
        cumulative closed P&L through that date) so a patched row's balances
        stay internally consistent; per that established precedent, patched
        rows' ``unrealized_pnl``/``max_drawdown`` are reset to 0 (reporting-only
        columns — nothing load-bearing reads them).

        Returns the list of patched dates (empty when nothing was undercounted).
        """
        try:
            from schedulers.eod_scheduler import (
                _DEFAULT_STARTING_BALANCE as initial_capital,
            )
        except Exception:
            initial_capital = 10_000.0

        recompute_sql = """
            SELECT date(exit_time) AS d,
                   COALESCE(SUM(pnl), 0.0) AS realized,
                   COUNT(*) AS n,
                   SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS wins,
                   SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) AS losses
            FROM paper_trades
            WHERE status = 'closed' AND exit_time IS NOT NULL
            GROUP BY date(exit_time)
            ORDER BY date(exit_time)
        """
        with self._lock:
            conn = self._connect()
            try:
                grouped = [r for r in conn.execute(recompute_sql).fetchall() if r["d"] is not None]
                stored_counts = {
                    r["date"]: int(r["total_trades"] or 0)
                    for r in conn.execute("SELECT date, total_trades FROM daily_pnl").fetchall()
                }

                if not any(int(r["n"]) > stored_counts.get(r["d"], 0) for r in grouped):
                    return []

                # Cumulative sum over the FULL ordered ledger (not just the
                # undercounted dates) so a patched row's starting/ending
                # balance stays anchored exactly like repair_daily_pnl.
                running = float(initial_capital)
                patched: List[str] = []
                for r in grouped:
                    start = round(running, 4)
                    realized = round(float(r["realized"]), 4)
                    end = round(start + realized, 4)
                    running = end

                    if int(r["n"]) <= stored_counts.get(r["d"], 0):
                        continue  # not undercounted — leave this row alone

                    conn.execute(
                        """
                        INSERT OR REPLACE INTO daily_pnl
                            (date, starting_balance, ending_balance, realized_pnl,
                             unrealized_pnl, total_trades, winning_trades,
                             losing_trades, max_drawdown)
                        VALUES (?, ?, ?, ?, 0.0, ?, ?, ?, 0.0)
                        """,
                        (
                            r["d"],
                            start,
                            end,
                            realized,
                            int(r["n"]),
                            int(r["wins"] or 0),
                            int(r["losses"] or 0),
                        ),
                    )
                    patched.append(r["d"])

                if patched:
                    conn.commit()
                return patched
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

    def reconcile_daily_pnl(self, *, epsilon: float = 0.01) -> Dict:
        """Recompute realized P&L from closed paper_trades and flag drift.

        Detective control for the phantom-P&L class (2026-06-15). The stored
        ``daily_pnl.realized_pnl`` is written by the EOD snapshot; this method
        independently re-derives realized P&L per UTC date directly from the
        source of truth — ``SUM(pnl)`` over ``status='closed'`` paper_trades —
        and reports any date where the stored figure disagrees with the
        recomputed figure by more than ``epsilon`` dollars.

        Returns a dict::

            {
              "ok": bool,                  # True when no drift beyond epsilon
              "epsilon": float,
              "checked_dates": int,
              "drift_count": int,
              "total_recomputed_realized": float,
              "total_stored_realized": float,
              "drifts": [                  # only dates that disagree
                 {"date", "stored_realized", "recomputed_realized",
                  "delta", "stored_trades", "recomputed_trades"}
              ],
            }
        """
        recompute_sql = """
            SELECT date(exit_time) AS d,
                   COALESCE(SUM(pnl), 0.0) AS realized,
                   COUNT(*) AS n
            FROM paper_trades
            WHERE status = 'closed' AND exit_time IS NOT NULL
            GROUP BY date(exit_time)
        """
        with self._lock:
            conn = self._connect()
            try:
                recomputed = {
                    r["d"]: {"realized": float(r["realized"]), "n": int(r["n"])}
                    for r in conn.execute(recompute_sql).fetchall()
                    if r["d"] is not None
                }
                stored_rows = conn.execute(
                    "SELECT date, realized_pnl, total_trades FROM daily_pnl"
                ).fetchall()
            finally:
                conn.close()

        stored = {
            r["date"]: {
                "realized": float(r["realized_pnl"] or 0.0),
                "n": int(r["total_trades"] or 0),
            }
            for r in stored_rows
        }

        drifts: List[Dict] = []
        for date in sorted(set(stored) | set(recomputed)):
            s = stored.get(date, {"realized": 0.0, "n": 0})
            c = recomputed.get(date, {"realized": 0.0, "n": 0})
            delta = s["realized"] - c["realized"]
            if abs(delta) > epsilon:
                drifts.append(
                    {
                        "date": date,
                        "stored_realized": round(s["realized"], 2),
                        "recomputed_realized": round(c["realized"], 2),
                        "delta": round(delta, 2),
                        "stored_trades": s["n"],
                        "recomputed_trades": c["n"],
                    }
                )

        total_recomputed = sum(v["realized"] for v in recomputed.values())
        total_stored = sum(v["realized"] for v in stored.values())
        return {
            "ok": len(drifts) == 0,
            "epsilon": epsilon,
            "checked_dates": len(set(stored) | set(recomputed)),
            "drift_count": len(drifts),
            "total_recomputed_realized": round(total_recomputed, 2),
            "total_stored_realized": round(total_stored, 2),
            "drifts": drifts,
        }

    def repair_daily_pnl(
        self,
        *,
        initial_capital: float = 10_000.0,
        dry_run: bool = True,
    ) -> Dict:
        """Corrective control (2026-07-02): rebuild daily_pnl from the closed ledger.

        Companion to ``reconcile_daily_pnl`` (detective). Recomputes every
        daily_pnl row by replaying ``status='closed'`` paper_trades
        chronologically from ``initial_capital``::

            starting[d] = ending[d-1]   (initial_capital for the first date)
            realized[d] = SUM(pnl) of trades closed that UTC date
            ending[d]   = starting[d] + realized[d]

        This is the SAME absolute-anchoring formula the live EOD writer uses
        (``schedulers.eod_scheduler._collect_db_trade_metrics``), so a repair
        stays consistent with future EOD snapshots and every rebuilt row
        satisfies the ``ending == starting + realized`` identity by
        construction. Phantom/cancelled rows (``status != 'closed'``) are
        excluded, so once a bad trade is reclassified (manual
        ``mark_phantom_trades.py``) this heals the historical drift the
        detective control flagged. Idempotent — a second run is a no-op.

        ``dry_run=True`` (default) computes the diff and writes NOTHING.
        ``dry_run=False`` clears the table and reinserts the authoritative rows,
        removing orphan dates (a stored row with no closed trades that day).

        Returns a summary dict::

            {"applied", "dry_run", "initial_capital", "rows_before",
             "rows_after", "rows_changed", "orphans_removed", "orphans",
             "total_realized", "final_ending", "changes": [ ... ]}
        """
        recompute_sql = """
            SELECT date(exit_time) AS d,
                   COALESCE(SUM(pnl), 0.0) AS realized,
                   COUNT(*) AS n,
                   SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS wins,
                   SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) AS losses
            FROM paper_trades
            WHERE status = 'closed' AND exit_time IS NOT NULL
            GROUP BY date(exit_time)
            ORDER BY date(exit_time)
        """
        with self._lock:
            conn = self._connect()
            try:
                grouped = [r for r in conn.execute(recompute_sql).fetchall() if r["d"] is not None]
                stored_rows = conn.execute(
                    "SELECT date, starting_balance, ending_balance, "
                    "realized_pnl, total_trades FROM daily_pnl"
                ).fetchall()

                rebuilt: List[Dict] = []
                running = float(initial_capital)
                for r in grouped:
                    start = round(running, 4)
                    realized = round(float(r["realized"]), 4)
                    end = round(start + realized, 4)
                    running = end
                    rebuilt.append(
                        {
                            "date": r["d"],
                            "starting_balance": start,
                            "ending_balance": end,
                            "realized_pnl": realized,
                            "unrealized_pnl": 0.0,
                            "total_trades": int(r["n"]),
                            "winning_trades": int(r["wins"] or 0),
                            "losing_trades": int(r["losses"] or 0),
                            "max_drawdown": 0.0,
                        }
                    )

                stored = {row["date"]: dict(row) for row in stored_rows}
                rebuilt_dates = {row["date"] for row in rebuilt}
                changes: List[Dict] = []
                for row in rebuilt:
                    o = stored.get(row["date"])
                    if (
                        o is None
                        or abs(float(o["ending_balance"]) - row["ending_balance"]) > 0.01
                        or abs(float(o["realized_pnl"] or 0.0) - row["realized_pnl"]) > 0.01
                        or int(o["total_trades"] or 0) != row["total_trades"]
                    ):
                        changes.append(
                            {
                                "date": row["date"],
                                "old_realized": round(float(o["realized_pnl"]), 2) if o else None,
                                "new_realized": round(row["realized_pnl"], 2),
                                "old_ending": round(float(o["ending_balance"]), 2) if o else None,
                                "new_ending": round(row["ending_balance"], 2),
                            }
                        )
                orphans = sorted(d for d in stored if d not in rebuilt_dates)

                summary: Dict = {
                    "applied": False,
                    "dry_run": dry_run,
                    "initial_capital": float(initial_capital),
                    "rows_before": len(stored),
                    "rows_after": len(rebuilt),
                    "rows_changed": len(changes),
                    "orphans_removed": len(orphans),
                    "orphans": orphans,
                    "total_realized": round(sum(row["realized_pnl"] for row in rebuilt), 4),
                    "final_ending": (
                        round(rebuilt[-1]["ending_balance"], 4)
                        if rebuilt
                        else round(float(initial_capital), 4)
                    ),
                    "changes": changes,
                }

                if not dry_run and (changes or orphans):
                    # Clean rebuild: clear then reinsert so orphan dates are removed.
                    conn.execute("DELETE FROM daily_pnl")
                    conn.executemany(
                        """
                        INSERT INTO daily_pnl
                            (date, starting_balance, ending_balance, realized_pnl,
                             unrealized_pnl, total_trades, winning_trades,
                             losing_trades, max_drawdown)
                        VALUES (:date, :starting_balance, :ending_balance,
                                :realized_pnl, :unrealized_pnl, :total_trades,
                                :winning_trades, :losing_trades, :max_drawdown)
                        """,
                        rebuilt,
                    )
                    conn.commit()
                    summary["applied"] = True
                    logger.info(
                        "[DB] repair_daily_pnl applied — rebuilt %d rows, %d changed, "
                        "%d orphans removed, final_ending=%.2f",
                        len(rebuilt),
                        len(changes),
                        len(orphans),
                        summary["final_ending"],
                    )
            finally:
                conn.close()
        return summary

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
