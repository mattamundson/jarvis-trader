#!/usr/bin/env python
"""Read-only bar-quality audit of STORED bars (false-positive / contamination check).

Runs the write-time gate's pure ``screen_bars`` over every ``market_data_bars``
group already in the database, grouped by (symbol, interval) exactly as the
write path screens each batch. Reports rejects by reason and proves whether the
*traded futures* the strategies actually backtest on are contamination-free.

This is the read-side companion to ``data/bar_quality_gate.py`` (the write-time
guard). The gate is forward-only — it screens rows *before* insert — so this
audit is how you verify the rows ALREADY stored (and therefore the data every
gate-v2 verdict was computed on) carry none of the contaminated-tick classes
that produced the 2026-06-11 fake edges.

NO WRITES. Opens the database read-only (``mode=ro``).

Usage (from the engine/ directory):
    .venv/Scripts/python -m scripts.bar_quality_fp_audit
    .venv/Scripts/python -m scripts.bar_quality_fp_audit --db data/jarvis_trader.db
    .venv/Scripts/python -m scripts.bar_quality_fp_audit --symbols MES,MGC

Exit codes:
    0 — traded futures clean (the gating condition for trusting their verdicts)
    1 — at least one traded-futures group has rejects
    2 — database not found / unreadable
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys

# engine/ is the parent of scripts/; put it on the path so `data` imports resolve
# whether run as `python -m scripts.bar_quality_fp_audit` or as a direct file.
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
_ENGINE_DIR = os.path.dirname(_SCRIPTS_DIR)
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)

from data.bar_quality_gate import screen_bars  # noqa: E402

_DEFAULT_DB = os.path.join(_ENGINE_DIR, "data", "jarvis_trader.db")

# Futures the strategies actually trade/backtest. The validated trend edges live
# on MES and MGC; MCL/MNQ are gated but still screened. Override with --symbols.
_DEFAULT_TRADED = ("MES", "MGC", "MCL", "MNQ")

# market_data_bars column order == the Row layout screen_bars expects.
_COLS = "symbol, interval, ts_utc, open, high, low, close, volume, source, fetched_at"


def audit(db_path: str, traded: set[str]) -> int:
    if not os.path.exists(db_path):
        print(f"ERROR: database not found: {db_path}", file=sys.stderr)
        return 2

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error as exc:
        print(f"ERROR: cannot open database read-only: {exc}", file=sys.stderr)
        return 2

    traded_upper = {s.upper() for s in traded}
    try:
        groups = conn.execute(
            "SELECT symbol, interval, COUNT(*) FROM market_data_bars "
            "GROUP BY symbol, interval ORDER BY symbol, interval"
        ).fetchall()

        print(f"DB: {db_path}")
        print(f"Traded futures audited for the exit code: {sorted(traded_upper)}")
        print(f"Distinct (symbol, interval) groups: {len(groups)}")
        print("-" * 72)

        total_rejects = 0
        traded_rejects = 0
        for symbol, interval, cnt in groups:
            rows = conn.execute(
                f"SELECT {_COLS} FROM market_data_bars "
                "WHERE symbol = ? AND interval = ? ORDER BY ts_utc",
                (symbol, interval),
            ).fetchall()
            rejects = screen_bars(rows)
            is_traded = symbol.upper() in traded_upper
            if rejects:
                by_reason: dict[str, int] = {}
                for rj in rejects:
                    by_reason[rj.reason] = by_reason.get(rj.reason, 0) + 1
                summary = ", ".join(f"{k}={v}" for k, v in sorted(by_reason.items()))
                flag = "  <-- TRADED" if is_traded else ""
                print(f"{symbol:8} {interval:6} n={cnt:7} REJECTS={len(rejects):5} ({summary}){flag}")
                total_rejects += len(rejects)
                if is_traded:
                    traded_rejects += len(rejects)
            else:
                mark = "TRADED" if is_traded else ""
                print(f"{symbol:8} {interval:6} n={cnt:7} clean {mark}")
    finally:
        conn.close()

    print("-" * 72)
    print(f"Total rejects (all symbols):     {total_rejects}")
    print(f"Total rejects (traded futures):  {traded_rejects}")
    if traded_rejects == 0:
        print("RESULT: traded futures CLEAN -- their gate-v2 verdicts read uncontaminated data.")
        return 0
    print("RESULT: traded futures have rejects — investigate before trusting their verdicts.")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only bar-quality audit of stored market_data_bars.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--db",
        default=_DEFAULT_DB,
        help=f"Path to jarvis_trader.db (default: {_DEFAULT_DB})",
    )
    parser.add_argument(
        "--symbols",
        default=",".join(_DEFAULT_TRADED),
        help=(
            "Comma-separated symbols that gate the exit code "
            f"(default: {','.join(_DEFAULT_TRADED)}). All groups are still printed."
        ),
    )
    args = parser.parse_args()
    traded = {s.strip() for s in args.symbols.split(",") if s.strip()}
    return audit(os.path.abspath(args.db), traded)


if __name__ == "__main__":
    sys.exit(main())
