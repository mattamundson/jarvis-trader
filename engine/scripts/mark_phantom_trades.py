"""
JARVIS TRADER — Phantom Trade Data Remediation
===============================================
Mark paper_trades rows as status='phantom' so Phase 3 readiness metrics
(C2 trade count, C3 win rate, C5 drawdown, C7 loss streak) compute against
real trades only.

Phantom trades were caused by two bugs:
  1. stop_loss value copied into entry_price field (MES at 7384-7498 instead of ~5600)
  2. Exit prices frozen at stale values from prior runs

Confirmed phantom trade IDs and dates (from DB investigation 2026-05-22):
  IDs 145-150  (2026-05-08): MES at 7384.75, MGC at 4705
  IDs 152-157  (2026-05-09): MES at 7398.5481 (incident report confirmed)
  IDs 158-167  (2026-05-22): MES at 7498.00, MGC at 4525-4526

Usage
-----
  Dry-run (shows what would change, does NOT modify DB):
    python scripts/mark_phantom_trades.py

  Execute (marks trades + optionally resets pnl_snapshots):
    python scripts/mark_phantom_trades.py --execute
    python scripts/mark_phantom_trades.py --execute --reset-pnl-snapshots

IMPORTANT: Run this ONLY after the engine has been restarted with commits:
  841800a — VALIDATION_ONLY_STRATEGIES gate (prevents new phantom trades)
  e10cad3 — entry-price sanity check (rejects corrupted prices at submission)

Without restarting, the engine will keep generating new phantom trades.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

# ── Configuration ─────────────────────────────────────────────────────────────

# Confirmed phantom trade IDs from DB investigation 2026-05-22
# Each entry: (id, reason)
PHANTOM_TRADE_IDS: list[tuple[int, str]] = [
    (145, "MES sell entry_price=7384.75 (real market ~5600); stop_loss=7398.5481 in notes"),
    (146, "MES sell entry_price=7384.75 pnl=4982.50 (MES moved ~1000pts — impossible)"),
    (147, "MES sell entry_price=7384.75 pnl=4982.50 — duplicate of #146"),
    (148, "MGC sell entry_price=4705 alongside confirmed phantom MES trades 2026-05-08"),
    (149, "MES sell entry_price=7384.75 pnl=4982.50 — third duplicate"),
    (150, "MGC sell entry_price=4705 alongside confirmed phantom MES trades 2026-05-08"),
    (152, "MES sell entry_price=7398.5481 — incident report 2026-05-09 confirmed phantom"),
    (153, "MES sell entry_price=7398.5481 — same idempotency_key as #152 with -153 suffix"),
    (154, "MES sell entry_price=7398.5481 — incident report phantom (6 entries)"),
    (155, "MES sell entry_price=7398.5481 — incident report phantom (6 entries)"),
    (156, "MES sell entry_price=7398.5481 — incident report phantom (6 entries)"),
    (157, "MES sell entry_price=7398.5481 — incident report phantom (6 entries)"),
    (158, "MGC buy entry_price=4526.00 2026-05-22; alongside confirmed phantom MES"),
    (159, "MGC buy entry_price=4525.90 2026-05-22; alongside confirmed phantom MES"),
    (160, "MGC buy entry_price=4525.90 2026-05-22; duplicate of #159"),
    (161, "MGC buy entry_price=4517.30 2026-05-22; alongside confirmed phantom MES"),
    (162, "MES buy entry_price=7498.00 2026-05-22; real market ~5600; clearly corrupted"),
    (163, "MES buy entry_price=7498.00 2026-05-22; duplicate"),
    (164, "MES buy entry_price=7498.00 2026-05-22; duplicate"),
    (165, "MES buy entry_price=7498.00 2026-05-22; duplicate"),
    (166, "MES buy entry_price=7498.00 2026-05-22; duplicate"),
    (167, "MES buy entry_price=7498.00 2026-05-22; duplicate"),
]

# pnl_snapshots dates to reset (dates when phantom trades were recorded)
PHANTOM_SNAPSHOT_DATES = [
    "2026-05-08",
    "2026-05-09",
    "2026-05-10",
    "2026-05-11",
    "2026-05-12",
    "2026-05-13",
    "2026-05-14",
    "2026-05-19",
    "2026-05-20",
    "2026-05-21",
    "2026-05-22",
]

# ── Helpers ────────────────────────────────────────────────────────────────────


def _find_db() -> Path:
    here = Path(__file__).parent.parent  # engine/
    candidates = [
        here / "data" / "jarvis_trader.db",
        here.parent / "data" / "jarvis_trader.db",
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(f"jarvis_trader.db not found. Tried: {candidates}")


def _load_current_state(conn: sqlite3.Connection) -> list[dict]:
    conn.row_factory = sqlite3.Row
    ids = [t[0] for t in PHANTOM_TRADE_IDS]
    placeholders = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT id, symbol, side, entry_price, exit_price, pnl, status, entry_time "
        f"FROM paper_trades WHERE id IN ({placeholders})",
        ids,
    ).fetchall()
    return [dict(r) for r in rows]


def _print_dry_run(current: list[dict]) -> None:
    print("\n[DRY-RUN] Phantom trades to be marked (no changes made):")
    print(
        f"{'ID':>6}  {'Symbol':>6}  {'Side':>5}  {'Entry':>10}  {'PnL':>10}  {'Status':>10}  {'Date':>12}"
    )
    print("-" * 75)
    total_pnl = 0.0
    for tid, reason in PHANTOM_TRADE_IDS:
        matching = [r for r in current if r["id"] == tid]
        if matching:
            r = matching[0]
            date = r["entry_time"][:10] if r["entry_time"] else "?"
            pnl = float(r["pnl"] or 0)
            total_pnl += pnl
            print(
                f"{r['id']:>6}  {r['symbol']:>6}  {r['side']:>5}  "
                f"{float(r['entry_price']):>10.2f}  {pnl:>10.2f}  "
                f"{r['status']:>10}  {date:>12}"
            )
        else:
            print(f"{tid:>6}  {'(not found)':>50}  Reason: {reason[:40]}")

    print("-" * 75)
    print(f"Total phantom P&L impact: ${total_pnl:+,.2f}")
    print(f"\nRun with --execute to mark these {len(PHANTOM_TRADE_IDS)} trades as 'phantom'.")
    print("Run with --execute --reset-pnl-snapshots to also clear affected pnl_snapshots rows.")


def _execute_marking(conn: sqlite3.Connection, dry_run: bool = True) -> int:
    ids = [t[0] for t in PHANTOM_TRADE_IDS]
    if dry_run:
        return len(ids)
    placeholders = ",".join("?" * len(ids))
    cursor = conn.execute(
        f"UPDATE paper_trades SET status = 'phantom' WHERE id IN ({placeholders}) AND status = 'closed'",
        ids,
    )
    return cursor.rowcount


def _execute_pnl_reset(conn: sqlite3.Connection, dry_run: bool = True) -> int:
    if dry_run:
        return len(PHANTOM_SNAPSHOT_DATES)
    placeholders = ",".join("?" * len(PHANTOM_SNAPSHOT_DATES))
    cursor = conn.execute(
        f"DELETE FROM pnl_snapshots WHERE date IN ({placeholders})",
        PHANTOM_SNAPSHOT_DATES,
    )
    return cursor.rowcount


# ── Main ───────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description="Mark phantom paper_trades as status='phantom'")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually modify the DB (default: dry-run only)",
    )
    parser.add_argument(
        "--reset-pnl-snapshots",
        action="store_true",
        help="Also DELETE pnl_snapshots rows for phantom dates so the engine recalculates them",
    )
    args = parser.parse_args()

    try:
        db_path = _find_db()
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"DB: {db_path}")
    print(f"Mode: {'EXECUTE' if args.execute else 'DRY-RUN'}")

    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row

    try:
        current = _load_current_state(conn)

        if not args.execute:
            _print_dry_run(current)
            if args.reset_pnl_snapshots:
                print(f"\n[DRY-RUN] Would DELETE {len(PHANTOM_SNAPSHOT_DATES)} pnl_snapshot rows:")
                for d in PHANTOM_SNAPSHOT_DATES:
                    print(f"  {d}")
            return 0

        # ── Execute mode ───────────────────────────────────────────────────────
        print(f"\nMarking {len(PHANTOM_TRADE_IDS)} trades as status='phantom'...")
        marked = _execute_marking(conn, dry_run=False)
        conn.commit()
        print(f"  Marked {marked} trades.")

        if args.reset_pnl_snapshots:
            print(f"\nDeleting {len(PHANTOM_SNAPSHOT_DATES)} pnl_snapshot rows...")
            deleted = _execute_pnl_reset(conn, dry_run=False)
            conn.commit()
            print(f"  Deleted {deleted} snapshot rows.")
            print(
                "  NOTE: pnl_snapshots will be rebuilt by the engine on the next snapshot update.\n"
                "  The realized_peak_equity will reset to the legitimate P&L baseline.\n"
                "  Restart the engine FIRST to activate the entry-price sanity check.\n"
                "  Phase 3 C5 (max_drawdown) should then recalculate correctly."
            )

        print("\nRemediation complete. Verify with:")
        print("  GET http://127.0.0.1:8010/readiness/phase3")
        return 0

    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
