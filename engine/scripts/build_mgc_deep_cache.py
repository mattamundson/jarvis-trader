"""One-off: build a deep MGC 1h cache from Databento and validate it before use.

Needed because the 2026-09-17 audit + provenance check found NO deep MGC cache on disk
(docs/research/mgc-deep-cache-absence-2026-09-17.md), which blocks any MGC evidence at the
certification standard. Mirrors how the MES deep cache was produced.

Research data only. Writes a NEW cache file; never touches live/paper trading.

Validation gate (all must pass before the file is accepted):
  - span >= 5.0 years            (shallow caches cannot certify edge)
  - 0 duplicate timestamps
  - 0 NaN in OHLC
  - OHLC sanity: high >= low, high >= max(open,close), low <= min(open,close), all prices > 0
"""

from __future__ import annotations

import sys
from pathlib import Path

engine_root = Path(__file__).resolve().parent.parent  # engine/ (this file lives in engine/scripts/)
sys.path.insert(0, str(engine_root))

START = "2015-01-01"
END = "2026-09-18"
CACHE_DIR = engine_root / "backtest" / "cache"


def main() -> int:
    from backtest.databento_loader import fetch_ohlcv

    print(f"[MGC-DEEP] fetching GLBX.MDP3 ohlcv-1h {START} -> {END}")
    df = fetch_ohlcv("MGC", start=START, end=END, interval="1h")
    if df is None or len(df) == 0:
        print("[MGC-DEEP] FETCH RETURNED EMPTY - no cache written.")
        print("           Likely causes: DATABENTO_API_KEY not visible to this process, the")
        print("           databento package missing, no entitlements/balance for GLBX.MDP3, or")
        print("           the requested range predates available MGC history.")
        return 3

    df = df[~df.index.duplicated(keep="first")].sort_index()
    dupes = int(df.index.duplicated().sum())
    nan_ohlc = int(df[["open", "high", "low", "close"]].isna().sum().sum())
    bad_hl = int((df["high"] < df["low"]).sum())
    bad_h = int((df["high"] < df[["open", "close"]].max(axis=1)).sum())
    bad_l = int((df["low"] > df[["open", "close"]].min(axis=1)).sum())
    nonpos = int((df[["open", "high", "low", "close"]] <= 0).sum().sum())

    span_years = (df.index.max() - df.index.min()).days / 365.25
    print(f"[MGC-DEEP] bars={len(df)} span={df.index.min()} -> {df.index.max()} ({span_years:.3f}y)")
    print(f"[MGC-DEEP] dupes={dupes} nan_ohlc={nan_ohlc} bad_high_low={bad_hl} "
          f"bad_high={bad_h} bad_low={bad_l} nonpositive={nonpos}")

    problems = []
    if span_years < 5.0:
        problems.append(f"span {span_years:.2f}y < 5.0y (does not meet the deep standard)")
    for label, count in (("duplicate timestamps", dupes), ("NaN in OHLC", nan_ohlc),
                         ("high<low rows", bad_hl), ("high<max(open,close) rows", bad_h),
                         ("low>min(open,close) rows", bad_l), ("non-positive prices", nonpos)):
        if count:
            problems.append(f"{label}: {count}")

    if problems:
        print("[MGC-DEEP] REJECTED - not writing a cache that fails validation:")
        for p in problems:
            print("   -", p)
        return 4

    out = CACHE_DIR / f"MGC_{START}_{df.index.max().date()}_1h.csv"
    df.to_csv(out, index_label="timestamp")
    print(f"[MGC-DEEP] wrote {out.name} ({out.stat().st_size} bytes)")

    from backtest._gate_v2_helpers import cache_provenance
    prov = cache_provenance(out)
    for k in sorted(prov):
        print(f"    {k}: {prov[k]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
