#!/usr/bin/env python
"""
JARVIS TRADER -- Full Backtesting Matrix
Runs all symbol/timeframe combinations and produces comparison report.

Usage (from engine/ directory):
    .venv/Scripts/python backtest/run_all_backtests.py
    .venv/Scripts/python backtest/run_all_backtests.py --symbols MES MGC --intervals 1h 1d
    .venv/Scripts/python backtest/run_all_backtests.py --compare-old
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SYMBOLS = ["SPY", "MES", "MNQ", "MCL", "MGC", "M2K"]
INTERVALS = ["1h", "1d"]

# Date windows per interval
INTERVAL_DATES: Dict[str, Tuple[str, str]] = {
    "1h": ("2024-06-01", "2026-03-27"),
    "4h": ("2024-06-01", "2026-03-27"),
    "1d": ("2025-01-01", "2026-03-27"),
}

DEFAULT_CAPITAL = 10_000.0
RESULTS_DIR = Path(__file__).parent / "results"


# ---------------------------------------------------------------------------
# Single backtest runner
# ---------------------------------------------------------------------------


def run_single_backtest(
    symbol: str,
    interval: str,
    start: str,
    end: str,
    capital: float = DEFAULT_CAPITAL,
) -> Dict[str, Any]:
    """
    Run one backtest and return a result dict.
    On failure returns a dict with status='ERROR' and an error message.
    """
    from backtest.backtester import Backtester
    from backtest.data_loader import BacktestDataLoader
    from backtest.signals import generate_signals

    t0 = time.time()
    result_row: Dict[str, Any] = {
        "symbol": symbol,
        "interval": interval,
        "start": start,
        "end": end,
        "status": "OK",
        "error": None,
        "bars": 0,
        "trades": 0,
        "win_rate": 0.0,
        "profit_factor": 0.0,
        "sharpe": 0.0,
        "sortino": 0.0,
        "total_return_pct": 0.0,
        "max_drawdown_pct": 0.0,
        "elapsed_sec": 0.0,
        "full_result": None,
    }

    try:
        loader = BacktestDataLoader()
        df = loader.load(symbol, start, end, interval)

        if df is None or df.empty:
            result_row["status"] = "NO_DATA"
            result_row["error"] = f"No data returned for {symbol} ({interval})"
            result_row["elapsed_sec"] = round(time.time() - t0, 2)
            return result_row

        result_row["bars"] = len(df)

        # Generate signals
        df = generate_signals(df)

        # Run backtest
        multiplier = loader.get_multiplier(symbol)
        backtester = Backtester(initial_capital=capital)
        bt_result = backtester.run(df, symbol, multiplier)

        # Populate summary metrics
        result_row["trades"] = bt_result.total_trades
        result_row["win_rate"] = round(bt_result.win_rate * 100, 1)
        result_row["profit_factor"] = round(bt_result.profit_factor, 2)
        result_row["sharpe"] = round(bt_result.sharpe_ratio, 2)
        result_row["sortino"] = round(bt_result.sortino_ratio, 2)
        result_row["total_return_pct"] = round(bt_result.total_return_pct * 100, 1)
        result_row["max_drawdown_pct"] = round(bt_result.max_drawdown_pct * 100, 1)
        result_row["full_result"] = bt_result.to_dict()

    except Exception as exc:
        result_row["status"] = "ERROR"
        result_row["error"] = str(exc)

    result_row["elapsed_sec"] = round(time.time() - t0, 2)
    return result_row


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------


def print_matrix_table(results: List[Dict[str, Any]], capital: float) -> None:
    """Print the formatted comparison table to stdout."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    print()
    print("=" * 90)
    print("  JARVIS TRADER -- BACKTEST MATRIX")
    print(f"  Date: {now_str}  |  Capital: ${capital:,.0f}")
    print("=" * 90)

    header = (
        f"{'Symbol':<8}{'TF':<5}{'Bars':>6}{'Trades':>8}"
        f"{'WR%':>7}{'PF':>7}{'Sharpe':>8}{'Return%':>10}"
        f"{'MaxDD%':>8}  {'Status':<8}"
    )
    print(header)
    print("-" * 90)

    for r in results:
        if r["status"] != "OK":
            status_str = r["status"]
            print(
                f"{r['symbol']:<8}{r['interval']:<5}"
                f"{'--':>6}{'--':>8}{'--':>7}{'--':>7}{'--':>8}"
                f"{'--':>10}{'--':>8}  {status_str:<8}"
            )
        else:
            ret_str = f"{r['total_return_pct']:+.1f}%"
            dd_str = f"{r['max_drawdown_pct']:.1f}%"
            pf_str = f"{r['profit_factor']:.2f}" if r["profit_factor"] < 999 else "Inf"
            print(
                f"{r['symbol']:<8}{r['interval']:<5}"
                f"{r['bars']:>6}{r['trades']:>8}"
                f"{r['win_rate']:>6.1f}%{pf_str:>7}{r['sharpe']:>8.2f}"
                f"{ret_str:>10}{dd_str:>8}  {'OK':<8}"
            )

    print("-" * 90)

    # Summary row
    ok_results = [r for r in results if r["status"] == "OK"]
    if ok_results:
        total_time = sum(r["elapsed_sec"] for r in results)
        avg_sharpe = sum(r["sharpe"] for r in ok_results) / len(ok_results)
        avg_return = sum(r["total_return_pct"] for r in ok_results) / len(ok_results)
        print(
            f"  {len(ok_results)}/{len(results)} completed  |"
            f"  Avg Sharpe: {avg_sharpe:.2f}  |"
            f"  Avg Return: {avg_return:+.1f}%  |"
            f"  Total time: {total_time:.1f}s"
        )
    print("=" * 90)
    print()


