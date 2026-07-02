"""Ad-hoc phantom-trade detector — flag-only (2026-07-02).

Scans the closed paper_trades ledger and prints the automatically-detected
suspicious trades (duplicate bookings, pnl/price inconsistency, contaminated
entries) so you have a fresh, evidence-tagged list to confirm-mark with
``mark_phantom_trades.py``. This script NEVER mutates a row — detection and
marking are deliberately separate steps (a human confirms before anything is
voided). The same detector runs automatically inside the 20:05 UTC EOD snapshot
(``schedulers/eod_scheduler.run_eod_snapshot`` → ``snapshot["suspects"]``).

Run from the engine directory:

    .venv/Scripts/python.exe scripts/detect_phantom_trades.py
    .venv/Scripts/python.exe scripts/detect_phantom_trades.py --date 2026-07-02
    .venv/Scripts/python.exe scripts/detect_phantom_trades.py --lookback 500 --json

Exit code is 0 when the scan runs (regardless of how many suspects it finds) —
finding suspects is the tool working, not an error.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_ENGINE_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)


def main() -> int:
    parser = argparse.ArgumentParser(description="Flag suspicious closed paper trades.")
    parser.add_argument("--date", default=None, help="scope to exit_time UTC date YYYY-MM-DD")
    parser.add_argument("--lookback", type=int, default=300, help="closed rows to scan")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a report")
    parser.add_argument("--ids", action="store_true", help="print only the suspect trade IDs")
    parser.add_argument(
        "--price-outlier",
        action="store_true",
        help="also run the same-day entry-outlier signal (opt-in; can finger the "
        "genuine trade on a thin day where stale entries are the majority — read "
        "each flag as 'inspect this day', not 'this row is the phantom')",
    )
    args = parser.parse_args()

    from analytics.phantom_detector import (
        detect_suspect_closed_trades,
        format_suspect_report,
    )
    from database.schema import DatabaseManager

    db = DatabaseManager()
    db.initialize()

    suspects = detect_suspect_closed_trades(
        db,
        on_date=args.date,
        lookback=args.lookback,
        enable_price_outlier=args.price_outlier,
    )

    if args.ids:
        print(" ".join(str(s.trade_id) for s in suspects))
    elif args.json:
        print(json.dumps([s.as_dict() for s in suspects], indent=2))
    else:
        print(format_suspect_report(suspects))
        if suspects:
            print(
                "\nReview these, then mark the confirmed ones phantom via "
                "scripts/mark_phantom_trades.py (nothing was mutated by this scan)."
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
