"""
JARVIS TRADER — News Blackout Filter Test
Tests Signal Improvement #4: blocking entries near major economic events.

Usage:
    cd engine
    .venv/Scripts/python -m backtest.test_news_blackout
"""
from __future__ import annotations
import sys
from pathlib import Path

# Ensure engine/ is on the path
engine_dir = Path(__file__).parent.parent
if str(engine_dir) not in sys.path:
    sys.path.insert(0, str(engine_dir))

from backtest.data_loader import BacktestDataLoader
from backtest.signals import generate_signals
from backtest.backtester import Backtester
from backtest.news_blackout import EconomicCalendar


def main():
    print("=" * 70)
    print("JARVIS TRADER — News Blackout Filter Test (Improvement #4)")
    print("=" * 70)

    # ── 1. Calendar summary ─────────────────────────────────────────────
    cal = EconomicCalendar()
    print(f"\n{cal.summary()}")

    events_in_range = cal.get_events_in_range("2024-06-01", "2026-03-27")
    print(f"\nEvents in backtest range (2024-06-01 to 2026-03-27): {len(events_in_range)}")
    for evt in events_in_range[:10]:
        print(f"  {evt['datetime'].strftime('%Y-%m-%d %H:%M')}  {evt['event_name']:20s}  impact={evt['impact_level']}")
    if len(events_in_range) > 10:
        print(f"  ... and {len(events_in_range) - 10} more events")

    # ── 2. Load MNQ 1h data ─────────────────────────────────────────────
    print("\n" + "-" * 70)
    print("Loading MNQ 1h data (2024-06-01 to 2026-03-27)...")
    loader = BacktestDataLoader()
    df = loader.load("MNQ", "2024-06-01", "2026-03-27", "1h")

    if df is None or df.empty:
        print("[ERROR] No MNQ data available. Check cache or network.")
        print("Trying NQ=F daily as fallback for demonstration...")
        df = loader.load("MNQ", "2024-06-01", "2026-03-27", "1d")
        if df is None or df.empty:
            print("[ERROR] No data at all. Cannot run test.")
            sys.exit(1)
        interval = "1d"
        window_minutes = 480  # block entire day for daily bars
    else:
        interval = "1h"
        window_minutes = 30

    print(f"Loaded {len(df)} bars ({interval})")

    # ── 3. Baseline signals (no blackout) ───────────────────────────────
    print("\n" + "-" * 70)
    print("Generating BASELINE signals (news_blackout=False)...")
    df_baseline = generate_signals(df.copy(), symbol="MNQ", news_blackout=False)
    baseline_entries = (df_baseline['entry_signal'] == 'ENTRY_NOW').sum()
    print(f"Baseline ENTRY_NOW signals: {baseline_entries}")

    # ── 4. Blackout-filtered signals ────────────────────────────────────
    print(f"\nGenerating BLACKOUT-FILTERED signals (window={window_minutes}min)...")
    df_filtered = generate_signals(
        df.copy(), symbol="MNQ",
        news_blackout=True, news_blackout_window=window_minutes,
    )
    filtered_entries = (df_filtered['entry_signal'] == 'ENTRY_NOW').sum()
    blocked_entries = (df_filtered['entry_signal'] == 'NEWS_BLACKOUT').sum()
    total_news_blocked_bars = df_filtered['news_blocked'].sum()

    print(f"Filtered ENTRY_NOW signals: {filtered_entries}")
    print(f"NEWS_BLACKOUT blocked signals: {blocked_entries}")
    print(f"Total bars in blackout zones: {total_news_blocked_bars}")
    print(f"Signals blocked: {blocked_entries} / {baseline_entries} "
          f"({blocked_entries/baseline_entries*100:.1f}%)" if baseline_entries > 0 else "")

    # ── 5. Analyze which events blocked which signals ───────────────────
    if blocked_entries > 0:
        print("\n" + "-" * 70)
        print("BLOCKED SIGNAL DETAILS:")
        blocked_rows = df_filtered[df_filtered['entry_signal'] == 'NEWS_BLACKOUT']
        event_type_counts = {}
        for idx_ts in blocked_rows.index:
            evt = cal.get_blackout_event(idx_ts, window_minutes=window_minutes)
            if evt:
                event_dt, event_name, impact = evt
                event_type_counts[event_name] = event_type_counts.get(event_name, 0) + 1
                print(f"  {idx_ts} -> blocked by {event_name} @ {event_dt.strftime('%Y-%m-%d %H:%M')}")

        print("\nBlocked by event type:")
        for name, count in sorted(event_type_counts.items(), key=lambda x: -x[1]):
            print(f"  {name}: {count} signals blocked")

    # ── 6. Run backtests: baseline vs filtered ──────────────────────────
    print("\n" + "-" * 70)
    print("BACKTEST COMPARISON: Baseline vs News-Blackout-Filtered")
    print("-" * 70)

    multiplier = loader.get_multiplier("MNQ")
    bt = Backtester(initial_capital=100_000, risk_per_trade=0.01)

    print("\nRunning BASELINE backtest...")
    result_baseline = bt.run(df_baseline, "MNQ", multiplier)

    print("Running FILTERED backtest...")
    bt2 = Backtester(initial_capital=100_000, risk_per_trade=0.01)
    result_filtered = bt2.run(df_filtered, "MNQ", multiplier)

    # ── 7. Compare metrics ──────────────────────────────────────────────
    print("\n" + "=" * 70)
    print(f"{'METRIC':<30} {'BASELINE':>15} {'FILTERED':>15} {'DELTA':>12}")
    print("=" * 70)

    def _fmt(val, fmt=".2f"):
        if isinstance(val, float):
            return f"{val:{fmt}}"
        return str(val)

    comparisons = [
        ("Total Trades", result_baseline.total_trades, result_filtered.total_trades, "d"),
        ("Win Rate", result_baseline.win_rate, result_filtered.win_rate, ".1%"),
        ("Profit Factor", result_baseline.profit_factor, result_filtered.profit_factor, ".2f"),
        ("Total Return %", result_baseline.total_return_pct * 100, result_filtered.total_return_pct * 100, ".1f"),
        ("Sharpe Ratio", result_baseline.sharpe_ratio, result_filtered.sharpe_ratio, ".2f"),
        ("Sortino Ratio", result_baseline.sortino_ratio, result_filtered.sortino_ratio, ".2f"),
        ("Max Drawdown %", result_baseline.max_drawdown_pct * 100, result_filtered.max_drawdown_pct * 100, ".1f"),
        ("Avg Win $", result_baseline.avg_win, result_filtered.avg_win, ",.0f"),
        ("Avg Loss $", result_baseline.avg_loss, result_filtered.avg_loss, ",.0f"),
        ("Max Consec Losses", result_baseline.max_consecutive_losses, result_filtered.max_consecutive_losses, "d"),
        ("Expectancy $", result_baseline.expectancy, result_filtered.expectancy, ",.0f"),
        ("Calmar Ratio", result_baseline.calmar_ratio, result_filtered.calmar_ratio, ".2f"),
    ]

    for label, base_val, filt_val, fmt in comparisons:
        if fmt == "d":
            b_str = str(int(base_val))
            f_str = str(int(filt_val))
            delta = int(filt_val) - int(base_val)
            d_str = f"{delta:+d}"
        elif fmt == ".1%":
            b_str = f"{base_val:.1%}"
            f_str = f"{filt_val:.1%}"
            delta = (filt_val - base_val) * 100
            d_str = f"{delta:+.1f}pp"
        elif fmt == ",.0f":
            b_str = f"${base_val:,.0f}"
            f_str = f"${filt_val:,.0f}"
            delta = filt_val - base_val
            d_str = f"${delta:+,.0f}"
        else:
            b_str = f"{base_val:{fmt}}"
            f_str = f"{filt_val:{fmt}}"
            delta = filt_val - base_val
            d_str = f"{delta:+{fmt}}"

        print(f"{label:<30} {b_str:>15} {f_str:>15} {d_str:>12}")

    # ── 8. Quality analysis: were blocked signals losers? ───────────────
    print("\n" + "-" * 70)
    print("QUALITY ANALYSIS: Were blocked signals likely losers?")
    print("-" * 70)

    # To answer this, we run the baseline backtest and check which trades
    # corresponded to entry bars that would have been blocked.
    if blocked_entries > 0 and result_baseline.total_trades > 0:
        blocked_timestamps = set(blocked_rows.index)

        # In the baseline, trades that entered on a blocked bar:
        # (entry_date is the execution bar = signal bar + 1 for pending entries,
        #  but the signal bar is what matters for the blackout check)
        # We need to find signal bars that were ENTRY_NOW in baseline but
        # NEWS_BLACKOUT in filtered. Those signal bars correspond to trades
        # entered on the NEXT bar.
        entry_now_baseline = set(df_baseline[df_baseline['entry_signal'] == 'ENTRY_NOW'].index)
        entry_now_filtered = set(df_filtered[df_filtered['entry_signal'] == 'ENTRY_NOW'].index)
        blocked_signal_bars = entry_now_baseline - entry_now_filtered

        # Map: for each trade, find which signal bar generated it
        # (trade.entry_date is the execution bar; the signal bar is the bar before)
        blocked_trades = []
        non_blocked_trades = []
        for trade in result_baseline.trades:
            # Find the signal bar (1 bar before entry bar in the index)
            entry_loc = df_baseline.index.get_loc(trade.entry_date)
            if entry_loc > 0:
                signal_bar_ts = df_baseline.index[entry_loc - 1]
                if signal_bar_ts in blocked_signal_bars:
                    blocked_trades.append(trade)
                else:
                    non_blocked_trades.append(trade)
            else:
                non_blocked_trades.append(trade)

        if blocked_trades:
            blocked_wins = sum(1 for t in blocked_trades if t.pnl > 0)
            blocked_losses = sum(1 for t in blocked_trades if t.pnl <= 0)
            blocked_total_pnl = sum(t.pnl for t in blocked_trades)
            blocked_wr = blocked_wins / len(blocked_trades) if blocked_trades else 0

            print(f"Trades that would have been blocked: {len(blocked_trades)}")
            print(f"  Winners: {blocked_wins}  |  Losers: {blocked_losses}")
            print(f"  Win Rate: {blocked_wr:.1%}")
            print(f"  Total P&L of blocked trades: ${blocked_total_pnl:,.0f}")
            if blocked_total_pnl < 0:
                print(f"  --> GOOD: Blocked trades were NET LOSERS (filter is beneficial)")
            elif blocked_total_pnl == 0:
                print(f"  --> NEUTRAL: Blocked trades broke even")
            else:
                print(f"  --> CAUTION: Blocked trades were NET WINNERS "
                      f"(filter may be removing good trades)")

            if non_blocked_trades:
                non_blocked_wr = sum(1 for t in non_blocked_trades if t.pnl > 0) / len(non_blocked_trades)
                print(f"\nNon-blocked trades win rate: {non_blocked_wr:.1%} "
                      f"vs blocked trades: {blocked_wr:.1%}")
        else:
            print("No trades matched blocked signal bars (may be due to pending entry logic).")
    else:
        print("No blocked entries to analyze.")

    # ── 9. Final verdict ────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("VERDICT:")
    pf_delta = result_filtered.profit_factor - result_baseline.profit_factor
    wr_delta = (result_filtered.win_rate - result_baseline.win_rate) * 100
    ret_delta = (result_filtered.total_return_pct - result_baseline.total_return_pct) * 100

    if pf_delta > 0 and wr_delta >= 0:
        print(f"  NEWS BLACKOUT IMPROVES performance:")
        print(f"  PF: {result_baseline.profit_factor:.2f} -> {result_filtered.profit_factor:.2f} ({pf_delta:+.2f})")
        print(f"  WR: {result_baseline.win_rate:.1%} -> {result_filtered.win_rate:.1%} ({wr_delta:+.1f}pp)")
        print(f"  Return: {result_baseline.total_return_pct*100:.1f}% -> {result_filtered.total_return_pct*100:.1f}% ({ret_delta:+.1f}pp)")
        print(f"  RECOMMENDATION: Enable news_blackout=True in production.")
    elif pf_delta < -0.05:
        print(f"  NEWS BLACKOUT HURTS performance:")
        print(f"  PF: {result_baseline.profit_factor:.2f} -> {result_filtered.profit_factor:.2f} ({pf_delta:+.2f})")
        print(f"  RECOMMENDATION: Keep news_blackout=False (or widen window).")
    else:
        print(f"  NEWS BLACKOUT has MARGINAL effect:")
        print(f"  PF: {result_baseline.profit_factor:.2f} -> {result_filtered.profit_factor:.2f} ({pf_delta:+.2f})")
        print(f"  WR: {result_baseline.win_rate:.1%} -> {result_filtered.win_rate:.1%} ({wr_delta:+.1f}pp)")
        print(f"  RECOMMENDATION: Use if risk-averse; marginal impact on returns.")
    print("=" * 70)


if __name__ == "__main__":
    main()
