#!/usr/bin/env python
"""E7-FOLLOWUP independent verification of SPY/QQQ deep caches.

1. Runs the engine's own gate: backtest.cache_completeness.inspect_cache_file.
2. Independent cross-check: enumerate every missing weekday in the cache span,
   subtract the whitelist (holidays | early closes), and report any residual
   (which would be genuine holes). Also sanity-verify the 2015-2018 holiday
   additions are real NYSE closures by checking each against known calendars.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

engine_root = Path(__file__).resolve().parent
sys.path.insert(0, str(engine_root))

from backtest.cache_completeness import (  # noqa: E402
    US_MARKET_EARLY_CLOSES,
    US_MARKET_HOLIDAYS,
    inspect_cache_file,
)

CACHES = [
    engine_root / "backtest" / "cache" / "SPY_2015-01-01_2026-08-17_1d.csv",
    engine_root / "backtest" / "cache" / "QQQ_2015-01-01_2026-08-17_1d.csv",
]

# Known-good reference: NYSE holiday closures 2015-2018 (incl. special closes)
REF_2015_2018 = {
    (2015, 1, 1), (2015, 1, 19), (2015, 2, 16), (2015, 4, 3), (2015, 5, 25),
    (2015, 7, 3), (2015, 9, 7), (2015, 11, 26), (2015, 12, 25),
    (2016, 1, 1), (2016, 1, 18), (2016, 2, 15), (2016, 3, 25), (2016, 5, 30),
    (2016, 7, 4), (2016, 9, 5), (2016, 11, 24), (2016, 12, 26),
    (2017, 1, 2), (2017, 1, 16), (2017, 2, 20), (2017, 4, 14), (2017, 5, 29),
    (2017, 7, 4), (2017, 9, 4), (2017, 11, 23), (2017, 12, 25),
    (2018, 1, 1), (2018, 1, 15), (2018, 2, 19), (2018, 3, 30), (2018, 5, 28),
    (2018, 7, 4), (2018, 9, 3), (2018, 11, 22), (2018, 12, 5), (2018, 12, 25),
}


def missing_weekdays(df: pd.DataFrame) -> set[date]:
    """All Mon-Fri dates in [min,max] absent from the index."""
    idx = pd.to_datetime(df.index).normalize()
    present = set(idx.date)
    start, end = idx.min().date(), idx.max().date()
    missing: set[date] = set()
    d = start
    while d <= end:
        if d.weekday() < 5 and d not in present:
            missing.add(d)
        d += timedelta(days=1)
    return missing


def main() -> int:
    whitelist = US_MARKET_HOLIDAYS | US_MARKET_EARLY_CLOSES

    # 1. Verify 2015-2018 additions against the reference closure calendar.
    added = US_MARKET_HOLIDAYS - frozenset(
        date(y, m, d) for y in range(2019, 2031)
        for m, d in [(1, 1)]
    )
    missing_from_ref = [d for d in whitelist if d.year in (2015, 2016, 2017, 2018)
                        and (d.year, d.month, d.day) not in REF_2015_2018]
    print("=== whitelist 2015-2018 vs NYSE reference ===")
    print("whitelist entries 2015-2018 not in reference calendar:",
          missing_from_ref or "NONE (all genuine closures)")
    ref_not_in_wl = [
        date(*ymd) for ymd in sorted(REF_2015_2018)
        if date(*ymd) not in whitelist
    ]
    print("reference closures 2015-2018 missing from whitelist:",
          ref_not_in_wl or "NONE (complete)")

    ok = True
    for path in CACHES:
        print(f"\n=== {path.name} ===")
        rep = inspect_cache_file(path, holiday_dates=whitelist)
        print(f"trustworthy={rep['trustworthy']} "
              f"n_suspicious_gaps={rep['n_suspicious_gaps']}")
        df = pd.read_csv(path)
        df.columns = [c.lower() for c in df.columns]
        ts_col = "timestamp" if "timestamp" in df.columns else "datetime"
        ts = pd.to_datetime(df[ts_col])
        if getattr(ts.dt, "tz", None) is not None:
            ts = ts.dt.tz_localize(None)
        df[ts_col] = ts
        df = df.set_index(ts_col).sort_index()
        print(f"bars={len(df)} span={df.index.min().date()} -> "
              f"{df.index.max().date()}")

        miss = missing_weekdays(df)
        unexplained = sorted(d for d in miss if d not in whitelist)
        # Explicable-only check: every missing weekday must be a whitelist day
        print(f"missing weekdays total={len(miss)}")
        print(f"  whitelist-covered (holidays/early closes)={len(miss) - len(unexplained)}")
        print(f"  UNEXPLAINED (genuine holes): {len(unexplained)}")
        for d in unexplained[:20]:
            print(f"    HOLE {d} ({d.strftime('%A')})")
        if unexplained:
            ok = False
    print("\n=== RESULT:", "ALL CLEAN" if ok else "HOLES FOUND", "===")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
