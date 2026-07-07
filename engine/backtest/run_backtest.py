"""
JARVIS TRADER — Backtest CLI Runner

Usage (from engine/ directory):
    .venv/Scripts/python backtest/run_backtest.py --symbol MES --start 2024-01-01 --end 2026-03-31
    .venv/Scripts/python backtest/run_backtest.py --symbol MES --start 2024-01-01 --capital 50000
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="JARVIS TRADER Backtester",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--symbol", default="SPY", help="Symbol to backtest")
    parser.add_argument("--start", default="2024-01-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", default="2025-12-31", help="End date (YYYY-MM-DD)")
    parser.add_argument("--interval", default="1d", help="Data interval (1d, 1h, 15m, etc.)")
    parser.add_argument("--capital", type=float, default=10_000.0, help="Initial capital")
    parser.add_argument("--risk", type=float, default=0.01, help="Risk per trade (fraction)")
    parser.add_argument("--output", default=None, help="Save JSON results to file")
    args = parser.parse_args()

    print("JARVIS TRADER Backtester")
    print(f"Symbol: {args.symbol} | Period: {args.start} -> {args.end}")
    print(f"Capital: ${args.capital:,.0f} | Risk/trade: {args.risk:.1%}")
    print("-" * 50)

    try:
        from backtest.backtester import Backtester
        from backtest.data_loader import BacktestDataLoader
        from backtest.signals import generate_signals
    except ImportError as e:
        print(f"[ERROR] Import failed: {e}")
        print("Make sure you're running from the engine/ directory.")
        sys.exit(1)

    # Load data
    loader = BacktestDataLoader()
    print(f"Loading {args.symbol} data...")
    df = loader.load(args.symbol, args.start, args.end, args.interval)

    if df is None or df.empty:
        print(f"[ERROR] No data returned for {args.symbol}")
        sys.exit(1)

    print(f"Loaded {len(df)} bars. Computing signals...")

    # Generate signals
    df = generate_signals(df)

    entry_count = (df["entry_signal"] == "ENTRY_NOW").sum()
    print(f"Found {entry_count} ENTRY_NOW signals out of {len(df)} bars.")

    # Run backtest
    multiplier = loader.get_multiplier(args.symbol)
    backtester = Backtester(
        initial_capital=args.capital,
        risk_per_trade=args.risk,
    )

    print("Running simulation...")
    result = backtester.run(df, args.symbol, multiplier)

    # Print summary
    print("\n" + result.summary())

    # Auto-save JSON to backtest/results/
    engine_root = Path(__file__).parent.parent
    results_dir = engine_root / "backtest" / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    auto_filename = f"{args.symbol}_{args.interval}_{args.start}_{args.end}.json"
    auto_path = results_dir / auto_filename

    result_data = result.to_dict()
    # Ensure canonical top-level fields match spec
    json_payload = {
        "symbol": result_data["symbol"],
        "interval": args.interval,
        "start": args.start,
        "end": args.end,
        "n_trades": result_data["total_trades"],
        "win_rate": result_data["win_rate"],
        "profit_factor": result_data["profit_factor"],
        "sharpe": result_data["sharpe_ratio"],
        "total_return": result_data["total_return_pct"],
        "trades_list": [
            {
                "entry_date": t["entry_date"],
                "exit_date": t["exit_date"],
                "pnl": t["pnl"],
            }
            for t in result_data["trades"]
        ],
        # Full metrics included for completeness
        "full_metrics": result_data,
    }

    with open(auto_path, "w") as f:
        json.dump(json_payload, f, indent=2)
    print(f"\nResults saved to: {auto_path}")

    # Save if --output explicitly requested as well
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(result.to_dict(), f, indent=2)
        print(f"Results also saved to: {output_path}")

    return result


if __name__ == "__main__":
    main()
