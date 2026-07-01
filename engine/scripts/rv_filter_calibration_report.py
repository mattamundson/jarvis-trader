"""Print the RV-filter calibration report (MGC/MES progress toward 60 live trades).

Wires ``analytics.rv_filter_calibration.status_from_db`` to the real
``DatabaseManager`` -- the report/counting logic was added report-only in #228
but had no runnable entry point. This script is the entry point.

Strictly read-only: opens the SQLite DB via the same ``DatabaseManager`` the
engine uses, counts closed trades per symbol, and prints progress toward the
documented 60-trade calibration threshold (engine/CLAUDE.md). Never writes to
the DB, never touches paper config, risk params, or the RV filter itself.
Enabling the filter remains a separate human gate-v2 / Tier-3 decision --
this script only tells you whether the data exists to make that decision.

Run (from engine/ directory; read-only, safe to run any time):
  cd engine && .venv/Scripts/python.exe scripts/rv_filter_calibration_report.py
  cd engine && .venv/Scripts/python.exe scripts/rv_filter_calibration_report.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analytics.rv_filter_calibration import format_report, status_from_db  # noqa: E402
from database.manager import DatabaseManager  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json", action="store_true", help="emit machine-readable JSON instead of the text report"
    )
    parser.add_argument(
        "--db-path",
        default="data/jarvis_trader.db",
        help="SQLite path (relative to engine/ unless absolute); default matches the live engine DB",
    )
    args = parser.parse_args()

    db = DatabaseManager(db_path=args.db_path)
    statuses = status_from_db(db)

    if args.json:
        print(json.dumps([s.as_dict() for s in statuses], indent=2))
    else:
        print(format_report(statuses))

    # Non-zero exit when nothing is ready yet, so this composes in a script/CI
    # check without needing to parse the text output.
    return 0 if any(s.ready for s in statuses) else 1


if __name__ == "__main__":
    raise SystemExit(main())
