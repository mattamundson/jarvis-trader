"""Bar-quality gate — false-positive audit (read-only).

Backs the shadow->enforce decision for the write-time bar-quality gate
(``data/bar_quality_gate.py``). Screens every bar already in
``market_data_bars`` through the SAME predicate the gate uses on write and
reports what *would* be rejected, grouped by symbol/interval and reason.

Interpretation:
  * Zero rejects for a symbol  -> enforcing the gate cannot drop any of its
    real bars; flipping BAR_QUALITY_GATE_ENFORCE=1 is safe for it.
  * Non-zero rejects           -> inspect the samples. On post-quarantine data
    these are residual contamination the gate correctly catches (not false
    positives) — e.g. SPY 1h wrong-era prints (~100 interleaved with ~728).

Exit code: 0 if the configured TRADED futures are all clean (enforce-safe),
1 otherwise. SPY/equities are reported but do not gate the exit code, since
they are not in the live futures trading set.

Usage:
    python -m scripts.bar_quality_fp_audit [db_path]
"""

from __future__ import annotations

import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

# Allow running both as `python -m scripts.bar_quality_fp_audit` and directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.bar_quality_gate import screen_bars  # noqa: E402

_DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "jarvis_trader.db"
# Futures actually scanned/traded — these MUST be clean to enforce safely.
TRADED_FUTURES = {"MES", "MGC", "MCL", "MNQ", "M2K"}

_COLS = "symbol,interval,ts_utc,open,high,low,close,volume,source,fetched_at"


def audit(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        pairs = list(conn.execute("SELECT DISTINCT symbol, interval FROM market_data_bars"))
        total = 0
        rejects = 0
        by_symbol: dict[str, int] = defaultdict(int)
        by_reason: dict[str, int] = defaultdict(int)
        samples: list[str] = []
        for sym, iv in pairs:
            rows = list(
                conn.execute(
                    f"SELECT {_COLS} FROM market_data_bars "
                    "WHERE symbol=? AND interval=? ORDER BY ts_utc",
                    (sym, iv),
                )
            )
            total += len(rows)
            rj = screen_bars(rows)
            rejects += len(rj)
            for r in rj:
                by_symbol[sym] += 1
                by_reason[r.reason] += 1
                if len(samples) < 15:
                    samples.append(f"{sym} {iv} {r.reason}: {r.detail}")
    finally:
        conn.close()

    print(f"Bars screened : {total}")
    print(f"Would reject  : {rejects} ({100 * rejects / max(total, 1):.4f}%)")
    print(f"By reason     : {dict(by_reason)}")
    print(f"By symbol     : {dict(by_symbol)}")
    if samples:
        print("Samples:")
        for s in samples:
            print("  -", s)

    dirty_traded = sorted(s for s in by_symbol if s in TRADED_FUTURES)
    if dirty_traded:
        print(f"\nNOT enforce-safe — traded futures with rejects: {dirty_traded}")
        return 1
    print("\nEnforce-safe: all traded futures are clean "
          f"({', '.join(sorted(TRADED_FUTURES))}). Non-traded rejects are "
          "residual contamination the gate correctly catches.")
    return 0


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else str(_DEFAULT_DB)
    raise SystemExit(audit(db))
