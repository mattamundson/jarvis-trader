"""
Decision-log audit-chain verifier
==================================
Standalone integrity check for the tamper-evident decision log.

Recomputes the SHA-256 hash chain over every hashed ``pending_trade_approvals``
row (see engine/approval/audit_chain.py) and reports whether any decision
snapshot has been mutated, reordered, deleted, or had its hash forged. Also
prints the Merkle root — a single value that pins the whole hashed history.

Usage (from engine/):
    python -m tools.verify_decision_chain [--db PATH] [--day YYYY-MM-DD]

Exit code 0 when the chain is intact, 1 when a break is found (suitable for a
CI/cron integrity gate). Read-only — never writes to the database.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running as a bare script (python tools/verify_decision_chain.py) by
# putting the engine root on sys.path, mirroring the test bootstrap pattern.
_engine_root = Path(__file__).resolve().parent.parent
if str(_engine_root) not in sys.path:
    sys.path.insert(0, str(_engine_root))

from database.manager import DatabaseManager  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the decision-log audit chain.")
    parser.add_argument(
        "--db",
        default=None,
        help="Path to the SQLite DB (defaults to DatabaseManager's default path).",
    )
    parser.add_argument(
        "--day",
        default=None,
        help="Optional YYYY-MM-DD UTC date to scope the Merkle root.",
    )
    args = parser.parse_args(argv)

    db = DatabaseManager(db_path=args.db) if args.db else DatabaseManager()

    result = db.verify_decision_audit_chain()
    root = db.decision_merkle_root(day=args.day)

    print(f"records:      {result['n_records']}")
    print(f"merkle_root:  {root}")
    if result["ok"]:
        print("status:       OK — decision-log audit chain is intact.")
        return 0

    print("status:       BROKEN — tampering detected.")
    print(f"broken_index: {result['broken_index']}")
    print(f"approval_id:  {result['broken_approval_id']}")
    print(f"reason:       {result['reason']}")
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