def print_comparison_table(
    new_results: List[Dict[str, Any]],
    old_results: Dict[str, Dict[str, Any]],
) -> None:
    """Print before/after comparison table."""
    print()
    print("=" * 100)
    print("  BEFORE/AFTER BUG FIXES")
    print("=" * 100)
    header = (
        f"{'Symbol':<8}{'TF':<5}"
        f"  | {'OLD PF':>8}{'NEW PF':>9}"
        f"  | {'OLD Sharpe':>11}{'NEW Sharpe':>12}"
        f"  | {'OLD Return':>11}{'NEW Return':>12}"
    )
    print(header)
    print("-" * 100)

    matched = 0
    for r in new_results:
        key = f"{r['symbol']}_{r['interval']}"
        old = old_results.get(key)
        if old is None:
            continue
        matched += 1

        old_pf = old.get("profit_factor", 0)
        old_sharpe = old.get("sharpe", 0)
        old_return = old.get("total_return", 0)
        # Old results store return as fraction (0.155 = 15.5%) -- convert to %
        if abs(old_return) < 5:
            old_return_pct = old_return * 100
        else:
            old_return_pct = old_return

        new_pf = r["profit_factor"] if r["status"] == "OK" else 0
        new_sharpe = r["sharpe"] if r["status"] == "OK" else 0
        new_return = r["total_return_pct"] if r["status"] == "OK" else 0

        old_pf_str = f"{old_pf:.2f}" if old_pf < 999 else "Inf"
        new_pf_str = (
            f"{new_pf:.2f}"
            if r["status"] == "OK" and new_pf < 999
            else ("Inf" if r["status"] == "OK" else "N/A")
        )

        print(
            f"{r['symbol']:<8}{r['interval']:<5}"
            f"  | {old_pf_str:>8}{new_pf_str:>9}"
            f"  | {old_sharpe:>11.2f}{new_sharpe:>12.2f}"
            f"  | {old_return_pct:>+10.1f}%{new_return:>+11.1f}%"
        )

    if matched == 0:
        print("  No matching old results found for comparison.")

    print("=" * 100)
    print()


# ---------------------------------------------------------------------------
# Load old results from JSON files in results/
# ---------------------------------------------------------------------------


def load_old_results() -> Dict[str, Dict[str, Any]]:
    """
    Scan results/ for existing JSON files and return a lookup dict keyed by
    '{SYMBOL}_{INTERVAL}', e.g. 'SPY_1h'.
    """
    old: Dict[str, Dict[str, Any]] = {}
    if not RESULTS_DIR.exists():
        return old

    for path in RESULTS_DIR.glob("*.json"):
        try:
            with open(path) as f:
                data = json.load(f)

            sym = data.get("symbol", "")
            interval = data.get("interval", "")
            if not sym or not interval:
                # Try to parse from filename: SPY_1h_2024-06-01_2026-03-27.json
                parts = path.stem.split("_")
                if len(parts) >= 2:
                    sym = parts[0]
                    interval = parts[1]

            if sym and interval:
                key = f"{sym}_{interval}"
                # Only keep the first one found (or overwrite with newer)
                old[key] = data
        except Exception:
            continue

    return old


# ---------------------------------------------------------------------------
# Save results
# ---------------------------------------------------------------------------


