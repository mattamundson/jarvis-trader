"""
Strategy Lab Router — auto-generated scaffold.
Full implementation pending strategy_lab module.
"""
from fastapi import APIRouter, BackgroundTasks

router = APIRouter(prefix="/strategy/lab", tags=["strategy/lab"])


@router.post("/strategy-lab/run")
async def start_strategy_lab(
    background_tasks: BackgroundTasks,
    symbol: str = "MES",
    max_iterations: int = 20,
    start: str = "2024-06-01",
    end: str = "2026-03-27",
):
    """Start the LLM autonomous strategy improvement loop (not yet implemented)."""
    return {
        "status": "not_implemented",
        "message": "Strategy lab is pending full implementation. Check back soon.",
    }


@router.get("/strategy-lab/results")
async def get_strategy_lab_results():
    """Return best strategies found by strategy lab (not yet implemented)."""
    import json
    from pathlib import Path

    best_file = Path("backtest/results/strategy_lab_best.json")
    best = json.loads(best_file.read_text()) if best_file.exists() else []
    return {
        "best_strategies": best,
        "message": "No results yet. POST /strategy-lab/run to start." if not best else f"Top {len(best)} strategies shown.",
    }
