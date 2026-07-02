"""Rebuild the daily_pnl table from the closed paper_trades ledger (dry-run by default).

Run from the engine/ directory:  python scripts/repair_daily_pnl.py [--apply]

Ground truth = closed paper_trades ledger. Rebuilds each daily_pnl row by replaying
closed trades chronologically from INITIAL_CAPITAL ($10,000):
  starting[d] = ending[d-1]  (initial for the first date)
  realized[d] = SUM(pnl) of trades closed that UTC date
  ending[d]   = starting[d] + realized[d]
This enforces the balance identity the plausibility guard requires and makes the
final ending == true equity (initial + net closed P&L).

This is the same absolute-anchoring formula the live EOD writer uses
(schedulers/eod_scheduler.py::_collect_db_trade_metrics, 2026-06-12 corruption fix),
so a rebuild here stays consistent with what the scheduler writes on the next EOD run.
Re-run any time to re-sync history after phantom/duplicate trades are reclassified.

DRY-RUN prints the full diff and writes NOTHING. Pass --apply to write (GATED; requires
a DB backup first). unrealized_pnl set to 0 (closed-basis); max_drawdown left 0 (per-day
intraday DD not reconstructable from EOD closed rows without tick marks).

History: created 2026-07-02 to repair 06-12..07-01 drift (corrupt rows counted
cancelled_duplicate/cancelled_contaminated/phantom trades as real). See
~/.claude/projects/C--Users-mattm/memory/project_pnl_double_count_bug_2026_07_02.md.
"""

import argparse
import sqlite3
from pathlib import Path

INITIAL_CAPITAL = 10_000.0
DB = Path("data/jarvis_trader.db")  # run from engine/


def build_rows(conn):
    conn.row_factory = sqlite3.Row
    grp = conn.execute(
        """
        SELECT date(exit_time) d,
               COALESCE(SUM(pnl),0.0) realized,
               COUNT(*) n,
               SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) wins,
               SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) losses
        FROM paper_trades
        WHERE status='closed' AND exit_time IS NOT NULL
        GROUP BY date(exit_time) ORDER BY d
    """
    ).fetchall()
    rows = []
    running = INITIAL_CAPITAL
    for r in grp:
        start = round(running, 4)
        realized = round(float(r["realized"]), 4)
        end = round(start + realized, 4)
        running = end
        rows.append(
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
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="WRITE the rebuilt rows (gated)")
    args = ap.parse_args()

    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    new = build_rows(conn)
    old = {
        r["date"]: dict(r)
        for r in conn.execute(
            "SELECT date,starting_balance,ending_balance,realized_pnl,total_trades FROM daily_pnl"
        ).fetchall()
    }

    print(
        f"{'date':<12} {'OLD start->end':>22} {'OLD real':>10} {'OLD t':>5} | "
        f"{'NEW start->end':>22} {'NEW real':>10} {'NEW t':>5}  chg"
    )
    print("-" * 108)
    old_real_sum = new_real_sum = 0.0
    changed = 0
    for r in new:
        d = r["date"]
        o = old.get(d)
        new_real_sum += r["realized_pnl"]
        if o:
            old_real_sum += float(o["realized_pnl"] or 0)
            oi = f"{o['starting_balance']:>9.2f}->{o['ending_balance']:<9.2f}"
            ost = f"{float(o['realized_pnl'] or 0):+.2f}"
            ot = o["total_trades"]
            diff = (
                abs(float(o["ending_balance"]) - r["ending_balance"]) > 0.01
                or abs(float(o["realized_pnl"] or 0) - r["realized_pnl"]) > 0.01
                or int(o["total_trades"]) != r["total_trades"]
            )
        else:
            oi, ost, ot, diff = "(no row)", "-", "-", True
        if diff:
            changed += 1
        ni = f"{r['starting_balance']:>9.2f}->{r['ending_balance']:<9.2f}"
        print(
            f"{d:<12} {oi:>22} {ost:>10} {str(ot):>5} | "
            f"{ni:>22} {r['realized_pnl']:>+10.2f} {r['total_trades']:>5}  {'CHG' if diff else ''}"
        )

    # rows in old but not in rebuilt (dates with no closed trades but a snapshot row)
    orphan = [d for d in old if d not in {r["date"] for r in new}]

    print("-" * 108)
    print(
        f"rows: old={len(old)} new={len(new)} changed={changed} orphan_old_only={len(orphan)} {orphan}"
    )
    print(
        f"realized SUM: old_stored={old_real_sum:+.2f}  rebuilt={new_real_sum:+.2f}  (ground truth == ledger net closed P&L)"
    )
    print(
        f"final ending: old_last={list(old.values())[-1]['ending_balance'] if old else 'NA'}  "
        f"rebuilt={new[-1]['ending_balance']}  (true equity == initial + net closed P&L)"
    )

    if not args.apply:
        print("\nDRY-RUN: nothing written. Re-run with --apply (after a DB backup) to persist.")
        return
    # --- GATED WRITE PATH (not executed in dry-run) ---
    # Clean rebuild: clear the whole table first so orphan dates (snapshot rows with
    # no closed trades) are removed, then reinsert the authoritative rebuilt rows.
    print(
        f"\n[APPLY] DELETE FROM daily_pnl ({len(old)} rows) then insert {len(new)} rebuilt rows ..."
    )
    conn.execute("DELETE FROM daily_pnl")
    for r in new:
        conn.execute(
            """INSERT OR REPLACE INTO daily_pnl
            (date,starting_balance,ending_balance,realized_pnl,unrealized_pnl,
             total_trades,winning_trades,losing_trades,max_drawdown)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                r["date"],
                r["starting_balance"],
                r["ending_balance"],
                r["realized_pnl"],
                r["unrealized_pnl"],
                r["total_trades"],
                r["winning_trades"],
                r["losing_trades"],
                r["max_drawdown"],
            ),
        )
    conn.commit()
    print(f"[APPLY] wrote {len(new)} rows.")
    conn.close()


if __name__ == "__main__":
    main()
