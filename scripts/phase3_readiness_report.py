#!/usr/bin/env python
"""
Phase 3 live-trading readiness report — CLI tool.

Usage:
    engine/.venv/Scripts/python scripts/phase3_readiness_report.py
    engine/.venv/Scripts/python scripts/phase3_readiness_report.py --db engine/data/jarvis_trader.db

Exit codes:
    0 — GO       (all blockers pass, <= 1 warning fails)
    1 — WAIT     (all blockers pass, > 1 warning fails)
    2 — NO-GO    (any blocker fails)

Run from the jarvis-trader project root.
"""

from __future__ import annotations

import argparse
import os
import sys

# Allow running from project root with engine/ on the path.
# scripts/ lives one level below repo root; engine/ is a sibling of scripts/.
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPTS_DIR)
_ENGINE_DIR = os.path.join(_REPO_ROOT, "engine")
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)

_DEFAULT_DB = os.path.join(_ENGINE_DIR, "data", "jarvis_trader.db")

_EXIT_CODE = {"GO": 0, "WAIT": 1, "NO-GO": 2}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Print the Phase 3 live-trading readiness report.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--db",
        default=_DEFAULT_DB,
        help=f"Path to jarvis_trader.db (default: {_DEFAULT_DB})",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON instead of Markdown",
    )
    args = parser.parse_args()

    db_path = os.path.abspath(args.db)
    if not os.path.exists(db_path):
        print(f"ERROR: database not found: {db_path}", file=sys.stderr)
        return 2

    from readiness.phase3_criteria import _render_markdown, evaluate_with_edge_mode

    # mode=None -> honors READINESS_EDGE_MODE (default paper_accrual, byte-identical
    # to the legacy evaluate_all_criteria plus an edge_mode key). GO/WAIT/NO-GO exit
    # codes are unchanged.
    report = evaluate_with_edge_mode(db_path)

    if args.json:
        import json

        print(json.dumps(report, indent=2))
    else:
        print(_render_markdown(report))

    overall = report["summary"]["overall"]
    return _EXIT_CODE.get(overall, 2)


if __name__ == "__main__":
    sys.exit(main())
