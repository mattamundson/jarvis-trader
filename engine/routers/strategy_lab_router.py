"""Strategy Lab — LLM-driven autonomous strategy improvement loop."""

import json
import logging
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks

router = APIRouter(prefix="/strategy-lab", tags=["strategy-lab"])
logger = logging.getLogger(__name__)


@router.post("/run")
async def start_strategy_lab(
    background_tasks: BackgroundTasks,
    symbol: str = "MES",
    max_iterations: int = 20,
    start: str = "2024-06-01",
    end: str = "2026-03-27",
):
    """
    Start the LLM autonomous strategy improvement loop in the background.
    Generates STC+ATR strategy variants via Claude, backtests each variant,
    applies dual-gate validation, and saves ELIGIBLE results to disk.\n
    Auth: global X-API-Key middleware enforces authentication.
    """
    from strategy_lab.strategy_loop import run_strategy_loop

    background_tasks.add_task(
        run_strategy_loop,
        symbol=symbol,
        max_iterations=max_iterations,
        start=start,
        end=end,
    )
    return {
        "status": "started",
        "symbol": symbol,
        "max_iterations": max_iterations,
        "message": (
            f"Strategy lab running {max_iterations} iterations on {symbol}. "
            "Check /strategy-lab/results when complete."
        ),
    }


@router.get("/results")
async def get_strategy_lab_results():
    """
    Return the best strategies found by the strategy lab.\n
    Auth: global X-API-Key middleware enforces authentication.
    """
    best_file = Path("backtest/results/strategy_lab_best.json")
    all_file = Path("backtest/results/strategy_lab_results.jsonl")

    best = json.loads(best_file.read_text()) if best_file.exists() else []

    total_evaluated = 0
    eligible_count = 0
    if all_file.exists():
        for line in all_file.read_text().strip().splitlines():
            if line.strip():
                try:
                    r = json.loads(line)
                    total_evaluated += 1
                    if r.get("verdict") == "ELIGIBLE":
                        eligible_count += 1
                except Exception:
                    pass

    return {
        "best_strategies": best,
        "stats": {
            "total_evaluated": total_evaluated,
            "eligible_count": eligible_count,
            "best_pf": max(
                (
                    s.get("metrics", {}).get("profit_factor") or s.get("metrics", {}).get("pf") or 0
                    for s in best
                ),
                default=0,
            ),
        },
        "message": (
            "No results yet. POST /strategy-lab/run to start."
            if not best
            else f"Top {len(best)} strategies shown."
        ),
    }
