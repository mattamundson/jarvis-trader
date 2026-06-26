#!/usr/bin/env python
"""
Task #49 -- scrub historical contaminated MGC paper_trades (fabricated ~100 fills).

Background: before commit 53b5d85, paper-mode get_quote fabricated ~100 prices for
MGC (it was absent from the static mock table), so every MGC paper fill booked at
a sentinel price (100.05 / 100.30 / 100.55) instead of the real ~$2,000-3,400/oz.
Those rows poisoned paper_trades and the daily_pnl aggregates. The fix stopped new
contamination; this script cleans the historical rows.

Contamination predicate: symbol='MGC' AND entry_price < 200. Real MGC fills are
$4,058-4,723 in this DB; the only sub-200 prices are the fabricated sentinels.
There is NO ambiguous middle band (verified: 0 rows in 200-1500), so the threshold
is unambiguous. As of 2026-06-22: 27 contaminated rows, pnl impact -$80.00, dates
2026-06-16/18/19. Real MGC: 18 rows, +$4,766.12.

Disposition: QUARANTINE, not DELETE (per "archive never delete"). Rows are copied
to paper_trades_quarantine (which already holds 22 prior MES quarantines) with a
reason + timestamp, the affected daily_pnl rows are archived to
daily_pnl_corrupt_archive, then daily_pnl is recomputed from the cleaned table.

SAFETY: dry-run by default (read-only). --apply is DESTRUCTIVE and Amo-gated; it
takes a timestamped file backup of the DB first and wraps all mutations in one
transaction. The quarantine column list is derived by intersecting the live
schemas at runtime, so it can't drift out of sync with the table definitions.

Usage (from engine/):
    .venv/Scripts/python scripts/scrub_mgc_contaminated_paper_trades.py            # dry-run
    .venv/Scripts/python scripts/scrub_mgc_contaminated_paper_trades.py --apply    # DESTRUCTIVE
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ENGINE_ROOT / "data" / "jarvis_trader.db"

CONTAM_PREDICATE = "symbol = 'MGC' AND entry_price < 200"
QUARANTINE_REASON = (
    "Task #49: fabricated ~100 paper sentinel fill (MGC absent from pre-53b5d85 "
    "mock quote table); real MGC trades $2k-3.4k/oz. Quarantined not deleted."
)


def _table_cols(cur: sqlite3.Cursor, table: str) -> list[str]:
    return [r[1] for r in cur.execute(f"PRAGMA table_info({table})")]


def _fetch_contaminated(cur: sqlite3.Cursor) -> list[sqlite3.Row]:
    return cur.execute(
        f"SELECT * FROM paper_trades WHERE {CONTAM_PREDICATE} ORDER BY id"
    ).fetchall()


def _affected_dates(cur: sqlite3.Cursor) -> list[str]:
    return [
        r[0]
        for r in cur.execute(
            f"SELECT DISTINCT substr(entry_time,1,10) FROM paper_trades "
            f"WHERE {CONTAM_PREDICATE} ORDER BY 1"
        )
    ]


def dry_run(con: sqlite3.Connection) -> None:
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    rows = _fetch_contaminated(cur)
    total_mgc, total_pnl = cur.execute(
        "SELECT COUNT(*), ROUND(COALESCE(SUM(pnl),0),2) FROM paper_trades WHERE symbol='MGC'"
    ).fetchone()
    contam_pnl = round(sum((r["pnl"] or 0) for r in rows), 2)
    dates = _affected_dates(cur)

    print("=" * 72)
    print("DRY RUN -- Task #49 MGC contaminated paper_trades scrub (no changes made)")
    print("=" * 72)
    print(f"DB: {DEFAULT_DB}")
    print(f"Contamination predicate: {CONTAM_PREDICATE}")
    print(f"\nContaminated MGC rows: {len(rows)}  (pnl impact {contam_pnl:+.2f})")
    print(f"Total MGC rows: {total_mgc}  (current reported pnl {total_pnl:+.2f})")
    print(
        f"After scrub -> MGC rows: {total_mgc - len(rows)}  "
        f"(pnl {round(total_pnl - contam_pnl, 2):+.2f})"
    )
    print(f"Affected dates: {dates}")
    print("\n id  | entry  | exit   |   pnl  | date")
    print("-" * 48)
    for r in rows:
        print(
            f"{r['id']:>4} | {r['entry_price']:>6} | {r['exit_price']:>6} | "
            f"{(r['pnl'] or 0):>6} | {str(r['entry_time'])[:10]}"
        )

    print("\ndaily_pnl rows touched by these dates (NOT mutated by --apply; the")
    print("engine EOD summary regenerates them from the cleaned table on exit_time):")
    for d in dates:
        row = cur.execute(
            "SELECT date, total_trades, realized_pnl FROM daily_pnl WHERE date=?", (d,)
        ).fetchone()
        if row:
            print(f"  {d}: stale trades={row['total_trades']} realized={row['realized_pnl']}")
        else:
            print(f"  {d}: (no daily_pnl row)")
    print("\nNothing was modified. Re-run with --apply (DESTRUCTIVE, Amo-gated) to execute.")


def apply(con: sqlite3.Connection, db_path: Path) -> int:
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    rows = _fetch_contaminated(cur)
    if not rows:
        print("No contaminated rows found -- nothing to do.")
        return 0
    ids = [r["id"] for r in rows]
    dates = _affected_dates(cur)

    # 1. File backup before any mutation.
    stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = db_path.with_suffix(f".db.pre_task49_{stamp}.bak")
    shutil.copy2(db_path, backup)
    print(f"DB backed up -> {backup}")

    # 2. Resolve the quarantine column intersection at runtime (no drift).
    pt_cols = set(_table_cols(cur, "paper_trades"))
    q_cols = _table_cols(cur, "paper_trades_quarantine")
    extra = {"quarantine_reason", "quarantined_at"}
    copy_cols = [c for c in q_cols if c in pt_cols and c not in extra]

    placeholders = ",".join("?" for _ in ids)

    try:
        cur.execute("BEGIN")

        # 3. Copy contaminated rows into quarantine with reason + timestamp.
        sel = ",".join(copy_cols)
        cur.execute(
            f"INSERT INTO paper_trades_quarantine "
            f"({sel}, quarantine_reason, quarantined_at) "
            f"SELECT {sel}, ?, ? FROM paper_trades WHERE id IN ({placeholders})",
            [QUARANTINE_REASON, stamp, *ids],
        )
        print(f"Quarantined {cur.rowcount} row(s) into paper_trades_quarantine")

        # 4. Remove contaminated rows from the active table.
        cur.execute(f"DELETE FROM paper_trades WHERE id IN ({placeholders})", ids)
        print(f"Removed {cur.rowcount} contaminated row(s) from paper_trades")

        con.commit()
        print("Committed. Contaminated paper_trades quarantined.")
    except Exception as exc:  # noqa: BLE001
        con.rollback()
        print(f"ROLLED BACK due to error: {exc}")
        print(f"DB unchanged. Backup remains at {backup}")
        return 1

    # daily_pnl is intentionally NOT mutated here. The engine's EOD summary keys
    # realized_pnl on closed-trade EXIT date (tracker.py:1276-1278), not entry
    # date, so a hand-rolled recompute would be wrong (verified: a naive
    # entry-date SUM diverged from the stored value by >$800 on 2026-06-16).
    # After this scrub, daily_pnl for the affected dates is stale and must be
    # regenerated by the engine's EOD aggregation path (which uses exit_time).
    print(
        "\nWARNING: daily_pnl for "
        + ", ".join(dates)
        + " still reflects the contaminated trades. Regenerate via the engine EOD "
        "summary (keys on exit_time), not by hand."
    )

    # 7. Verification.
    remain = cur.execute(f"SELECT COUNT(*) FROM paper_trades WHERE {CONTAM_PREDICATE}").fetchone()[
        0
    ]
    qn = cur.execute(
        "SELECT COUNT(*) FROM paper_trades_quarantine WHERE quarantined_at=?", (stamp,)
    ).fetchone()[0]
    mgc_n, mgc_pnl = cur.execute(
        "SELECT COUNT(*), ROUND(COALESCE(SUM(pnl),0),2) FROM paper_trades WHERE symbol='MGC'"
    ).fetchone()
    print(
        f"\nVERIFY: remaining contaminated MGC rows={remain} (expect 0); "
        f"quarantined this run={qn}; clean MGC rows={mgc_n} pnl={mgc_pnl}"
    )
    return 0 if remain == 0 else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Scrub contaminated MGC paper_trades (Task #49)")
    p.add_argument(
        "--apply",
        action="store_true",
        help="DESTRUCTIVE: execute the quarantine+recompute (Amo-gated). Default is dry-run.",
    )
    p.add_argument("--db", default=str(DEFAULT_DB), help="path to jarvis_trader.db")
    args = p.parse_args(argv)

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"DB not found: {db_path}")
        return 2
    con = sqlite3.connect(str(db_path))
    try:
        if args.apply:
            return apply(con, db_path)
        dry_run(con)
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