def save_matrix_results(results: List[Dict[str, Any]], capital: float) -> Path:
    """Save the full matrix to a timestamped JSON file."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    matrix_path = RESULTS_DIR / f"MATRIX_{date_str}.json"

    payload = {
        "run_date": datetime.now().isoformat(),
        "capital": capital,
        "results": [],
    }

    for r in results:
        entry = {k: v for k, v in r.items() if k != "full_result"}
        if r.get("full_result"):
            entry["full_metrics"] = r["full_result"]
        payload["results"].append(entry)

    with open(matrix_path, "w") as f:
        json.dump(payload, f, indent=2, default=str)

    print(f"[Matrix] Saved to: {matrix_path}")
    return matrix_path


def save_per_symbol_results(results: List[Dict[str, Any]]) -> None:
    """Save individual corrected result files per symbol/interval."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    for r in results:
        if r["status"] != "OK" or not r.get("full_result"):
            continue

        filename = f"{r['symbol']}_{r['interval']}_backtest_corrected.json"
        path = RESULTS_DIR / filename

        payload = {
            "symbol": r["symbol"],
            "interval": r["interval"],
            "start": r["start"],
            "end": r["end"],
            "n_trades": r["trades"],
            "win_rate": r["win_rate"] / 100.0,  # store as fraction
            "profit_factor": r["profit_factor"],
            "sharpe": r["sharpe"],
            "sortino": r["sortino"],
            "total_return": r["total_return_pct"] / 100.0,  # store as fraction
            "max_drawdown": r["max_drawdown_pct"] / 100.0,
            "elapsed_sec": r["elapsed_sec"],
            "full_metrics": r["full_result"],
        }

        with open(path, "w") as f:
            json.dump(payload, f, indent=2, default=str)

        print(f"[Matrix] Saved: {filename}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="JARVIS TRADER -- Full Backtest Matrix Runner",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=None,
        help=f"Symbols to backtest (default: {SYMBOLS})",
    )
    parser.add_argument(
        "--intervals",
        nargs="+",
        default=None,
        help=f"Intervals to backtest (default: {INTERVALS})",
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=DEFAULT_CAPITAL,
        help="Initial capital",
    )
    parser.add_argument(
        "--compare-old",
        action="store_true",
        help="Load old JSON results from results/ and show before/after comparison",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Skip saving results to disk",
    )
    args = parser.parse_args()

    symbols = args.symbols if args.symbols else SYMBOLS
    intervals = args.intervals if args.intervals else INTERVALS

    # Build the backtest matrix
    matrix: List[Tuple[str, str, str, str]] = []
    for interval in intervals:
        dates = INTERVAL_DATES.get(interval)
        if dates is None:
            print(f"[WARN] No date range configured for interval '{interval}', skipping.")
            continue
        start, end = dates
        for symbol in symbols:
            matrix.append((symbol, interval, start, end))

    total = len(matrix)
    print()
    print("JARVIS TRADER -- Backtest Matrix Runner")
    print(f"  Symbols:   {', '.join(symbols)}")
    print(f"  Intervals: {', '.join(intervals)}")
    print(f"  Capital:   ${args.capital:,.0f}")
    print(f"  Total backtests: {total}")
    print()

    # Run all backtests
    all_results: List[Dict[str, Any]] = []
    t_start = time.time()

    for i, (symbol, interval, start, end) in enumerate(matrix, 1):
        print(f"[{i}/{total}] Running {symbol} {interval} ({start} -> {end})...")
        result = run_single_backtest(symbol, interval, start, end, args.capital)
        all_results.append(result)

        status = result["status"]
        if status == "OK":
            print(
                f"         -> {result['trades']} trades, "
                f"PF {result['profit_factor']:.2f}, "
                f"Sharpe {result['sharpe']:.2f}, "
                f"Return {result['total_return_pct']:+.1f}% "
                f"({result['elapsed_sec']:.1f}s)"
            )
        else:
            err_msg = result.get("error", "unknown")
            print(f"         -> {status}: {err_msg} ({result['elapsed_sec']:.1f}s)")

    total_elapsed = time.time() - t_start

    # Print the matrix table
    print_matrix_table(all_results, args.capital)
    print(f"  Total elapsed: {total_elapsed:.1f}s")

    # Before/After comparison
    if args.compare_old:
        old_results = load_old_results()
        if old_results:
            print_comparison_table(all_results, old_results)
        else:
            print("[WARN] No old results found in results/ for comparison.")

    # Save results
    if not args.no_save:
        save_matrix_results(all_results, args.capital)
        save_per_symbol_results(all_results)

    print("\nDone.")


if __name__ == "__main__":
    main()
