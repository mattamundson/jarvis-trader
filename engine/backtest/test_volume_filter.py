"""
JARVIS TRADER — Volume Filter Test (Improvement #3)
Compares baseline signals vs volume-filtered signals on MNQ 1h data.

Answers:
  1. How many entries were blocked by the volume filter?
  2. Baseline vs volume-filtered backtest metrics
  3. Did the filter block more losers than winners? (quality analysis)
"""

from __future__ import annotations

import os
import sys

# Ensure engine/ is on the path when run as a script
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from backtest.backtester import Backtester
from backtest.data_loader import BacktestDataLoader
from backtest.signals import generate_signals


def main():
    # ── 1. Load MNQ 1h data ────────────────────────────────────────────
    loader = BacktestDataLoader()
    df = loader.load("MNQ", start="2024-06-01", end="2026-03-27", interval="1h")
    if df is None or df.empty:
        print("ERROR: Could not load MNQ 1h data from cache.")
        return

    print(f"\n{'=' * 70}")
    print(f"  VOLUME FILTER TEST — MNQ 1h  ({df.index[0].date()} to {df.index[-1].date()})")
    print(f"{'=' * 70}")
    print(f"Total bars: {len(df)}")

    # Check volume data quality
    vol = df["volume"]
    zero_vol = (vol == 0).sum()
    nan_vol = vol.isna().sum()
    print(
        f"Volume stats: mean={vol.mean():.0f}, median={vol.median():.0f}, "
        f"zeros={zero_vol}, NaN={nan_vol}"
    )
    if zero_vol + nan_vol > len(df) * 0.5:
        print("WARNING: >50% of volume data is zero/NaN — filter will be unreliable.")

    # ── 2. Generate baseline signals ────────────────────────────────────
    print("\n--- Generating baseline signals (no volume filter) ---")
    df_baseline = generate_signals(df.copy(), symbol="MNQ")
    baseline_entries = (df_baseline["entry_signal"] == "ENTRY_NOW").sum()
    print(f"Baseline ENTRY_NOW signals: {baseline_entries}")

    # ── 3. Generate volume-filtered signals ─────────────────────────────
    print("\n--- Generating volume-filtered signals (period=20) ---")
    df_vol = generate_signals(df.copy(), symbol="MNQ", volume_filter=True, volume_period=20)
    vol_entries = (df_vol["entry_signal"] == "ENTRY_NOW").sum()
    blocked = (df_vol["entry_signal"] == "LOW_VOLUME_BLOCK").sum()
    print(f"Volume-filtered ENTRY_NOW signals: {vol_entries}")
    print(f"Blocked by volume filter: {blocked}")
    if baseline_entries > 0:
        print(f"Block rate: {blocked / baseline_entries:.1%}")

    # ── 4. Run backtests ────────────────────────────────────────────────
    multiplier = loader.get_multiplier("MNQ")

    print("\n--- Running baseline backtest ---")
    bt_base = Backtester(initial_capital=100_000)
    result_base = bt_base.run(df_baseline, symbol="MNQ", multiplier=multiplier)

    print("--- Running volume-filtered backtest ---")
    bt_vol = Backtester(initial_capital=100_000)
    result_vol = bt_vol.run(df_vol, symbol="MNQ", multiplier=multiplier)

    # ── 5. Print comparison ─────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print("  RESULTS COMPARISON")
    print(f"{'=' * 70}")
    print(f"{'Metric':<30} {'Baseline':>15} {'Vol Filter':>15} {'Delta':>12}")
    print(f"{'-' * 72}")

    metrics = [
        ("Trades", result_base.total_trades, result_vol.total_trades),
        ("Win Rate", f"{result_base.win_rate:.1%}", f"{result_vol.win_rate:.1%}"),
        ("Profit Factor", f"{result_base.profit_factor:.2f}", f"{result_vol.profit_factor:.2f}"),
        (
            "Total Return %",
            f"{result_base.total_return_pct * 100:+.1f}%",
            f"{result_vol.total_return_pct * 100:+.1f}%",
        ),
        ("Total PnL $", f"${result_base.total_pnl:,.0f}", f"${result_vol.total_pnl:,.0f}"),
        ("Sharpe", f"{result_base.sharpe_ratio:.2f}", f"{result_vol.sharpe_ratio:.2f}"),
        ("Sortino", f"{result_base.sortino_ratio:.2f}", f"{result_vol.sortino_ratio:.2f}"),
        (
            "Max Drawdown %",
            f"{result_base.max_drawdown_pct * 100:.1f}%",
            f"{result_vol.max_drawdown_pct * 100:.1f}%",
        ),
        ("Avg Win $", f"${result_base.avg_win:,.0f}", f"${result_vol.avg_win:,.0f}"),
        ("Avg Loss $", f"${result_base.avg_loss:,.0f}", f"${result_vol.avg_loss:,.0f}"),
        ("Expectancy $", f"${result_base.expectancy:,.0f}", f"${result_vol.expectancy:,.0f}"),
        ("Calmar", f"{result_base.calmar_ratio:.2f}", f"{result_vol.calmar_ratio:.2f}"),
        ("Blocked Signals", "0", str(blocked)),
    ]

    for m in metrics:
        name, base_val, vol_val = m
        if isinstance(base_val, (int, float)) and isinstance(vol_val, (int, float)):
            delta = vol_val - base_val
            delta_str = f"{delta:+}" if isinstance(delta, int) else f"{delta:+.2f}"
        else:
            delta_str = ""
        print(f"{name:<30} {str(base_val):>15} {str(vol_val):>15} {delta_str:>12}")

    # ── 6. Quality analysis: did the filter block losers? ───────────────
    print(f"\n{'=' * 70}")
    print("  QUALITY ANALYSIS: Were blocked signals losers?")
    print(f"{'=' * 70}")

    # Find the bars that were blocked
    blocked_mask = df_vol["entry_signal"] == "LOW_VOLUME_BLOCK"
    blocked_bars = df_vol[blocked_mask].copy()

    if len(blocked_bars) == 0:
        print("No signals were blocked — volume filter had no effect.")
        return

    # For each blocked signal, simulate what would have happened:
    # Entry at next bar's open, check if T1 or stop would have been hit
    blocked_outcomes = []
    for idx in blocked_bars.index:
        idx_pos = df_baseline.index.get_loc(idx)
        if idx_pos + 1 >= len(df_baseline):
            continue

        row = df_baseline.loc[idx]
        bias = row["bias"]
        direction = "long" if "BULL" in str(bias) else "short"
        entry_price = df_baseline.iloc[idx_pos + 1]["open"]
        stop = row["stop_level"]
        t1 = row["target_1"]
        atr_val = row.get("atr", 0)

        if atr_val <= 0 or entry_price <= 0:
            continue

        # Simulate forward up to 20 bars (or end of day)
        pnl = 0.0
        exit_reason = "timeout"
        for fwd in range(1, 21):
            if idx_pos + 1 + fwd >= len(df_baseline):
                break
            fwd_row = df_baseline.iloc[idx_pos + 1 + fwd]
            fwd_high = fwd_row["high"]
            fwd_low = fwd_row["low"]

            if direction == "long":
                if fwd_low <= stop:
                    pnl = stop - entry_price
                    exit_reason = "stop"
                    break
                if fwd_high >= t1:
                    pnl = t1 - entry_price
                    exit_reason = "target"
                    break
            else:
                if fwd_high >= stop:
                    pnl = entry_price - stop
                    exit_reason = "stop"
                    break
                if fwd_low <= t1:
                    pnl = entry_price - t1
                    exit_reason = "target"
                    break

        if exit_reason == "timeout":
            # Close at last forward bar
            last_pos = min(idx_pos + 21, len(df_baseline) - 1)
            last_close = df_baseline.iloc[last_pos]["close"]
            if direction == "long":
                pnl = last_close - entry_price
            else:
                pnl = entry_price - last_close

        blocked_outcomes.append(
            {
                "date": idx,
                "direction": direction,
                "entry_price": entry_price,
                "pnl_points": pnl,
                "exit_reason": exit_reason,
                "would_win": pnl > 0,
            }
        )

    if not blocked_outcomes:
        print("Could not simulate blocked signal outcomes (all at end of data).")
        return

    outcomes_df = pd.DataFrame(blocked_outcomes)
    total_blocked = len(outcomes_df)
    winners_blocked = outcomes_df["would_win"].sum()
    losers_blocked = total_blocked - winners_blocked

    print(f"\nBlocked signals analyzed: {total_blocked}")
    print(f"  Would have been WINNERS: {winners_blocked} ({winners_blocked / total_blocked:.0%})")
    print(f"  Would have been LOSERS:  {losers_blocked} ({losers_blocked / total_blocked:.0%})")
    print(f"  Avg PnL of blocked (points): {outcomes_df['pnl_points'].mean():+.2f}")

    # Exit reason breakdown
    print("\nBlocked signal exit reasons:")
    for reason, count in outcomes_df["exit_reason"].value_counts().items():
        avg_pnl = outcomes_df[outcomes_df["exit_reason"] == reason]["pnl_points"].mean()
        print(f"  {reason}: {count} ({count / total_blocked:.0%}), avg PnL: {avg_pnl:+.2f} pts")

    # Verdict
    print(f"\n{'=' * 70}")
    if losers_blocked > winners_blocked:
        pct_losers = losers_blocked / total_blocked
        print(f"  VERDICT: Volume filter is BENEFICIAL — {pct_losers:.0%} of blocked were losers.")
        print("  The filter correctly identified low-conviction entries that would have lost.")
    elif winners_blocked > losers_blocked:
        pct_winners = winners_blocked / total_blocked
        print(f"  VERDICT: Volume filter is HARMFUL — {pct_winners:.0%} of blocked were winners.")
        print("  The filter is removing good trades. Consider disabling or adjusting period.")
    else:
        print("  VERDICT: Volume filter is NEUTRAL — equal winners and losers blocked.")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
