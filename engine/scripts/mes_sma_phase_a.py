"""
Phase A — Baseline stress tests on MES SMA(50,200) backtest.

Runs the authoritative MES SMA backtest (same config as /backtest/run API
for is_trend=True), then pipes the BacktestResult into:
  1. run_monte_carlo() — permutation MC, 10,000 simulations
  2. run_monte_carlo() — permutation MC with 2-tick slippage stress
  3. evaluation_harness.evaluate() — two-layer institutional gate

Writes combined report to:
  engine/backtest/results/mes_sma_phase_a_YYYY-MM-DD.json

Usage (from engine/ dir):
  .venv/Scripts/python -m scripts.mes_sma_phase_a
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

# Make the engine package importable when run as `python -m scripts.mes_sma_phase_a`
ENGINE_DIR = Path(__file__).resolve().parent.parent
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

from backtest import BacktestDataLoader, Backtester
from backtest.evaluation_harness import evaluate
from backtest.monte_carlo import run_monte_carlo
from backtest.signals import TREND_INSTRUMENTS, generate_instrument_signals
from backtest.trend_signals import get_sma_trend_params


SYMBOL = "MES"
INTERVAL = "1h"
START = "2024-06-01"
END = "2026-03-27"
CAPITAL = 10_000.0
RISK_PER_TRADE = 0.01
N_SIMULATIONS = 10_000
SEED = 42


def run_mes_backtest() -> "BacktestResult":
    """Reproduce the exact backtest the /backtest/run API runs for MES."""
    loader = BacktestDataLoader()
    df = loader.load(SYMBOL, START, END, INTERVAL)
    if df is None or df.empty:
        raise ValueError(f"No cached data for {SYMBOL} {INTERVAL} {START}→{END}")

    df = generate_instrument_signals(df, symbol=SYMBOL)
    multiplier = loader.get_multiplier(SYMBOL)

    is_trend = SYMBOL.upper() in TREND_INSTRUMENTS
    assert is_trend, f"{SYMBOL} must be in TREND_INSTRUMENTS to run SMA phase A"
    trend_params = get_sma_trend_params(SYMBOL)

    backtester = Backtester(
        initial_capital=CAPITAL,
        risk_per_trade=RISK_PER_TRADE,
        trailing_stop=True,
        trailing_atr_mult=trend_params["atr_trail_mult"],
        t1_exit_pct=1.0,
        t2_exit_pct=0.0,
        strict_trailing=True,
        eod_close=False,
        use_targets=False,
        fixed_contracts=1,
        max_drawdown=0.99,
        max_daily_loss=0.99,
    )
    return backtester.run(df, SYMBOL, multiplier)


def build_report(result) -> dict:
    """Run MC (clean + slippage) + evaluation harness, assemble report."""
    print(f"[phase-a] MES backtest: {result.total_trades} trades, PF {result.profit_factor:.3f}")

    print("[phase-a] Running Monte Carlo (clean, 10k perms)...")
    mc_clean = run_monte_carlo(
        result,
        n_simulations=N_SIMULATIONS,
        initial_capital=CAPITAL,
        max_slippage_ticks=0.0,
        symbol=SYMBOL,
        seed=SEED,
    )

    print("[phase-a] Running Monte Carlo (2-tick slippage stress, 10k perms)...")
    mc_slip2 = run_monte_carlo(
        result,
        n_simulations=N_SIMULATIONS,
        initial_capital=CAPITAL,
        max_slippage_ticks=2.0,
        symbol=SYMBOL,
        seed=SEED,
    )

    print("[phase-a] Running evaluation harness (two-layer gate)...")
    eval_result = evaluate(result)

    # Breakeven slippage scan — how much extra slippage kills the edge?
    import numpy as np
    pnls = np.array([t.pnl for t in result.trades])
    n_trades = len(pnls)
    tick_value = 1.25  # MES
    breakeven_scan = []
    for extra_ticks in [0, 1, 2, 3, 4, 5, 6, 8, 10]:
        added_cost_per_trade = extra_ticks * tick_value
        adj = pnls - added_cost_per_trade
        gp = float(adj[adj > 0].sum()) if (adj > 0).any() else 0.0
        gl = float(abs(adj[adj <= 0].sum())) if (adj <= 0).any() else 0.0
        pf = gp / gl if gl > 0 else float("inf")
        breakeven_scan.append({"extra_ticks": extra_ticks, "pf": round(pf, 3)})

    return {
        "metadata": {
            "symbol": SYMBOL,
            "interval": INTERVAL,
            "start": START,
            "end": END,
            "capital": CAPITAL,
            "n_simulations": N_SIMULATIONS,
            "run_at": datetime.utcnow().isoformat() + "Z",
            "strategy": "SMA(50,200) + 2.0×ATR trail, fixed 1 contract, strict trailing, no targets, no EOD",
        },
        "backtest": {
            "total_trades": result.total_trades,
            "winning_trades": result.winning_trades,
            "losing_trades": result.losing_trades,
            "win_rate": round(result.win_rate, 4),
            "profit_factor": round(result.profit_factor, 4),
            "sharpe_ratio": round(result.sharpe_ratio, 4),
            "sortino_ratio": round(result.sortino_ratio, 4),
            "calmar_ratio": round(result.calmar_ratio, 4),
            "max_drawdown_pct": round(result.max_drawdown_pct, 4),
            "total_return_pct": round(result.total_return_pct, 4),
            "max_consecutive_losses": result.max_consecutive_losses,
            "avg_holding_bars": round(result.avg_holding_bars, 2),
        },
        "monte_carlo_clean": mc_clean,
        "monte_carlo_slippage_2tick": mc_slip2,
        "breakeven_slippage_scan": breakeven_scan,
        "evaluation_harness": {
            "verdict": eval_result.verdict.value,
            "layer1_passed": eval_result.layer1_passed,
            "layer2_passed": eval_result.layer2_passed,
            "violations": eval_result.violations,
            "details": eval_result.details,
            "summary": eval_result.summary(),
        },
        "gate_check": {
            "prob_profitable_gte_60": mc_clean["confidence"]["prob_profitable"] >= 60.0,
            "prob_profitable_value": mc_clean["confidence"]["prob_profitable"],
            "evaluation_eligible": eval_result.verdict.value == "ELIGIBLE",
            "slippage_2tick_still_profitable": mc_slip2["confidence"]["prob_profitable"] >= 50.0,
        },
    }


def print_summary(report: dict) -> None:
    bt = report["backtest"]
    mc_clean = report["monte_carlo_clean"]
    mc_slip = report["monte_carlo_slippage_2tick"]
    eval_ = report["evaluation_harness"]
    gate = report["gate_check"]

    print()
    print("=" * 70)
    print(f"MES SMA(50,200) — Phase A Stress-Test Report")
    print("=" * 70)
    print(f"Backtest: {bt['total_trades']} trades | WR {bt['win_rate']:.1%} | "
          f"PF {bt['profit_factor']:.3f} | Sharpe {bt['sharpe_ratio']:.3f} | "
          f"MaxDD {bt['max_drawdown_pct']:.2%}")
    print()
    print(f"Monte Carlo (clean, {mc_clean['n_simulations']:,} perms):")
    pf_dist = mc_clean["distribution"].get("profit_factor")  # may not exist
    fc_dist = mc_clean["distribution"]["final_capital"]
    dd_dist = mc_clean["distribution"]["max_drawdown_pct"]
    sh_dist = mc_clean["distribution"]["sharpe_ratio"]
    print(f"  Final capital:  p5=${fc_dist['p5']:,.0f}  p25=${fc_dist['p25']:,.0f}  "
          f"median=${fc_dist['median']:,.0f}  p75=${fc_dist['p75']:,.0f}  p95=${fc_dist['p95']:,.0f}")
    print(f"  Max drawdown:   p5={dd_dist['p5']:.2f}%  p25={dd_dist['p25']:.2f}%  "
          f"median={dd_dist['median']:.2f}%  p75={dd_dist['p75']:.2f}%  p95={dd_dist['p95']:.2f}%")
    print(f"  Sharpe ratio:   p5={sh_dist['p5']:.3f}  p25={sh_dist['p25']:.3f}  "
          f"median={sh_dist['median']:.3f}  p75={sh_dist['p75']:.3f}  p95={sh_dist['p95']:.3f}")
    print(f"  prob_profitable: {mc_clean['confidence']['prob_profitable']:.2f}%")
    print(f"  prob_2x_return:  {mc_clean['confidence']['prob_achieving_2x_return']:.2f}%")
    print(f"  prob_ruin:       {mc_clean['confidence']['probability_of_ruin']:.2f}%")
    print(f"  value_at_risk_5pct: ${mc_clean['confidence']['value_at_risk_5pct']:,.0f}")
    print(f"  expected_shortfall: ${mc_clean['confidence']['expected_shortfall']:,.0f}")
    print(f"  verdict: {mc_clean['verdict']}")
    print()
    print(f"Monte Carlo (+2-tick slippage, {mc_slip['n_simulations']:,} perms):")
    print(f"  prob_profitable: {mc_slip['confidence']['prob_profitable']:.2f}%  (vs clean: "
          f"{mc_clean['confidence']['prob_profitable']:.2f}%)")
    print(f"  verdict: {mc_slip['verdict']}")
    print()
    print("Breakeven slippage scan (when does PF drop below 1.0?):")
    for row in report["breakeven_slippage_scan"]:
        marker = " ← BREAKEVEN" if row["pf"] < 1.0 and row["extra_ticks"] > 0 else ""
        print(f"  +{row['extra_ticks']} ticks → PF {row['pf']:.3f}{marker}")
    print()
    print(f"Evaluation harness: {eval_['summary']}")
    print(f"  Layer 1 (stat validity): {'PASS' if eval_['layer1_passed'] else 'FAIL'}")
    print(f"  Layer 2 (risk-adj return): {'PASS' if eval_['layer2_passed'] else 'FAIL'}")
    if eval_["violations"]:
        print(f"  Violations: {eval_['violations']}")
    print()
    print("Gate check:")
    for k, v in gate.items():
        print(f"  {k}: {v}")
    print("=" * 70)


def main() -> int:
    print(f"[phase-a] Running MES SMA backtest: {START} → {END}")
    result = run_mes_backtest()
    report = build_report(result)
    print_summary(report)

    out_path = ENGINE_DIR / "backtest" / "results" / \
        f"mes_sma_phase_a_{datetime.utcnow():%Y-%m-%d}.json"
    out_path.write_text(json.dumps(report, indent=2, default=str))
    print(f"\n[phase-a] Report written: {out_path}")

    gate = report["gate_check"]
    exit_code = 0 if all([
        gate["prob_profitable_gte_60"],
        gate["evaluation_eligible"],
        gate["slippage_2tick_still_profitable"],
    ]) else 1
    print(f"[phase-a] Gate: {'PASS' if exit_code == 0 else 'FAIL'} (exit {exit_code})")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
