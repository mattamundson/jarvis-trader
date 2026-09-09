#!/usr/bin/env python
"""
RETIRED legacy Phase 3 evidence report — never authorizes live trading.

Usage:
    engine/.venv/Scripts/python scripts/phase3_readiness_report.py
    engine/.venv/Scripts/python scripts/phase3_readiness_report.py --db engine/data/jarvis_trader.db

Exit codes:
    2 — RETIRED / NO-GO (always)

The underlying legacy criteria remain visible as historical PAPER/readiness
observations, but this command can never authorize LIVE trading or return process
success for a historical computed GO. LIVE authority requires a separately
reviewed governing plan plus explicit human capital-owner authorization for the
exact bounded scope.

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

_RETIREMENT_REASON = (
    "Legacy Phase 3 readiness is evidence-only and cannot authorize live trading. "
    "A separately reviewed governing plan plus explicit human capital-owner "
    "authorization for the exact bounded scope is required."
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Print the retired legacy Phase 3 evidence report.",
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

    # Preserve the legacy calculation as historical evidence while forcing the
    # authorization result closed. A historical GO must never become a process-
    # success signal or capital authorization.
    report = evaluate_with_edge_mode(db_path)
    summary = report.setdefault("summary", {})
    summary["legacy_result"] = summary.get("overall")
    summary["overall"] = "NO-GO"
    summary["live_authorization"] = False
    summary["authorization_reason"] = _RETIREMENT_REASON

    if args.json:
        import json

        print(json.dumps(report, indent=2))
    else:
        print(f"RETIRED / NO-GO: {_RETIREMENT_REASON}")
        print()
        print(_render_markdown(report))

    return 2


if __name__ == "__main__":
    sys.exit(main())
