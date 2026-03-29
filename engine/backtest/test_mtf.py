"""
JARVIS TRADER -- MTF Filter Test Script

Loads MNQ 1h and 4h data, runs generate_signals() with and without the
MTF filter, and reports how many entries were blocked.
"""
from __future__ import annotations
import sys
import os

# Ensure engine/ is on the path for backtest.* imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from backtest.data_loader import BacktestDataLoader
from backtest.signals import generate_signals, compute_all_indicators


def main():
    loader = BacktestDataLoader()
    symbol = "MNQ"
    start = "2024-06-01"
    end = "2026-03-27"

    # ── Load 1h data ──────────────────────────────────────────────────────
    print("=" * 70)
    print(f"Loading {symbol} 1h data ({start} to {end})...")
    df_1h = loader.load(symbol, start, end, interval="1h")
    if df_1h is None or df_1h.empty:
        print("ERROR: Could not load 1h data. Exiting.")
        return
    print(f"  1h bars: {len(df_1h)}")

    # ── Load 4h data ──────────────────────────────────────────────────────
    print(f"\nLoading {symbol} 4h data ({start} to {end})...")
    df_4h = loader.load(symbol, start, end, interval="4h")
    if df_4h is None or df_4h.empty:
        print("WARNING: Could not load 4h data directly.")
        print("Attempting to resample 1h data to 4h...")
        # Resample 1h -> 4h as fallback
        df_4h = df_1h.resample("4h").agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }).dropna(subset=["open", "high", "low", "close"])
        df_4h["timestamp"] = df_4h.index
        print(f"  Resampled to {len(df_4h)} 4h bars")
    else:
        print(f"  4h bars: {len(df_4h)}")

    # ── Compute 4h indicators ────────────────────────────────────────────
    print("\nComputing 4h indicators...")
    df_4h = compute_all_indicators(df_4h)
    print(f"  4h STC signal distribution:")
    print(f"    {df_4h['stc_signal'].value_counts().to_dict()}")

    # ── Baseline: generate signals without MTF filter ────────────────────
    print("\n" + "=" * 70)
    print("BASELINE: generate_signals(df_1h, symbol='MNQ') -- no MTF filter")
    print("=" * 70)
    df_baseline = generate_signals(df_1h.copy(), symbol=symbol)
    baseline_entries = df_baseline[df_baseline["entry_signal"] == "ENTRY_NOW"]
    print(f"  Total ENTRY_NOW signals: {len(baseline_entries)}")
    print(f"  Bias breakdown:")
    print(f"    {baseline_entries['bias'].value_counts().to_dict()}")

    # ── MTF-filtered: generate signals with 4h confirmation ──────────────
    print("\n" + "=" * 70)
    print("MTF FILTER: generate_signals(df_1h, symbol='MNQ', mtf_df=df_4h)")
    print("=" * 70)
    df_mtf = generate_signals(df_1h.copy(), symbol=symbol, mtf_df=df_4h)
    mtf_entries = df_mtf[df_mtf["entry_signal"] == "ENTRY_NOW"]
    mtf_blocked = df_mtf[df_mtf["entry_signal"] == "MTF_BLOCKED"]
    print(f"  Total ENTRY_NOW signals (passed): {len(mtf_entries)}")
    print(f"  Total MTF_BLOCKED signals:        {len(mtf_blocked)}")
    if len(baseline_entries) > 0:
        pct_blocked = len(mtf_blocked) / len(baseline_entries) * 100
        print(f"  Percentage blocked: {pct_blocked:.1f}%")
    print(f"  Passed bias breakdown:")
    print(f"    {mtf_entries['bias'].value_counts().to_dict()}")
    print(f"  Blocked bias breakdown:")
    print(f"    {mtf_blocked['bias'].value_counts().to_dict()}")

    # ── Spot-check: show a few blocked entries ───────────────────────────
    print("\n" + "=" * 70)
    print("SPOT CHECK: First 10 blocked entries")
    print("=" * 70)
    if len(mtf_blocked) > 0:
        cols = ["close", "bias", "stc_signal", "stc_val", "entry_signal", "mtf_aligned"]
        print(mtf_blocked[cols].head(10).to_string())

        # Show corresponding 4h STC at those timestamps
        print("\n  Corresponding 4h STC state at blocked timestamps:")
        for ts in mtf_blocked.index[:10]:
            # Find the most recent 4h bar
            mask = df_4h.index <= ts
            if mask.any():
                htf_row = df_4h.loc[mask].iloc[-1]
                print(
                    f"    {ts} -> 4h bar {htf_row.name}: "
                    f"stc_signal={htf_row['stc_signal']}, "
                    f"stc_val={htf_row['stc_val']:.1f}, "
                    f"cross_up={htf_row['stc_cross_up']}, "
                    f"cross_down={htf_row['stc_cross_down']}"
                )
    else:
        print("  No entries were blocked by MTF filter.")

    # ── Spot-check: first 5 ALLOWED entries ──────────────────────────────
    print("\n" + "=" * 70)
    print("SPOT CHECK: First 5 allowed entries")
    print("=" * 70)
    if len(mtf_entries) > 0:
        cols = ["close", "bias", "stc_signal", "stc_val", "entry_signal", "mtf_aligned"]
        print(mtf_entries[cols].head(5).to_string())

    # ── Summary ──────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"  Baseline entries:    {len(baseline_entries)}")
    print(f"  MTF-allowed entries: {len(mtf_entries)}")
    print(f"  MTF-blocked entries: {len(mtf_blocked)}")
    if len(baseline_entries) > 0:
        print(f"  Block rate:          {len(mtf_blocked)/len(baseline_entries)*100:.1f}%")
    print(f"\n  Suggested walk-forward flag: --mtf-filter")
    print(f"  (Integration with walk-forward engine is separate work)")


if __name__ == "__main__":
    main()
