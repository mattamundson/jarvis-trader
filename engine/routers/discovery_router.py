"""
JARVIS TRADER — Strategy Discovery Router
API endpoints for strategy registry, listing, and discovery management.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/discovery", tags=["discovery"])

# Lazy singleton — initialized on first access
_registry = None


def _get_registry():
    global _registry
    if _registry is None:
        from strategies.registry import StrategyRegistry

        _registry = StrategyRegistry()
        loaded = _registry.scan_all()
        logger.info(f"Strategy registry initialized: {len(loaded)} strategies loaded")
    return _registry


@router.get("/strategies")
async def list_strategies():
    """List all loaded strategies with metadata."""
    registry = _get_registry()
    return {
        "total": registry.count,
        "strategies": registry.list_all(),
    }


@router.get("/strategies/kept")
async def list_kept_strategies():
    """List only strategies marked keep=True (production-ready)."""
    registry = _get_registry()
    return {
        "kept": registry.list_kept(),
    }


@router.get("/strategies/{name}")
async def get_strategy(name: str):
    """Get a specific strategy by name."""
    registry = _get_registry()
    strategy = registry.get(name)
    if strategy is None:
        raise HTTPException(status_code=404, detail=f"Strategy '{name}' not found")
    return strategy.metadata()


@router.post("/strategies/reload")
async def reload_strategies():
    """Re-scan all strategy directories and reload."""
    global _registry
    from strategies.registry import StrategyRegistry

    _registry = StrategyRegistry()
    loaded = _registry.scan_all()
    return {
        "reloaded": True,
        "total": _registry.count,
        "loaded": loaded,
    }


@router.post("/strategies/load")
async def load_strategy_file(filename: str):
    """Load a specific strategy file from the generated/ directory."""
    registry = _get_registry()
    generated_dir = Path(__file__).parent.parent / "strategies" / "generated"
    path = generated_dir / filename

    if not path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")

    try:
        instance = registry.load_from_file(path)
        return {
            "loaded": True,
            "strategy": instance.metadata(),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/run-cycle")
async def run_discovery_cycle(symbol: str = "MCL", interval: str = "1h"):
    """Trigger one LLM strategy generation + evaluation loop."""
    from strategies.discovery_loop import evaluate_strategy_file, generate_strategy

    # Step 1: Generate strategy via LLM
    try:
        strategy_path = await generate_strategy(symbol=symbol, interval=interval)
    except Exception as e:
        logger.error(f"[discovery] generate_strategy raised: {e}")
        raise HTTPException(status_code=500, detail=f"Strategy generation failed: {e}") from e

    if strategy_path is None:
        raise HTTPException(
            status_code=503,
            detail="Strategy generation returned None — check logs (LLM unavailable or validation failed)",
        )

    filename = Path(strategy_path).name

    # Step 2: Evaluate the new strategy file
    try:
        result = evaluate_strategy_file(filename=filename, symbol=symbol, interval=interval)
    except Exception as e:
        logger.error(f"[discovery] evaluate_strategy_file raised: {e}")
        raise HTTPException(status_code=500, detail=f"Evaluation failed: {e}") from e

    eligible = result.get("verdict") == "ELIGIBLE"
    metrics = {
        k: result.get(k)
        for k in ("sharpe", "calmar", "pf", "num_trades", "win_rate", "max_drawdown_pct")
    }

    return {
        "status": "ok",
        "strategy_file": strategy_path,
        "eligible": eligible,
        "verdict": result.get("verdict"),
        "metrics": metrics,
        "thoughts": result.get("thoughts"),
    }


@router.get("/evaluation/gates")
async def get_evaluation_gates():
    """Return current evaluation harness gate thresholds."""
    from backtest.evaluation_harness import (
        MAX_DRAWDOWN_PCT,
        MIN_CALMAR,
        MIN_EXPOSURE_PCT,
        MIN_PROFIT_FACTOR,
        MIN_SHARPE,
        MIN_TRADES,
    )

    return {
        "layer1_statistical_validity": {
            "min_trades": MIN_TRADES,
            "min_exposure_pct": MIN_EXPOSURE_PCT,
        },
        "layer2_risk_adjusted_return": {
            "min_sharpe": MIN_SHARPE,
            "min_calmar": MIN_CALMAR,
            "min_profit_factor": MIN_PROFIT_FACTOR,
            "max_drawdown_pct": MAX_DRAWDOWN_PCT,
        },
    }
