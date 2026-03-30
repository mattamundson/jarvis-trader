"""
Fetch extended historical data (2022-2026) for all key symbols.
Caches to backtest/cache/ for use in extended walk-forward validation.

Notes:
- yfinance 1h data only goes back ~2 years from today (~730 days)
- Daily data goes back 5+ years
- For 1h we try 2024-01-01 as earliest feasible start
- For 1d we fetch from 2022-01-01
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from backtest.data_loader import BacktestDataLoader

loader = BacktestDataLoader()

# Symbols to fetch
symbols_all = ["SPY", "MES", "MNQ", "MCL", "MGC", "M2K"]

end = "2026-03-28"

# ── PHASE 1: Daily data from 2022 ──
print("=" * 60)
print("PHASE 1: Fetching DAILY data (2022-01-01 to 2026-03-28)")
print("=" * 60)
daily_start = "2022-01-01"
results = {}

for sym in symbols_all:
    print(f"\n  {sym} 1d ...", end=" ", flush=True)
    try:
        df = loader.load(sym, daily_start, end, "1d")
        if df is not None and not df.empty:
            first = df.index.min().date()
            last = df.index.max().date()
            results[f"{sym}_1d"] = {"bars": len(df), "first": str(first), "last": str(last)}
            print(f"OK  {len(df)} bars  ({first} -> {last})")
        else:
            results[f"{sym}_1d"] = {"bars": 0, "first": "N/A", "last": "N/A"}
            print("FAILED or empty")
    except Exception as e:
        results[f"{sym}_1d"] = {"bars": 0, "first": "N/A", "last": str(e)}
        print(f"ERROR: {e}")
    time.sleep(1)  # Be nice to Yahoo

# ── PHASE 2: Hourly data (as far back as possible) ──
print("\n" + "=" * 60)
print("PHASE 2: Fetching HOURLY data (2024-01-01 to 2026-03-28)")
print("  (yfinance 1h limit is ~730 days)")
print("=" * 60)
hourly_start = "2024-01-01"

for sym in symbols_all:
    print(f"\n  {sym} 1h ...", end=" ", flush=True)
    try:
        df = loader.load(sym, hourly_start, end, "1h")
        if df is not None and not df.empty:
            first = df.index.min().date()
            last = df.index.max().date()
            results[f"{sym}_1h"] = {"bars": len(df), "first": str(first), "last": str(last)}
            print(f"OK  {len(df)} bars  ({first} -> {last})")
        else:
            results[f"{sym}_1h"] = {"bars": 0, "first": "N/A", "last": "N/A"}
            print("FAILED or empty")
    except Exception as e:
        results[f"{sym}_1h"] = {"bars": 0, "first": "N/A", "last": str(e)}
        print(f"ERROR: {e}")
    time.sleep(1)

# ── Summary ──
print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)
print(f"{'Symbol/TF':<15} {'Bars':>7}  {'First':>12}  {'Last':>12}")
print("-" * 50)
for key in sorted(results.keys()):
    r = results[key]
    print(f"{key:<15} {r['bars']:>7}  {r['first']:>12}  {r['last']:>12}")

# Cache size
print("\n\nCache contents:")
cache_dir = os.path.join(os.path.dirname(__file__), "backtest", "cache")
total_kb = 0
for f in sorted(os.listdir(cache_dir)):
    fpath = os.path.join(cache_dir, f)
    size = os.path.getsize(fpath) // 1024
    total_kb += size
    print(f"  {f} ({size}KB)")
print(f"\nTotal cache size: {total_kb / 1024:.1f} MB")
