"""Rebuild the corrupted daily_pnl table from closed paper_trades round-trips.

The 2026-06 corruption (basis-flipped writers; see test_daily_pnl_integrity.py)
left daily_pnl with phantom ±$40k days and stale arithmetic-inconsistent rows.
paper_trades holds the true round-trips, so the table is fully re-derivable.

What this does (single transaction, archive-first, reversible):
  1. Copies every existing daily_pnl row into daily_pnl_corrupt_archive
     (created if absent) with an archived_at stamp.
  2. Deletes all daily_pnl rows.
  3. Re-inserts one row per date that has closed trades, anchored to
     INITIAL_CAPITAL + cumulative closed P&L — the same arithmetic the
     fixed EODScheduler now writes, so every row satisfies the
     DailyPnLMixin write guard (ending == starting + realized).

Counts (winning/losing/total) are per-day round-trips. unrealized_pnl and
max_drawdown are set to 0 for rebuilt history (not recoverable per-day).

Run (Amo-gated — mutates the production DB):
  cd engine && .venv/Scripts/python.exe scripts/rebuild_daily_pnl.py [--dry-run]
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "jarvis_trader.db"
INITIAL_CAPITAL = 10_000.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="print plan, write nothing")
    args = parser.parse_args()

    con = sqlite3.connect(str(DB), timeout=30)
    con.row_factory = sqlite3.Row
    c = con.cursor()

    daily = c.execute(
        """
        SELECT date(substr(exit_time, 1, 10)) AS d,
               COUNT(*)                        AS n,
               SUM(pnl)                        AS pnl,
               SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS wins,
               SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) AS losses
        FROM paper_trades
        WHERE status = 'closed' AND exit_time IS NOT NULL
        GROUP BY 1 ORDER BY 1
        """
    ).fetchall()

    old_count = c.execute("SELECT COUNT(*) FROM daily_pnl").fetchone()[0]
    print(f"existing daily_pnl rows: {old_count}")
    print(f"rebuild source: {len(daily)} trading day(s) with closed round-trips")

    cum = 0.0
    plan = []
    for row in daily:
        starting = round(INITIAL_CAPITAL + cum, 4)
        cum += row["pnl"]
        ending = round(INITIAL_CAPITAL + cum, 4)
        plan.append(
            (
                row["d"], starting, ending, round(ending - starting, 4), 0.0,
                row["n"], row["wins"], row["losses"], 0.0,
            )
        )
        print(
            f"  {row['d']}: {row['n']} trade(s) "
            f"start={starting:.2f} end={ending:.2f} realized={ending - starting:+.2f}"
        )

    if args.dry_run:
        print("dry-run: no writes")
        con.close()
        return

    now = datetime.now(timezone.utc).isoformat()
    c.execute("BEGIN IMMEDIATE")
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS daily_pnl_corrupt_archive AS
        SELECT *, '' AS archived_at FROM daily_pnl WHERE 0
        """
    )
    c.execute(
        "INSERT INTO daily_pnl_corrupt_archive SELECT *, ? FROM daily_pnl", (now,)
    )
    archived = c.rowcount
    c.execute("DELETE FROM daily_pnl")
    c.executemany(
        """
        INSERT INTO daily_pnl
            (date, starting_balance, ending_balance, realized_pnl, unrealized_pnl,
             total_trades, winning_trades, losing_trades, max_drawdown)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        plan,
    )
    con.commit()

    print(f"archived {archived} corrupt row(s) -> daily_pnl_corrupt_archive")
    print(f"rebuilt {len(plan)} row(s) from paper_trades")
    final = c.execute(
        "SELECT date, starting_balance, ending_balance, realized_pnl FROM daily_pnl ORDER BY date"
    ).fetchall()
    for r in final:
        ok = abs((r["starting_balance"] + r["realized_pnl"]) - r["ending_balance"]) < 0.01
        assert ok, f"identity violated in rebuilt row {dict(r)}"
    print("balance identity verified on every rebuilt row")
    con.close()


if __name__ == "__main__":
    main()
