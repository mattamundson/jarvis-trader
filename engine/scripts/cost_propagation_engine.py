"""
JARVIS TRADER — Cost Propagation Engine
Automates the update of backtest/research results when commission or slippage assumptions change.
Ensures that 'Gate v2' verdicts remain accurate under shifting market friction.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Dict, List

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cost_propagation")

def recalculate_stats(pnls: List[float]) -> Dict[str, float]:
    """Recalculate aggregate stats from a list of PnLs."""
    if not pnls:
        return {"pf": 0.0, "net_pnl": 0.0, "expectancy": 0.0}

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))

    pf = gross_win / gross_loss if gross_loss > 0 else 99.9  # cap inf
    net_pnl = sum(pnls)
    expectancy = net_pnl / len(pnls)

    return {
        "pf": round(pf, 3),
        "net_pnl": round(net_pnl, 2),
        "expectancy": round(expectancy, 4),
        "n_trades": len(pnls)
    }

def propagate_costs(
    file_path: Path,
    new_commission: float,
    new_slippage: float,
    old_commission: float = 0.0,
    old_slippage: float = 0.0,
    dry_run: bool = False
):
    """
    Adjust PnL for all trades in a results JSON and update stats.
    Assumes PnL in JSON already includes old_commission and old_slippage.
    """
    if not file_path.exists():
        logger.error("File not found: %s", file_path)
        return

    with open(file_path, "r") as f:
        data = json.load(f)

    # Delta per trade (points or dollars depending on backtester)
    # Most JARVIS backtest results store raw PnL after costs.
    # We need to know if the PnL is in POINTS or DOLLARS.
    # Usually it is in DOLLARS for the 'results' array.

    cost_delta = (new_commission + new_slippage) - (old_commission + old_slippage)

    results = data.get("results", [])
    logger.info("Propagating cost delta -$%.2f per trade across %d combinations in %s",
                cost_delta, len(results), file_path.name)

    for combo in results:
        trades = combo.get("trades", [])
        if not trades:
            continue

        new_pnls = []
        for trade in trades:
            # Adjust the PnL of each trade
            # Note: We subtract the delta because higher cost = lower PnL
            trade["pnl"] = round(trade["pnl"] - cost_delta, 2)
            new_pnls.append(trade["pnl"])

        # Update combo stats
        stats = recalculate_stats(new_pnls)
        combo["pf"] = stats["pf"]
        combo["net_pnl"] = stats["net_pnl"]
        # Update expectancy if present
        if "expectancy" in combo:
            combo["expectancy"] = stats["expectancy"]

    if not dry_run:
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2)
        logger.info("Successfully updated %s", file_path)
    else:
        logger.info("[DRY RUN] Would have updated %s", file_path)

def main():
    parser = argparse.ArgumentParser(description="Propagate new cost assumptions to research results.")
    parser.add_argument("--file", required=True, help="Path to the JSON results file")
    parser.add_argument("--new-comm", type=float, required=True, help="New commission per trade ($)")
    parser.add_argument("--new-slip", type=float, required=True, help="New slippage per trade ($)")
    parser.add_argument("--old-comm", type=float, default=0.0, help="Current commission included in PnL")
    parser.add_argument("--old-slip", type=float, default=0.0, help="Current slippage included in PnL")
    parser.add_argument("--dry-run", action="store_true", help="Don't write to file")

    args = parser.parse_args()
    propagate_costs(
        Path(args.file),
        args.new_comm,
        args.new_slip,
        args.old_comm,
        args.old_slip,
        args.dry_run
    )

if __name__ == "__main__":
    main()
