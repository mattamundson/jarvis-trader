#!/usr/bin/env python3
"""Backtest Results Comparison Tool — JARVIS TRADER."""

import argparse
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

VALIDATION_GATES = {
    "profit_factor": 2.0,
    "sharpe": 1.5,
    "win_rate": 0.55,
    "max_drawdown": 0.15,
}


def extract_metrics(data: dict) -> Optional[dict]:
    """Extract key metrics from backtest result JSON."""
    try:
        if not data.get("symbol") or not data.get("interval"):
            return None
        m = data.get("full_metrics", data)
        return {
            "symbol": data.get("symbol"),
            "timeframe": data.get("interval"),
            "profit_factor": m.get("profit_factor", "N/A"),
            "sharpe": m.get("sharpe_ratio", "N/A"),
            "win_rate": m.get("win_rate", "N/A"),
            "total_return_pct": m.get("total_return_pct", "N/A"),
            "max_drawdown": m.get("max_drawdown_pct", "N/A"),
            "trade_count": m.get("total_trades", "N/A"),
            "date": data.get("run_date", "unknown"),
        }
    except Exception as e:
        logger.warning(f"Extract failed: {e}")
        return None


def check_passes_validation(row: dict) -> bool:
    """Check if row passes ALL validation gates."""
    for metric, gate in VALIDATION_GATES.items():
        val = row.get(metric)
        if val == "N/A" or val is None:
            return False
        if metric == "max_drawdown" and val > gate:
            return False
        if metric != "max_drawdown" and val < gate:
            return False
    return True


def format_metric(val: Any) -> str:
    """Format metric for display."""
    if val == "N/A" or val is None:
        return "N/A"
    if isinstance(val, float):
        if 0.01 < abs(val) < 1000:
            return f"{val:.2f}"
        else:
            return f"{val:.4f}"
    return str(val)


def load_results_from_directory(results_dir: str) -> list:
    """Scan directory for JSON files and extract metrics."""
    results = []
    results_path = Path(results_dir)

    if not results_path.exists():
        logger.error(f"Results directory not found: {results_dir}")
        return results

    json_files = list(results_path.glob("*.json"))
    logger.info(f"Found {len(json_files)} JSON files in {results_dir}")

    for json_file in json_files:
        try:
            with open(json_file, "r") as f:
                data = json.load(f)

            # Handle single result or matrix of results
            if isinstance(data, dict):
                if "results" in data and isinstance(data["results"], list):
                    for result in data["results"]:
                        metrics = extract_metrics(result)
                        if metrics:
                            results.append(metrics)
                else:
                    metrics = extract_metrics(data)
                    if metrics:
                        results.append(metrics)
        except json.JSONDecodeError:
            logger.warning(f"Skipping {json_file.name}: invalid JSON")
        except Exception as e:
            logger.warning(f"Skipping {json_file.name}: {e}")

    return results


def generate_markdown_table(results: list, output_path: str) -> None:
    """Generate markdown comparison table sorted by Sharpe ratio."""
    def sharpe_key(row):
        val = row.get("sharpe", "N/A")
        return float(val) if val != "N/A" else float("-inf")

    sorted_results = sorted(results, key=sharpe_key, reverse=True)
    lines = [
        "# Backtest Results Comparison — JARVIS TRADER\n",
        f"Generated: {datetime.now().isoformat()}\n",
        f"Total Results: {len(sorted_results)}\n",
        "",
        "**Validation Gates**: PF >= 2.0, Sharpe >= 1.5, WR >= 55%, DD <= 15%",
        "Rows marked with **PASS** meet ALL gates.",
        "",
        "| Symbol | TF | Profit Factor | Sharpe | Win Rate | Total Return | Max DD | Trades | Status |",
        "|--------|----|--------------:|-------:|----------:|-------------:|-------:|-------:|--------|",
    ]
    for row in sorted_results:
        status = "**PASS**" if check_passes_validation(row) else ""
        lines.append(
            f"| {row.get('symbol', '?')} | {row.get('timeframe', '?')} | "
            f"{format_metric(row.get('profit_factor')):>14} | "
            f"{format_metric(row.get('sharpe')):>7} | "
            f"{format_metric(row.get('win_rate')):>10} | "
            f"{format_metric(row.get('total_return_pct')):>13} | "
            f"{format_metric(row.get('max_drawdown')):>7} | "
            f"{format_metric(row.get('trade_count')):>7} | {status} |"
        )
    lines.extend([
        "", "## Metrics Legend\n",
        "- **Profit Factor**: Gross profit / Gross loss (>= 2.0 PASS)",
        "- **Sharpe**: Risk-adjusted return (>= 1.5 PASS)",
        "- **Win Rate**: % of profitable trades (>= 55% PASS)",
        "- **Total Return**: % gain/loss over period",
        "- **Max DD**: Maximum drawdown (>= 15% FAIL)",
        "- **Trades**: Total trade count",
    ])
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write("\n".join(lines))
    logger.info(f"Markdown table written to {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Backtest Results Comparison Tool — JARVIS TRADER"
    )
    parser.add_argument(
        "--results-dir",
        default="engine/backtest/results/",
        help="Path to backtest results directory (default: engine/backtest/results/)",
    )
    parser.add_argument(
        "--output",
        default="docs/reports/BACKTEST_COMPARISON.md",
        help="Output markdown path (default: docs/reports/BACKTEST_COMPARISON.md)",
    )

    args = parser.parse_args()

    logger.info(f"Loading backtest results from {args.results_dir}")
    results = load_results_from_directory(args.results_dir)

    if not results:
        logger.warning("No valid backtest results found.")
        return

    logger.info(f"Loaded {len(results)} backtest results")
    generate_markdown_table(results, args.output)

    passes = sum(1 for r in results if check_passes_validation(r))
    logger.info(f"{passes}/{len(results)} results PASS all validation gates")


if __name__ == "__main__":
    main()
