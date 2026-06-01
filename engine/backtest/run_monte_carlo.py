"""
JARVIS TRADER — Monte Carlo CLI Runner
=====================================

Run Monte Carlo simulations on backtest results with optional slippage modeling.

Usage (from engine/ directory):
    .venv/Scripts/python backtest/run_monte_carlo.py --results-file results/MES_1h_2024-06-01_2026-03-27.json --simulations 1000 --max-slippage 2

Examples:
    # Basic: 1000 simulations, no slippage
    .venv/Scripts/python backtest/run_monte_carlo.py --results-file results/MES_1h_2024-06-01_2026-03-27.json

    # With slippage: 1000 sims, uniform 0-2 ticks per trade (MES)
    .venv/Scripts/python backtest/run_monte_carlo.py --results-file results/MES_1h_2024-06-01_2026-03-27.json --simulations 1000 --max-slippage 2

    # Different symbol: MCL with 1 tick slippage
    .venv/Scripts/python backtest/run_monte_carlo.py --results-file results/MCL_1h_2024-06-01_2026-03-27.json --symbol MCL --max-slippage 1
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from backtest.monte_carlo import _load_result_from_json, format_report, run_monte_carlo


def main():
    parser = argparse.ArgumentParser(
        description="Monte Carlo simulation runner for JARVIS TRADER backtest results",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--results-file",
        required=True,
        help="Path to backtest result JSON file (relative to engine/ or absolute)",
    )
    parser.add_argument(
        "--simulations",
        type=int,
        default=1_000,
        help="Number of simulations to run (default: 1000)",
    )
    parser.add_argument(
        "--max-slippage",
        type=float,
        default=0.0,
        help="Max random slippage per trade in ticks, uniform 0 to N (default: 0, no slippage)",
    )
    parser.add_argument(
        "--symbol",
        default=None,
        help="Instrument symbol for tick value lookup (auto-detected from filename if not provided)",
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=10_000.0,
        help="Initial capital for simulation (default: 10000)",
    )
    parser.add_argument(
        "--seed", type=int, default=42, help="Random seed for reproducibility (default: 42)"
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Save results to custom path (default: auto-generated in results/)",
    )
    args = parser.parse_args()

    # Resolve file path
    results_file = Path(args.results_file)
    if not results_file.is_absolute():
        # Try relative to current dir, then relative to engine/backtest/results/
        if not results_file.exists():
            alt_path = Path(__file__).parent / "results" / results_file.name
            if alt_path.exists():
                results_file = alt_path

    if not results_file.exists():
        print(f"ERROR: Results file not found: {results_file}")
        sys.exit(1)

    # Auto-detect symbol from filename if not provided
    symbol = args.symbol
    if not symbol:
        # Extract from filename: e.g., "MES_1h_2024-06-01_2026-03-27.json" -> "MES"
        stem = results_file.stem
        for part in stem.split("_"):
            if part.isupper() and len(part) <= 4:
                symbol = part
                break
        if not symbol:
            symbol = "MES"

    interval = "1h"
    stem = results_file.stem
    for itv in ("1h", "1d", "5m", "15m", "30m", "4h"):
        if itv in stem:
            interval = itv
            break

    print(f"{'=' * 70}")
    print("JARVIS TRADER — Monte Carlo Simulation Runner")
    print(f"{'=' * 70}")
    print(f"Results file: {results_file}")
    print(f"Symbol:       {symbol}")
    print(f"Interval:     {interval}")
    print(f"Simulations:  {args.simulations:,}")
    if args.max_slippage > 0:
        print(f"Slippage:     Uniform 0-{args.max_slippage} ticks per trade")
    print(f"Capital:      ${args.capital:,.0f}")
    print(f"{'=' * 70}")
    print()

    # Load backtest result
    try:
        print("Loading backtest results...")
        bt_result = _load_result_from_json(str(results_file))
        print(f"  Loaded {bt_result.total_trades} trades for {bt_result.symbol}")
    except Exception as e:
        print(f"ERROR: Failed to load results: {e}")
        sys.exit(1)

    # Run simulation
    print(f"Running {args.simulations:,} Monte Carlo simulations...")
    start_time = time.time()
    try:
        mc_results = run_monte_carlo(
            bt_result,
            n_simulations=args.simulations,
            initial_capital=args.capital,
            max_slippage_ticks=args.max_slippage,
            symbol=symbol,
            seed=args.seed,
        )
    except Exception as e:
        print(f"ERROR: Simulation failed: {e}")
        sys.exit(1)

    elapsed = time.time() - start_time
    print(f"  Completed in {elapsed:.2f} seconds")
    print()

    # Print formatted report
    print(format_report(mc_results))
    print()

    # Determine output path
    if args.output:
        output_path = Path(args.output)
    else:
        results_dir = results_file.parent
        mode_tag = ""
        if args.max_slippage > 0:
            mode_tag = f"_slip{int(args.max_slippage)}tk"
        output_filename = f"{symbol}_{interval}_monte_carlo{mode_tag}.json"
        output_path = results_dir / output_filename

    # Save results
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(output_path, "w") as f:
            json.dump(mc_results, f, indent=2)
        print(f"Results saved: {output_path}")
    except Exception as e:
        print(f"ERROR: Failed to save results: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
