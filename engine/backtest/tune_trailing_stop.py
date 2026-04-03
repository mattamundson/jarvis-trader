"""
JARVIS TRADER — Trailing Stop Tuner for MGC 1d
Grid search trailing_atr_mult values and post-T1 activation mode.

Usage (from engine/ dir):
    .venv/Scripts/python -m backtest.tune_trailing_stop
"""

from __future__ import annotations

import os
import sys

# Ensure engine/ is on the path when run as a module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.backtester import Backtester
from backtest.data_loader import BacktestDataLoader
from backtest.signals import generate_signals


def run_grid():
    """Run trailing stop grid search for MGC 1d."""
    print("=" * 100)
    print("JARVIS TRADER — Trailing Stop Tuner: MGC 1d")
    print("=" * 100)
    print()

    # Load data
    loader = BacktestDataLoader()
    df_raw = loader.load("MGC", "2025-01-01", "2026-03-27", "1d")
    if df_raw is None or df_raw.empty:
        print("[ERROR] Could not load MGC 1d data. Check cache or network.")
        return

    print(f"Loaded {len(df_raw)} bars for MGC 1d")

    # Generate signals once (shared across all runs)
    df = generate_signals(df_raw, symbol="MGC", adaptive_regime=True)
    print(f"Signals generated: {(df['entry_signal'] == 'ENTRY_NOW').sum()} ENTRY_NOW signals")
    print()

    # ── Baseline: no trailing stop ──────────────────────────────────────
    # Note: risk_per_trade=0.01 (1%) to ensure at least 1 contract with
    # MGC's tight 0.30 ATR stop (~8pt x $10 = $80/contract).
    # 0.25% risk on $25k = $62.50 which is below min contract risk.
    bt_base = Backtester(
        initial_capital=25000,
        risk_per_trade=0.01,
        trailing_stop=False,
    )
    base_result = bt_base.run(df.copy(), "MGC", 10.0)

    print("BASELINE (no trailing stop):")
    print(
        f"  Trades={base_result.total_trades}  WR={base_result.win_rate:.1%}  "
        f"PF={base_result.profit_factor:.2f}  Return={base_result.total_return_pct:+.1%}  "
        f"MaxDD={base_result.max_drawdown_pct:.1%}"
    )
    print()

    # ── Grid search ─────────────────────────────────────────────────────
    atr_mults = [0.70, 1.00, 1.20, 1.50, 1.80, 2.00, 2.50, 3.00]
    post_t1_modes = [False, True]

    results = []

    for mult in atr_mults:
        for post_t1 in post_t1_modes:
            bt = Backtester(
                initial_capital=25000,
                risk_per_trade=0.01,
                trailing_stop=True,
                trailing_atr_mult=mult,
                trailing_post_t1=post_t1,
            )
            r = bt.run(df.copy(), "MGC", 10.0)

            results.append(
                {
                    "mult": mult,
                    "post_t1": post_t1,
                    "trades": r.total_trades,
                    "wr": r.win_rate,
                    "pf": r.profit_factor,
                    "ret": r.total_return_pct,
                    "maxdd": r.max_drawdown_pct,
                    "trailing_exits": r.trailing_stop_exits,
                    "sharpe": r.sharpe_ratio,
                    "sortino": r.sortino_ratio,
                    "calmar": r.calmar_ratio,
                    "expectancy": r.expectancy,
                    "avg_win": r.avg_win,
                    "avg_loss": r.avg_loss,
                }
            )

    # ── Print results table ─────────────────────────────────────────────
    print()
    print("=" * 120)
    print(
        f"{'ATR Mult':>10} | {'Post-T1':>8} | {'Trades':>6} | {'WR':>6} | {'PF':>6} | "
        f"{'Return':>8} | {'MaxDD':>6} | {'Trail X':>7} | {'Sharpe':>7} | {'Sortino':>8} | {'Calmar':>7}"
    )
    print("-" * 120)

    for row in results:
        print(
            f"{row['mult']:>10.2f} | {'Yes' if row['post_t1'] else 'No':>8} | "
            f"{row['trades']:>6} | {row['wr']:>5.1%} | {row['pf']:>6.2f} | "
            f"{row['ret']:>+7.1%} | {row['maxdd']:>5.1%} | {row['trailing_exits']:>7} | "
            f"{row['sharpe']:>7.2f} | {row['sortino']:>8.2f} | {row['calmar']:>7.2f}"
        )

    print("-" * 120)
    # Baseline row
    print(
        f"{'BASELINE':>10} | {'N/A':>8} | "
        f"{base_result.total_trades:>6} | {base_result.win_rate:>5.1%} | {base_result.profit_factor:>6.2f} | "
        f"{base_result.total_return_pct:>+7.1%} | {base_result.max_drawdown_pct:>5.1%} | "
        f"{'0':>7} | {base_result.sharpe_ratio:>7.2f} | {base_result.sortino_ratio:>8.2f} | "
        f"{base_result.calmar_ratio:>7.2f}"
    )
    print("=" * 120)

    # ── Analysis: find optimal ──────────────────────────────────────────
    print()
    print("=" * 80)
    print("ANALYSIS")
    print("=" * 80)

    # Score = Return * (1 - MaxDD) — balances return with risk
    # Also compute WFE proxy: how well trailing improves risk-adjusted return
    for row in results:
        row["score"] = row["ret"] * (1.0 - row["maxdd"])
        # Return x Calmar as a combined metric
        row["ret_x_calmar"] = row["ret"] * row["calmar"] if row["calmar"] > 0 else 0

    base_score = base_result.total_return_pct * (1.0 - base_result.max_drawdown_pct)
    base_ret_x_calmar = base_result.total_return_pct * base_result.calmar_ratio

    print(f"\nBaseline score (Return x (1-MaxDD)): {base_score:.4f}")
    print(f"Baseline Return x Calmar: {base_ret_x_calmar:.4f}")

    # Best by score
    best = max(results, key=lambda r: r["score"])
    print("\nBest by Return x (1-MaxDD):")
    print(f"  ATR Mult={best['mult']:.2f}, Post-T1={'Yes' if best['post_t1'] else 'No'}")
    print(f"  Score={best['score']:.4f} (vs baseline {base_score:.4f})")
    print(f"  Return={best['ret']:+.1%}, MaxDD={best['maxdd']:.1%}, PF={best['pf']:.2f}")

    # Best by Return x Calmar
    best_rc = max(results, key=lambda r: r["ret_x_calmar"])
    print("\nBest by Return x Calmar:")
    print(f"  ATR Mult={best_rc['mult']:.2f}, Post-T1={'Yes' if best_rc['post_t1'] else 'No'}")
    print(f"  Return x Calmar={best_rc['ret_x_calmar']:.4f} (vs baseline {base_ret_x_calmar:.4f})")
    print(
        f"  Return={best_rc['ret']:+.1%}, MaxDD={best_rc['maxdd']:.1%}, Calmar={best_rc['calmar']:.2f}"
    )

    # Compare post_t1 vs immediate at optimal mult
    print(f"\n--- Comparison at ATR Mult={best['mult']:.2f} ---")
    for row in results:
        if row["mult"] == best["mult"]:
            label = "Post-T1" if row["post_t1"] else "Immediate"
            print(
                f"  {label:>10}: Return={row['ret']:+.1%}, MaxDD={row['maxdd']:.1%}, "
                f"PF={row['pf']:.2f}, Trailing Exits={row['trailing_exits']}, "
                f"Sharpe={row['sharpe']:.2f}"
            )

    # Check if any trailing config beats baseline
    print("\n--- vs Baseline ---")
    improvements = [r for r in results if r["score"] > base_score]
    if improvements:
        print(f"  {len(improvements)} configs beat baseline:")
        for r in sorted(improvements, key=lambda x: x["score"], reverse=True):
            delta = r["score"] - base_score
            print(
                f"    ATR={r['mult']:.2f} Post-T1={'Yes' if r['post_t1'] else 'No'}: "
                f"score={r['score']:.4f} (+{delta:.4f}), "
                f"Return={r['ret']:+.1%}, MaxDD={r['maxdd']:.1%}"
            )
    else:
        print("  No trailing config beats baseline! Consider running without trailing stop.")
        # Find the one that comes closest
        closest = min(results, key=lambda r: abs(r["score"] - base_score))
        print(
            f"  Closest: ATR={closest['mult']:.2f} Post-T1={'Yes' if closest['post_t1'] else 'No'}: "
            f"score={closest['score']:.4f} (baseline={base_score:.4f})"
        )

    # Final recommendation
    print()
    print("=" * 80)
    print("RECOMMENDATION")
    print("=" * 80)
    if best["score"] > base_score * 1.05:
        print(
            f"  USE trailing stop: ATR Mult={best['mult']:.2f}, "
            f"Post-T1={'Yes' if best['post_t1'] else 'No'}"
        )
        print(
            f"  Expected improvement: Return={best['ret']:+.1%} vs {base_result.total_return_pct:+.1%}, "
            f"MaxDD={best['maxdd']:.1%} vs {base_result.max_drawdown_pct:.1%}"
        )
    elif best["score"] > base_score:
        print(
            f"  MARGINAL improvement with trailing: ATR Mult={best['mult']:.2f}, "
            f"Post-T1={'Yes' if best['post_t1'] else 'No'}"
        )
        print("  Improvement is <5% — consider keeping no trailing stop for simplicity.")
    else:
        print("  DO NOT USE trailing stop for MGC 1d.")
        print("  Baseline (no trailing) outperforms all trailing configs.")
        print(
            "  The fixed target system (T1/T2/T3) already handles exits optimally for gold's trend characteristics."
        )


if __name__ == "__main__":
    run_grid()
