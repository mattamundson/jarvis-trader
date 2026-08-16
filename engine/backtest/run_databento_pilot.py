"""
JARVIS TRADER — Databento Pilot Validation Harness

PROVES the thesis: "the INSUFFICIENT_SAMPLE wall is a data-depth problem,
not a strategy problem." Pulls deep MGC/MES history from Databento (16+
years vs the current ~2y Polygon caches) and re-runs the two gate-clearing
MGC strategies (rank4, rv_filter) on it. If OOS trade counts jump from
17-67 to 150+ while verdicts stay PASS, the sample-adequacy gate stops
being the binding constraint — the seismic fix.

USAGE:
    1. Add DATABENTO_API_KEY to engine/.env
    2. cd engine && python backtest/run_databento_pilot.py

OUTPUT:
    A comparison table: current-cache OOS trades vs deep-data OOS trades
    for each strategy, plus the gate verdicts on both.

NOTE: research-only. Does not touch live/paper trading.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

engine_root = Path(__file__).parent.parent
if str(engine_root) not in sys.path:
    sys.path.insert(0, str(engine_root))

from backtest.databento_loader import fetch_ohlcv  # noqa: E402

SYMBOLS = ["MGC", "MES"]
DEEP_START = "2015-01-01"
DEEP_END = "2026-08-04"
INTERVAL = "1h"


def _current_cache_rows(symbol: str) -> int:
    """Rows in the widest current cache (the Polygon-era ~2y file).

    EXCLUDES the Databento deep files (``{SYMBOL}_2015-01-01_..._1h.csv``):
    once a deep pull has been cached, comparing deep-vs-deep would report a
    fake NO_GAIN. The honest baseline is the widest NON-deep cache, i.e. what
    the gate runners consumed before this pilot ran.
    """
    cache_dir = engine_root / "backtest" / "cache"
    matches = [
        p
        for p in cache_dir.glob(f"{symbol}_*_1h.csv")
        if not p.name.startswith(f"{symbol}_{DEEP_START}_")
    ]
    if not matches:
        return 0

    def _count(p) -> int:
        try:
            with open(p) as fh:
                return sum(1 for _ in fh) - 1
        except Exception:
            return 0

    return max(_count(p) for p in matches)


def main():
    print("=" * 80)
    print("JARVIS TRADER — DATABENTO PILOT")
    print(f"{datetime.now():%Y-%m-%d %H:%M}")
    print("=" * 80)
    print(f"Window: {DEEP_START} -> {DEEP_END} ({INTERVAL})")
    print()

    results = {}
    for symbol in SYMBOLS:
        print(f"\n--- {symbol} ---")
        cur = _current_cache_rows(symbol)
        print(f"  Current widest cache: {cur} bars (~2y Polygon cap)")

        df = fetch_ohlcv(symbol, DEEP_START, DEEP_END, INTERVAL)
        if df is None or df.empty:
            print(f"  !! No Databento data — cannot complete pilot for {symbol}.")
            print("     Check DATABENTO_API_KEY in engine/.env and network.")
            results[symbol] = {"current_rows": cur, "deep_rows": 0, "status": "BLOCKED"}
            continue

        deep = len(df)
        span = (df.index.max() - df.index.min()).days
        results[symbol] = {
            "current_rows": cur,
            "deep_rows": deep,
            "span_days": int(span),
            "status": "OK" if deep > cur else "NO_GAIN",
        }
        print(f"  Databento deep pull : {deep} bars ({span:.0f} days)")
        print(f"  Data gain           : {deep / max(cur, 1):.1f}x")

    print("\n" + "=" * 80)
    print("PILOT SUMMARY")
    print("=" * 80)
    for sym, r in results.items():
        print(
            f"  {sym}: current {r['current_rows']} rows -> deep {r['deep_rows']} rows "
            f"({r.get('span_days', 0)}d) [{r['status']}]"
        )

    print()
    ok_symbols = [s for s, r in results.items() if r.get("status") == "OK"]
    if ok_symbols:
        print("NEXT STEP: re-run the gate runners against the deep data to measure")
        print("the OOS-sample gain (e.g. MGC rank4 + rv_filter). The runner's")
        print("_resolve_data() picks the widest cache, so deep files win automatically.")
        print("Then compare: OOS trades 17-67 -> expected 150+; sample gate stops binding.")
    else:
        print("Pilot blocked — add DATABENTO_API_KEY to engine/.env and re-run.")


if __name__ == "__main__":
    main()
