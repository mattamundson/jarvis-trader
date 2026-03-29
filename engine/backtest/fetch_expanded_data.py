#!/usr/bin/env python
"""Fetch and cache data for expanded backtesting matrix."""
import sys
import time
from pathlib import Path

# Ensure engine/ is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtest.data_loader import BacktestDataLoader

SYMBOLS = ['MCL', 'MGC', 'M2K', 'GC', 'CL', 'RTY', 'SPY', 'MES', 'MNQ']
INTERVALS = ['1h', '1d']  # Yahoo Finance does not support 4h interval natively
START = '2024-06-01'
END = '2026-03-27'

def main():
    loader = BacktestDataLoader()
    results = {}

    total = len(SYMBOLS) * len(INTERVALS)
    done = 0

    for symbol in SYMBOLS:
        for interval in INTERVALS:
            done += 1
            key = f"{symbol}_{interval}"
            print(f"\n[{done}/{total}] Fetching {symbol} {interval} ({START} to {END})...")
            try:
                df = loader.load(symbol, START, END, interval)
                if df is not None and not df.empty:
                    results[key] = len(df)
                    print(f"  -> {symbol} {interval}: {len(df)} bars")
                else:
                    results[key] = 0
                    print(f"  -> {symbol} {interval}: NO DATA")
            except Exception as e:
                results[key] = 0
                print(f"  -> {symbol} {interval}: ERROR - {e}")

            # Small delay between fetches to avoid rate limiting
            time.sleep(1)

    # Summary
    print("\n" + "=" * 60)
    print("FETCH SUMMARY")
    print("=" * 60)
    print(f"{'Symbol':<8} {'Interval':<10} {'Bars':>8} {'Status'}")
    print("-" * 40)
    for key, count in results.items():
        symbol, interval = key.rsplit('_', 1)
        status = "OK" if count > 0 else "MISSING"
        print(f"{symbol:<8} {interval:<10} {count:>8} {status}")

    # Note about 4h
    print("\n" + "=" * 60)
    print("NOTE: Yahoo Finance does not support 4h interval natively.")
    print("To get 4h bars, resample 1h data: df.resample('4h').agg({...})")
    print("=" * 60)

    ok = sum(1 for v in results.values() if v > 0)
    fail = sum(1 for v in results.values() if v == 0)
    print(f"\nTotal: {ok} succeeded, {fail} failed out of {total}")

if __name__ == "__main__":
    main()
