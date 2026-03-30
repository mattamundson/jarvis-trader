"""
JARVIS TRADER — Monte Carlo Simulation
Validates backtest robustness by randomizing trade order N times.
If the strategy is truly profitable, the original equity curve should
sit in the upper portion of the shuffled distribution.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List

import numpy as np

from backtest.backtester import BacktestResult, Trade

# ---------------------------------------------------------------------------
# Core simulation
# ---------------------------------------------------------------------------

def _get_tick_value(symbol: str) -> float:
    """Get tick value in dollars for a given symbol.

    Args:
        symbol: Futures symbol (MES, MNQ, SPY, etc.)

    Returns:
        Dollar value per tick
    """
    tick_values = {
        "MES": 1.25,    # Micro E-mini S&P 500
        "MNQ": 0.50,    # Micro E-mini Nasdaq-100
        "SPY": 0.01,    # SPY per-share resolution
        "ES": 50.0,     # E-mini S&P 500
        "NQ": 20.0,     # E-mini Nasdaq-100
    }
    return tick_values.get(symbol, 0.01)


def _compute_sharpe(equity: np.ndarray, ann_factor: float = 252.0) -> float:
    """Annualised Sharpe from an equity curve (trade-by-trade steps)."""
    if len(equity) < 2:
        return 0.0
    returns = np.diff(equity) / equity[:-1]
    std = returns.std()
    if std == 0:
        return 0.0
    return float(returns.mean() / std * np.sqrt(ann_factor))


def _compute_max_dd(equity: np.ndarray) -> float:
    """Max drawdown as a positive percentage (0-100 scale)."""
    if len(equity) < 2:
        return 0.0
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / peak
    return float(abs(dd.min()) * 100.0)


def run_monte_carlo(
    result: BacktestResult,
    n_simulations: int = 10_000,
    initial_capital: float = 100_000.0,
    max_slippage_ticks: float = 0.0,
    symbol: str = "MES",
    seed: int = 42,
) -> dict:
    """Run Monte Carlo simulation on a BacktestResult.

    Shuffles the trade P&L sequence *n_simulations* times and collects
    distributions of final capital, max drawdown, and Sharpe ratio.

    Args:
        result: BacktestResult object with trades
        n_simulations: Number of Monte Carlo runs (default 1000)
        initial_capital: Starting capital (default 100000)
        max_slippage_ticks: Max random slippage per trade in ticks (default 0)
        symbol: Instrument symbol for tick value lookup (default MES)
        seed: Random seed for reproducibility (default 42)

    Returns:
        Dictionary with percentile statistics, confidence metrics, and verdict
    """
    pnls = np.array([t.pnl for t in result.trades], dtype=np.float64)

    # Get tick value for slippage conversion
    tick_value = _get_tick_value(symbol)
    n_trades = len(pnls)

    if n_trades == 0:
        return {
            "n_simulations": n_simulations,
            "n_trades": 0,
            "original": {},
            "distribution": {},
            "confidence": {},
            "verdict": "POOR",
        }

    # --- Original strategy metrics ---
    orig_equity = initial_capital + np.cumsum(pnls)
    orig_equity = np.concatenate([[initial_capital], orig_equity])
    orig_final = float(orig_equity[-1])
    orig_return_pct = (orig_final - initial_capital) / initial_capital * 100.0
    orig_max_dd = _compute_max_dd(orig_equity)
    orig_sharpe = _compute_sharpe(orig_equity)

    gross_profit = float(pnls[pnls > 0].sum()) if (pnls > 0).any() else 0.0
    gross_loss = float(abs(pnls[pnls <= 0].sum())) if (pnls <= 0).any() else 0.0
    orig_pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    # --- Monte Carlo simulations (vectorised) ---
    rng = np.random.default_rng(seed)

    # Build matrix of shuffled indices: (n_simulations, n_trades)
    # Each row is a permutation of trade indices
    idx_matrix = np.tile(np.arange(n_trades), (n_simulations, 1))
    # Shuffle each row independently using the RNG
    for i in range(n_simulations):
        rng.shuffle(idx_matrix[i])

    # Gather shuffled P&Ls and compute cumulative equity curves
    shuffled_pnls = pnls[idx_matrix]  # (n_simulations, n_trades)

    # Apply random slippage if specified
    if max_slippage_ticks > 0:
        # Generate random slippage in ticks: uniform between 0 and max_slippage_ticks
        # Shape: (n_simulations, n_trades)
        slippage_ticks = rng.uniform(0, max_slippage_ticks, size=(n_simulations, n_trades))
        # Convert ticks to dollars and subtract from P&Ls (slippage reduces profit/increases loss)
        slippage_dollars = slippage_ticks * tick_value
        shuffled_pnls = shuffled_pnls - slippage_dollars

    cum_pnls = np.cumsum(shuffled_pnls, axis=1)  # (n_simulations, n_trades)

    # Prepend initial capital column
    init_col = np.full((n_simulations, 1), initial_capital)
    equities = np.hstack([init_col, initial_capital + cum_pnls])  # (n_sims, n_trades+1)

    # Final capitals
    final_capitals = equities[:, -1]

    # Max drawdowns per simulation
    peaks = np.maximum.accumulate(equities, axis=1)
    dd = (equities - peaks) / peaks
    max_dds = np.abs(dd.min(axis=1)) * 100.0  # positive percentages

    # Sharpe ratios per simulation
    returns = np.diff(equities, axis=1) / equities[:, :-1]
    means = returns.mean(axis=1)
    stds = returns.std(axis=1)
    # Avoid division by zero
    safe_stds = np.where(stds == 0, 1.0, stds)
    sharpes = means / safe_stds * np.sqrt(252.0)
    sharpes = np.where(stds == 0, 0.0, sharpes)

    # --- Distribution stats helper ---
    def _dist_stats(arr: np.ndarray) -> dict:
        return {
            "p5": float(np.percentile(arr, 5)),
            "p25": float(np.percentile(arr, 25)),
            "median": float(np.median(arr)),
            "p75": float(np.percentile(arr, 75)),
            "p95": float(np.percentile(arr, 95)),
            "mean": float(arr.mean()),
            "std": float(arr.std()),
        }

    dist_final = _dist_stats(final_capitals)
    dist_dd = _dist_stats(max_dds)
    dist_sharpe = _dist_stats(sharpes)

    # --- Confidence metrics ---
    prob_profitable = float((final_capitals > initial_capital).mean() * 100.0)
    prob_better = float((final_capitals >= orig_final).mean() * 100.0)
    prob_2x = float((final_capitals >= initial_capital * 2.0).mean() * 100.0)
    prob_ruin = float((final_capitals < initial_capital).mean() * 100.0)
    var_5 = float(np.percentile(final_capitals, 5))
    bottom_5_mask = final_capitals <= np.percentile(final_capitals, 5)
    expected_shortfall = float(final_capitals[bottom_5_mask].mean()) if bottom_5_mask.any() else var_5

    # --- Verdict ---
    original_above_p75 = orig_final >= dist_final["p75"]
    original_above_median = orig_final >= dist_final["median"]

    if prob_profitable > 80.0 and original_above_p75:
        verdict = "EXCELLENT"
    elif prob_profitable > 65.0 and original_above_median:
        verdict = "GOOD"
    elif prob_profitable > 50.0:
        verdict = "MARGINAL"
    else:
        verdict = "POOR"

    return {
        "n_simulations": n_simulations,
        "n_trades": n_trades,
        "original": {
            "final_capital": round(orig_final, 2),
            "total_return_pct": round(orig_return_pct, 2),
            "max_drawdown_pct": round(orig_max_dd, 2),
            "sharpe_ratio": round(orig_sharpe, 4),
            "profit_factor": round(orig_pf, 3),
        },
        "distribution": {
            "final_capital": {k: round(v, 2) for k, v in dist_final.items()},
            "max_drawdown_pct": {k: round(v, 2) for k, v in dist_dd.items()},
            "sharpe_ratio": {k: round(v, 4) for k, v in dist_sharpe.items()},
        },
        "confidence": {
            "prob_profitable": round(prob_profitable, 2),
            "prob_better_than_original": round(prob_better, 2),
            "prob_achieving_2x_return": round(prob_2x, 2),
            "probability_of_ruin": round(prob_ruin, 2),
            "value_at_risk_5pct": round(var_5, 2),
            "expected_shortfall": round(expected_shortfall, 2),
            "worst_case_max_drawdown": round(float(np.percentile(max_dds, 5)), 2),
        },
        "verdict": verdict,
    }


# ---------------------------------------------------------------------------
# Report formatter
# ---------------------------------------------------------------------------

def format_report(mc: dict) -> str:
    """Return a human-readable Monte Carlo report string."""
    if mc["n_trades"] == 0:
        return "=== MONTE CARLO ANALYSIS ===\nNo trades to simulate.\n"

    o = mc["original"]
    d = mc["distribution"]
    c = mc["confidence"]

    lines = [
        f"=== MONTE CARLO ANALYSIS ({mc['n_simulations']:,} simulations) ===",
        f"Original Strategy: Return={o['total_return_pct']:+.1f}%  "
        f"MaxDD={o['max_drawdown_pct']:.1f}%  "
        f"Sharpe={o['sharpe_ratio']:.2f}  "
        f"PF={o['profit_factor']:.2f}",
        "",
        "DISTRIBUTION OF OUTCOMES:",
        f"{'':14s} {'P5%':>10s} {'P25%':>10s} {'Median':>10s} {'P75%':>10s} {'P95%':>10s}",
        f"{'Final Cap:':14s} "
        f"${d['final_capital']['p5']:>9,.0f} "
        f"${d['final_capital']['p25']:>9,.0f} "
        f"${d['final_capital']['median']:>9,.0f} "
        f"${d['final_capital']['p75']:>9,.0f} "
        f"${d['final_capital']['p95']:>9,.0f}",
        f"{'Max DD:':14s} "
        f"{d['max_drawdown_pct']['p5']:>9.1f}% "
        f"{d['max_drawdown_pct']['p25']:>9.1f}% "
        f"{d['max_drawdown_pct']['median']:>9.1f}% "
        f"{d['max_drawdown_pct']['p75']:>9.1f}% "
        f"{d['max_drawdown_pct']['p95']:>9.1f}%",
        f"{'Sharpe:':14s} "
        f"{d['sharpe_ratio']['p5']:>10.2f} "
        f"{d['sharpe_ratio']['p25']:>10.2f} "
        f"{d['sharpe_ratio']['median']:>10.2f} "
        f"{d['sharpe_ratio']['p75']:>10.2f} "
        f"{d['sharpe_ratio']['p95']:>10.2f}",
        "",
        "CONFIDENCE ANALYSIS:",
        f"  Probability of Profit:       {c['prob_profitable']:.1f}%",
        f"  Probability of Ruin:         {c['probability_of_ruin']:.1f}%",
        f"  Probability 2x Return:       {c['prob_achieving_2x_return']:.1f}%",
        f"  Original beats X% of sims:   {100.0 - c['prob_better_than_original']:.1f}%",
        f"  5% Value at Risk:            ${c['value_at_risk_5pct']:,.0f}",
        f"  Expected Shortfall (CVaR):   ${c['expected_shortfall']:,.0f}",
        f"  Worst-case Max DD (p5):      {c['worst_case_max_drawdown']:.1f}%",
        "",
        f"VERDICT: {mc['verdict']}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def _load_result_from_json(path: str) -> BacktestResult:
    """Load a backtest JSON file and reconstruct a BacktestResult object."""
    with open(path, "r") as f:
        data = json.load(f)

    # Support two JSON formats:
    #  1. Full BacktestResult.to_dict() output (has 'trades' key with full trade dicts)
    #  2. Simplified format from run_backtest.py (has 'trades_list' with {entry_date, exit_date, pnl})

    trades: List[Trade] = []

    if "trades" in data and data["trades"]:
        # Full format
        for td in data["trades"]:
            from datetime import datetime
            entry_dt = datetime.fromisoformat(td["entry_date"]) if td.get("entry_date") else datetime.now()
            exit_dt = datetime.fromisoformat(td["exit_date"]) if td.get("exit_date") else None
            trades.append(Trade(
                entry_date=entry_dt,
                symbol=td.get("symbol", data.get("symbol", "UNK")),
                direction=td.get("direction", "long"),
                entry_price=td.get("entry_price", 0.0),
                stop_price=td.get("stop_price", 0.0),
                target_1=td.get("target_1", 0.0),
                target_2=td.get("target_2", 0.0),
                contracts=td.get("contracts", 1),
                multiplier=td.get("multiplier", 1.0),
                exit_date=exit_dt,
                exit_price=td.get("exit_price"),
                pnl=td.get("pnl", 0.0),
                pnl_pct=td.get("pnl_pct", 0.0),
                exit_reason=td.get("exit_reason", ""),
                holding_bars=td.get("holding_bars", 0),
                regime=td.get("regime", ""),
                bias=td.get("bias", ""),
            ))
    elif "trades_list" in data and data["trades_list"]:
        # Simplified format
        from datetime import datetime
        symbol = data.get("symbol", "UNK")
        for td in data["trades_list"]:
            entry_dt = datetime.fromisoformat(td["entry_date"]) if td.get("entry_date") else datetime.now()
            exit_dt = datetime.fromisoformat(td["exit_date"]) if td.get("exit_date") else None
            trades.append(Trade(
                entry_date=entry_dt,
                symbol=symbol,
                direction="long",
                entry_price=0.0,
                stop_price=0.0,
                target_1=0.0,
                target_2=0.0,
                contracts=1,
                multiplier=1.0,
                exit_date=exit_dt,
                pnl=td.get("pnl", 0.0),
            ))

    initial_capital = data.get("initial_capital", 100_000.0)
    total_pnl = sum(t.pnl for t in trades)

    result = BacktestResult(
        symbol=data.get("symbol", "UNK"),
        start_date=data.get("start_date", data.get("start", "")),
        end_date=data.get("end_date", data.get("end", "")),
        initial_capital=initial_capital,
        final_capital=data.get("final_capital", initial_capital + total_pnl),
        trades=trades,
        total_trades=len(trades),
        total_pnl=total_pnl,
        total_return_pct=data.get("total_return_pct", data.get("total_return", 0.0)),
        sharpe_ratio=data.get("sharpe_ratio", data.get("sharpe", 0.0)),
        profit_factor=data.get("profit_factor", data.get("profit_factor", 0.0)),
        win_rate=data.get("win_rate", 0.0),
    )

    return result


def main():
    parser = argparse.ArgumentParser(description="Monte Carlo simulation on backtest results")
    parser.add_argument("--result", required=True, help="Path to backtest result JSON file")
    parser.add_argument("--n-sims", type=int, default=1_000, help="Number of simulations (default: 1000)")
    parser.add_argument("--capital", type=float, default=100_000.0, help="Initial capital (default: 100000)")
    parser.add_argument("--max-slippage", type=float, default=0.0, help="Max random slippage per trade in ticks (default: 0)")
    parser.add_argument("--symbol", default="MES", help="Instrument symbol for tick value (default: MES)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed (default: 42)")
    args = parser.parse_args()

    # Load result
    result_path = Path(args.result)
    if not result_path.exists():
        print(f"ERROR: File not found: {result_path}")
        sys.exit(1)

    print(f"Loading backtest results from {result_path} ...")
    bt_result = _load_result_from_json(str(result_path))
    print(f"  {len(bt_result.trades)} trades loaded for {bt_result.symbol}")

    # Run simulation
    print(f"Running {args.n_sims:,} Monte Carlo simulations...")
    if args.max_slippage > 0:
        print(f"  Slippage: uniform 0-{args.max_slippage} ticks ({args.symbol})")
    mc = run_monte_carlo(
        bt_result,
        n_simulations=args.n_sims,
        initial_capital=args.capital,
        max_slippage_ticks=args.max_slippage,
        symbol=args.symbol,
        seed=args.seed,
    )

    # Print report
    print()
    print(format_report(mc))

    # Save JSON output
    symbol = bt_result.symbol
    # Derive interval from filename if possible
    interval = "1h"
    stem = result_path.stem
    for itv in ("1h", "1d", "5m", "15m", "30m", "4h"):
        if itv in stem:
            interval = itv
            break

    out_path = result_path.parent / f"{symbol}_{interval}_monte_carlo.json"
    with open(out_path, "w") as f:
        json.dump(mc, f, indent=2)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()
