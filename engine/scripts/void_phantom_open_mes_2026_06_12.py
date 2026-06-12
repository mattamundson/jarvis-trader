"""
JARVIS TRADER — Void the 2026-06-12 phantom OPEN MES position
=============================================================
One-shot remediation for a single corrupted OPEN paper position:

    id 206 | trade_id 7d5cf789-1d98-4363-b78d-9308e60e180b
    MES buy | entry_price=100.5 | status=open | 2026-06-12T05:34:39Z

entry_price=100.5 is an STC oscillator value (0-100) that leaked into the
price field; MES trades ~5,000-6,000. Root cause + the write-time gate that
prevents recurrence: PR #38 (scanner entry-price sanity gate). See
mark_phantom_trades.py for the closed-trade precedent (2026-05-22 incident).

Method mirrors mark_phantom_trades.py: we ARCHIVE, never DELETE — the row is
marked status='phantom' so it drops out of open-position views, reconciliation,
and readiness/P&L aggregates while staying fully recoverable. The plausible
open MGC position (id 201, entry 4083.4) is intentionally LEFT ALONE.

REQUIRED ORDER (do NOT run this first):
  1. Merge PR #38 (scanner entry-price gate) to master.
  2. Deploy master to the engine working copy.
  3. Run THIS script --execute (marks id 206 phantom). The in-memory paper
     tracker still holds it until the next restart — that is fine; the
     per-symbol dedup keeps a new MES out in the meantime.
  4. Restart the engine (restart_engine.ps1 — Amo-only). The restart reloads
     open positions from the DB with the phantom excluded (clean in-memory
     state) AND activates the entry-price gate so no new 100.5 can be written.
  5. Verify: GET /brokers/positions shows no MES@100.5; only id 201 MGC open.

No pnl_snapshots reset is needed: this position never closed (pnl is NULL), so
it contributed no realized-P&L row. Unrealized/aggregate displays recompute
from live open positions, which exclude it after the restart.

Usage
-----
  Dry-run (default — shows the row, NO changes):
    python scripts/void_phantom_open_mes_2026_06_12.py

  Execute (marks the one row status='phantom'):
    python scripts/void_phantom_open_mes_2026_06_12.py --execute
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

# ── Confirmed target (read-only DB query 2026-06-12) ──────────────────────────
TARGET_TRADE_ID = "7d5cf789-1d98-4363-b78d-9308e60e180b"
TARGET_ID = 206
TARGET_SYMBOL = "MES"
# Safety band: a real MES price is in the thousands. Only void if the stored
# entry_price is below this floor — guarantees we can never void a legitimate
# MES position even if the trade_id were somehow reused.
MES_SANE_PRICE_FLOOR = 1000.0
VOID_NOTE = " [voided 2026-06-12: phantom entry_price=100.5 — STC oscillator leaked into price field; see PR #38]"


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


def _load_target(conn: sqlite3.Connection) -> dict | None:
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT id, trade_id, symbol, side, entry_price, exit_price, pnl, status, "
        "entry_time, notes FROM paper_trades WHERE trade_id = ?",
        (TARGET_TRADE_ID,),
    ).fetchone()
    return dict(row) if row else None


def _print_row(label: str, r: dict | None) -> None:
    print(f"\n{label}:")
    if not r:
        print("  (no row matches the target trade_id — nothing to do)")
        return
    print(
        f"  id={r['id']} trade_id={r['trade_id']}\n"
        f"  {r['symbol']} {r['side']} entry={r['entry_price']} "
        f"exit={r['exit_price']} pnl={r['pnl']} status={r['status']}\n"
        f"  entry_time={r['entry_time']}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Void the 2026-06-12 phantom OPEN MES position (status='phantom')"
    )
    parser.add_argument(
        "--execute", action="store_true", help="Modify the DB (default: dry-run only)"
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
        before = _load_target(conn)
        _print_row("Target row (before)", before)

        if before is None:
            return 0

        # Hard guards — refuse to act on anything that isn't the confirmed phantom.
        problems = []
        if before["id"] != TARGET_ID:
            problems.append(f"id mismatch (got {before['id']}, expected {TARGET_ID})")
        if str(before["symbol"]).upper() != TARGET_SYMBOL:
            problems.append(f"symbol mismatch (got {before['symbol']})")
        if before["status"] != "open":
            problems.append(f"status is '{before['status']}', expected 'open'")
        if before["entry_price"] is None or float(before["entry_price"]) >= MES_SANE_PRICE_FLOOR:
            problems.append(
                f"entry_price={before['entry_price']} is not below the phantom "
                f"floor {MES_SANE_PRICE_FLOOR} — refusing (looks like a real price)"
            )
        if problems:
            print("\nABORT — target does not match the confirmed phantom:")
            for p in problems:
                print(f"  - {p}")
            return 2

        if not args.execute:
            print(
                "\n[DRY-RUN] Would set status='phantom' and append a void note on the "
                "row above. The MGC open position (id 201) is NOT touched. "
                "Re-run with --execute to apply. Reminder: merge PR #38 + restart "
                "the engine around this per the header runbook."
            )
            return 0

        conn.execute(
            "UPDATE paper_trades SET status='phantom', "
            "notes = COALESCE(notes,'') || ? "
            "WHERE trade_id = ? AND status='open' AND symbol = ? "
            "AND entry_price < ?",
            (VOID_NOTE, TARGET_TRADE_ID, TARGET_SYMBOL, MES_SANE_PRICE_FLOOR),
        )
        conn.commit()
        after = _load_target(conn)
        _print_row("Target row (after)", after)
        print(
            "\nDone. NEXT: restart the engine (restart_engine.ps1 — Amo-only) so the "
            "in-memory tracker reloads without this row and the entry-price gate goes "
            "live. Then verify GET /brokers/positions shows no MES@100.5."
        )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
