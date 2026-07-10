#!/usr/bin/env python
"""Validate the live MES champion strategy against the backtest-rigor guardrails.

Runs the ACTUAL production MES trend config (SMA fast=50, slow=200,
atr_trail_mult=2.0 — ``backtest.trend_signals.SMA_TREND_PARAMS["MES"]``,
the same params live paper trading uses) through the real ``Backtester`` on
the full cached MES 1h history, then feeds the resulting trade list through
every gate in ``backtest.rigor_gates``. Read-only validation: does not import
or touch ``engine/agents/`` or the live signal-generation path, and does not
write anywhere except stdout.

Usage (from engine/ directory):
    .venv/Scripts/python backtest/run_mes_rigor_gates_validation.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

engine_root = Path(__file__).parent.parent
if str(engine_root) not in sys.path:
    sys.path.insert(0, str(engine_root))

SYMBOL = "MES"
MULTIPLIER = 5.0
CAPITAL = 50_000.0
COMMISSION = 0.62
SLIPPAGE_TICKS = 2.0

FAST, SLOW, ATR_TRAIL_MULT = 50, 200, 2.0


def _load_data(data_file: Path) -> pd.DataFrame:
    df = pd.read_csv(data_file)
    df.columns = [c.lower() for c in df.columns]
    ts_col = "timestamp" if "timestamp" in df.columns else "datetime"
    df[ts_col] = pd.to_datetime(df[ts_col])
    df = df.set_index(ts_col).sort_index()
    return df


def main() -> None:
    from backtest._gate_v2_helpers import _find_latest_cache
    from backtest.backtester import Backtester
    from backtest.trend_signals import generate_sma_trend_signals

    data_dir = engine_root / "backtest" / "cache"
    data_file = _find_latest_cache(data_dir, "MES")
    print(f"[VALIDATE] Selected cache: {data_file.name}")

    df = _load_data(data_file)
    print(f"[VALIDATE] {len(df)} bars | {df.index.min()} -> {df.index.max()}")
    print(f"[VALIDATE] Champion params: fast={FAST} slow={SLOW} atr_trail_mult={ATR_TRAIL_MULT}")

    df_sig = generate_sma_trend_signals(df, fast=FAST, slow=SLOW, atr_trail_mult=ATR_TRAIL_MULT)
    bt = Backtester(
        initial_capital=CAPITAL,
        risk_per_trade=0.01,
        max_daily_loss=0.02,
        max_drawdown=0.05,
        t1_exit_pct=0.50,
        t2_exit_pct=0.30,
        commission_per_contract=COMMISSION,
        slippage_ticks=SLIPPAGE_TICKS,
    )
    result = bt.run(df_sig, symbol=SYMBOL, multiplier=MULTIPLIER)

    pnls = [t.pnl for t in result.trades]
    n = len(pnls)
    print(f"\n[VALIDATE] Full-history backtest: {n} trades, PF={result.profit_factor:.3f}, "
          f"Sharpe={result.sharpe_ratio:.3f}, max_dd={result.max_drawdown_pct:.2%}")

    if n < 2:
        print("[VALIDATE] Too few trades to run the rigor gates meaningfully. Exiting.")
        return

    from backtest.rigor_gates import (
        adf_stationarity_check,
        diebold_mariano_test,
        ljung_box_independence_check,
        mc_permutation_gate,
        sharpe_implausibility_gate,
    )

    print(f"\n{'=' * 70}")
    print("1. SHARPE-IMPLAUSIBILITY GATE")
    print(f"{'=' * 70}")
    g1 = sharpe_implausibility_gate(sharpe=result.sharpe_ratio, n_trades=n)
    print(f"  flagged={g1['flagged']}  severity={g1['severity']}")
    print(f"  {g1['explanation']}")

    print(f"\n{'=' * 70}")
    print("2. MC TRADE-ORDER PERMUTATION GATE (reorders the REAL trade list)")
    print(f"{'=' * 70}")
    g2 = mc_permutation_gate(pnls, n_iters=2000, initial_capital=CAPITAL, symbol=SYMBOL, seed=42)
    print(f"  consistent_with_reordering={g2['consistent_with_reordering']}  "
          f"monte_carlo_verdict={g2['monte_carlo_verdict']}")
    print(f"  real_sharpe={g2['real_sharpe']} (pct={g2['sharpe_percentile']})  "
          f"real_max_dd_pct={g2['real_max_dd_pct']} (pct={g2['max_dd_percentile']})")
    print(f"  {g2['explanation']}")

    print(f"\n{'=' * 70}")
    print("3. LJUNG-BOX INDEPENDENCE PRE-CHECK (on the trade P&L series)")
    print(f"{'=' * 70}")
    lags = min(10, n // 3) if n >= 15 else max(1, n - 3)
    g3 = ljung_box_independence_check(pnls, lags=lags)
    print(f"  independent={g3['independent']}  lags={lags}")
    print(f"  {g3['explanation']}")

    print(f"\n{'=' * 70}")
    print("4. ADF STATIONARITY PRE-CHECK (on the MES close-price series)")
    print(f"{'=' * 70}")
    closes = df["close"].to_numpy()
    g4 = adf_stationarity_check(closes)
    print(f"  stationary={g4['stationary']}")
    print(f"  {g4['explanation']}")

    log_returns = np.diff(np.log(closes))
    g4b = adf_stationarity_check(log_returns)
    print(f"\n  [also] ADF on log-returns (the more relevant series for signal combination):")
    print(f"  stationary={g4b['stationary']}")
    print(f"  {g4b['explanation']}")

    print(f"\n{'=' * 70}")
    print("5. DIEBOLD-MARIANO TEST — strategy's realized per-trade return vs. the")
    print("   underlying's raw price return over that same entry->exit window")
    print(f"{'=' * 70}")
    # Baseline here is deliberately NOT a second candidate strategy (none is being
    # proposed for swap-in) — it is "what would holding the underlying flat over
    # the identical entry->exit window have returned", the cleanest apples-to-apples
    # comparator available without inventing a second strategy. Aligned by
    # construction: one candidate/baseline pair per realized trade, same window.
    candidate_returns = []
    baseline_returns = []
    for t in result.trades:
        if not t.exit_price or not t.entry_price:
            continue
        candidate_returns.append(t.pnl_pct)
        baseline_returns.append((t.exit_price - t.entry_price) / t.entry_price)

    if len(candidate_returns) >= 10:
        g5 = diebold_mariano_test(candidate_returns, baseline_returns, h=1)
        print(f"  n_trades_compared={len(candidate_returns)}")
        print(f"  significant={g5['significant']}  better={g5['better']}")
        print(f"  {g5['explanation']}")
    else:
        g5 = {"significant": False, "better": "tie (insufficient trades)"}
        print(f"  Only {len(candidate_returns)} trades with valid entry/exit prices — "
              "skipping (DM needs >= 10).")

    print(f"\n{'=' * 70}")
    print("SUMMARY")
    print(f"{'=' * 70}")
    print(f"  Live MES champion (fast=50, slow=200, atr_trail_mult=2.0), full-history backtest:")
    print(f"    n_trades={n}  PF={result.profit_factor:.3f}  Sharpe={result.sharpe_ratio:.3f}  "
          f"max_dd={result.max_drawdown_pct:.2%}")
    print(f"  Gate 1 (Sharpe implausibility): {'FLAGGED' if g1['flagged'] else 'clean'} "
          f"({g1['severity']})")
    print(f"  Gate 2 (MC reordering):         "
          f"{'consistent' if g2['consistent_with_reordering'] else 'FLAGGED (outlier)'}")
    print(f"  Gate 3 (Ljung-Box on trades):   "
          f"{'independent (i.i.d.-consistent)' if g3['independent'] else 'autocorrelated'}")
    print(f"  Gate 4 (ADF on close price):    "
          f"{'stationary' if g4['stationary'] else 'non-stationary (expected for a price level)'}")
    print(f"  Gate 4b (ADF on log-returns):   "
          f"{'stationary' if g4b['stationary'] else 'non-stationary'}")
    print(f"  Gate 5 (DM vs buy-and-hold):    {g5['better']} "
          f"({'significant' if g5['significant'] else 'not significant'})")


if __name__ == "__main__":
    main()
