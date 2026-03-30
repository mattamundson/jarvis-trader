"""
JARVIS TRADER — Trailing ATR Stop Comparison Test

Compares baseline (fixed stop) vs trailing ATR stop on:
  1. MGC 1d  (2025-01-01 to 2026-03-27)
  2. MNQ 1h  (2025-01-01 to 2026-03-27)

Reports: trade count, win rate, PF, return, MaxDD, exit type breakdown.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

# Ensure engine/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtest.backtester import Backtester
from backtest.data_loader import BacktestDataLoader
from backtest.signals import generate_signals


def run_comparison(
    symbol: str,
    start: str,
    end: str,
    interval: str,
    capital: float = 100_000.0,
    trailing_atr_mult: float = 0.70,
):
    """Run baseline vs trailing stop and print comparison."""
    loader = BacktestDataLoader()
    multiplier = loader.get_multiplier(symbol)

    print(f"\n{'=' * 70}")
    print(f"  {symbol} {interval}  |  {start} -> {end}  |  Multiplier: {multiplier}")
    print(f"{'=' * 70}")

    # Load data
    df = loader.load(symbol, start, end, interval)
    if df is None or df.empty:
        print(f"[ERROR] No data for {symbol}. Skipping.")
        return None, None

    print(f"Loaded {len(df)} bars. Computing signals...")
    df = generate_signals(df, symbol=symbol)
    entry_count = (df["entry_signal"] == "ENTRY_NOW").sum()
    print(f"Found {entry_count} ENTRY_NOW signals.")

    # --- Baseline (fixed stop) ---
    bt_baseline = Backtester(
        initial_capital=capital,
        trailing_stop=False,
    )
    result_baseline = bt_baseline.run(df, symbol, multiplier)

    # --- Trailing stop ---
    bt_trailing = Backtester(
        initial_capital=capital,
        trailing_stop=True,
        trailing_atr_mult=trailing_atr_mult,
    )
    result_trailing = bt_trailing.run(df, symbol, multiplier)

    # --- Exit type breakdown ---
    def exit_breakdown(result):
        reasons = Counter(t.exit_reason for t in result.trades)
        total = max(len(result.trades), 1)
        return {r: (c, f"{c / total:.0%}") for r, c in reasons.most_common()}

    baseline_exits = exit_breakdown(result_baseline)
    trailing_exits = exit_breakdown(result_trailing)

    # --- Print comparison table ---
    print(f"\n{'Metric':<28} {'Baseline (Fixed)':<22} {'Trailing Stop':<22} {'Delta':<15}")
    print("-" * 87)

    metrics = [
        ("Total Trades", result_baseline.total_trades, result_trailing.total_trades, ""),
        (
            "Win Rate",
            f"{result_baseline.win_rate:.1%}",
            f"{result_trailing.win_rate:.1%}",
            f"{(result_trailing.win_rate - result_baseline.win_rate):+.1%}",
        ),
        (
            "Profit Factor",
            f"{result_baseline.profit_factor:.2f}",
            f"{result_trailing.profit_factor:.2f}",
            f"{result_trailing.profit_factor - result_baseline.profit_factor:+.2f}",
        ),
        (
            "Total Return",
            f"{result_baseline.total_return_pct:+.1%}",
            f"{result_trailing.total_return_pct:+.1%}",
            f"{(result_trailing.total_return_pct - result_baseline.total_return_pct):+.1%}",
        ),
        (
            "Total PnL ($)",
            f"${result_baseline.total_pnl:,.0f}",
            f"${result_trailing.total_pnl:,.0f}",
            f"${result_trailing.total_pnl - result_baseline.total_pnl:+,.0f}",
        ),
        (
            "Max Drawdown",
            f"{result_baseline.max_drawdown_pct:.1%}",
            f"{result_trailing.max_drawdown_pct:.1%}",
            f"{(result_trailing.max_drawdown_pct - result_baseline.max_drawdown_pct):+.1%}",
        ),
        (
            "Sharpe",
            f"{result_baseline.sharpe_ratio:.2f}",
            f"{result_trailing.sharpe_ratio:.2f}",
            f"{result_trailing.sharpe_ratio - result_baseline.sharpe_ratio:+.2f}",
        ),
        ("Avg Win ($)", f"${result_baseline.avg_win:,.0f}", f"${result_trailing.avg_win:,.0f}", ""),
        (
            "Avg Loss ($)",
            f"${result_baseline.avg_loss:,.0f}",
            f"${result_trailing.avg_loss:,.0f}",
            "",
        ),
        (
            "Avg Holding Bars",
            f"{result_baseline.avg_holding_bars:.1f}",
            f"{result_trailing.avg_holding_bars:.1f}",
            "",
        ),
    ]

    for label, base_val, trail_val, delta in metrics:
        print(f"{label:<28} {str(base_val):<22} {str(trail_val):<22} {delta:<15}")

    # Exit type breakdown
    print("\n--- Exit Type Breakdown ---")
    all_reasons = sorted(set(list(baseline_exits.keys()) + list(trailing_exits.keys())))
    print(f"{'Exit Reason':<20} {'Baseline':<22} {'Trailing':<22}")
    print("-" * 64)
    for reason in all_reasons:
        b_count, b_pct = baseline_exits.get(reason, (0, "0%"))
        t_count, t_pct = trailing_exits.get(reason, (0, "0%"))
        print(f"{reason:<20} {b_count:>3} ({b_pct:>4})           {t_count:>3} ({t_pct:>4})")

    # Trailing stop specific
    print(f"\nTrailing stop exits: {result_trailing.trailing_stop_exits}")

    return result_baseline, result_trailing


def main():
    print("=" * 70)
    print("  JARVIS TRADER — Trailing ATR Stop Comparison Test")
    print("  Trailing ATR Multiplier: 0.70")
    print("=" * 70)

    # Test 1: MGC daily
    run_comparison("MGC", "2025-01-01", "2026-03-27", "1d")

    # Test 2: MNQ 1h
    run_comparison("MNQ", "2025-01-01", "2026-03-27", "1h")

    print("\n" + "=" * 70)
    print("  Test complete.")
    print("=" * 70)


if __name__ == "__main__":
    main()
