"""
JARVIS TRADER — RL Strategy API Router
========================================
Endpoints for RL strategy training, status, and evaluation.

Registered in main.py:
    from routers.strategy_router import router as strategy_router, set_data_manager as set_strategy_dm
    app.include_router(strategy_router, prefix="/strategies", tags=["strategies"])
    set_strategy_dm(data_manager)   # call in lifespan after data_manager init
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from strategies.rl_config import (
    TIMESTEPS_DEFAULT,
    TIMESTEPS_QUICK,
)
from strategies.rl_trainer import RLTrainer, get_training_status

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Module-level trainer (data_manager injected at startup) ───────────────────

_trainer: Optional[RLTrainer] = None


def set_data_manager(data_manager) -> None:
    """Called from main.py lifespan after data_manager is initialized."""
    global _trainer
    _trainer = RLTrainer(data_manager=data_manager)
    logger.info("✅ RL Strategy trainer initialized")


def _get_trainer() -> RLTrainer:
    if _trainer is None:
        # Lazy init without data_manager (yfinance fallback)
        return RLTrainer(data_manager=None)
    return _trainer


# ── Request / Response Models ─────────────────────────────────────────────────

class TrainRequest(BaseModel):
    symbol: str = Field("MES", description="Futures symbol: MES, MNQ, MCL")
    interval: str = Field("1h", description="Bar interval: 1h, 4h, 1d")
    timesteps: int = Field(
        TIMESTEPS_DEFAULT,
        ge=TIMESTEPS_QUICK,
        le=1_000_000,
        description="PPO training timesteps",
    )
    force_recompute: bool = Field(
        False, description="Force re-fetch + recompute indicators"
    )


class EvaluateRequest(BaseModel):
    symbol: str = Field("MES", description="Futures symbol")
    model_path: str = Field(..., description="Path to saved model .zip (without extension)")
    interval: str = Field("1h")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/rl/train")
async def train_rl_strategy(
    req: TrainRequest,
    background_tasks: BackgroundTasks,
) -> dict:
    """
    Start RL agent training in the background.

    Training runs asynchronously. Poll GET /strategies/rl/status for progress.

    Returns immediately with {"status": "started", "symbol": ..., "timesteps": ...}
    """
    status = get_training_status()
    if status.get("running"):
        raise HTTPException(
            400,
            f"Training already running for {status.get('symbol')} — "
            "wait for it to finish or restart the engine.",
        )

    trainer = _get_trainer()

    async def _run():
        await trainer.train_symbol(
            symbol=req.symbol,
            interval=req.interval,
            timesteps=req.timesteps,
            force_recompute=req.force_recompute,
        )

    background_tasks.add_task(_run)

    logger.info(
        f"[StrategyRouter] RL training started: {req.symbol} {req.interval} "
        f"({req.timesteps:,} timesteps)"
    )
    return {
        "status": "started",
        "symbol": req.symbol,
        "interval": req.interval,
        "timesteps": req.timesteps,
        "message": "Training running in background. Poll GET /strategies/rl/status for progress.",
    }


@router.get("/rl/status")
async def rl_training_status() -> dict:
    """
    Get current RL training status and last result.

    Returns running status, progress %, and last completed training metrics.
    """
    status = get_training_status()
    return {
        "running": status.get("running", False),
        "symbol": status.get("symbol"),
        "started_at": status.get("started_at"),
        "progress_pct": status.get("progress_pct", 0),
        "error": status.get("error"),
        "last_result": status.get("last_result"),
    }


@router.get("/rl/models")
async def list_rl_models(symbol: Optional[str] = None) -> dict:
    """
    List saved RL models.

    Optionally filter by symbol (e.g. ?symbol=MES).
    Returns list of models with path, size, and training metadata.
    """
    trainer = _get_trainer()
    models = trainer.list_models(symbol=symbol)
    return {
        "count": len(models),
        "symbol_filter": symbol.upper() if symbol else None,
        "models": models,
    }


@router.post("/rl/evaluate")
async def evaluate_rl_model(req: EvaluateRequest) -> dict:
    """
    Evaluate a saved RL model on recent OOS data.

    Fetches the last TEST_LOOKBACK_DAYS of data and runs the agent through it.
    Returns performance metrics and pass/fail for validation gates.
    """
    import asyncio
    from pathlib import Path

    from strategies.rl_agent import RLTradingAgent
    from strategies.rl_config import RL_CACHE_DIR, TEST_LOOKBACK_DAYS
    from strategies.rl_environment import build_env, prepare_dataframe

    model_zip = req.model_path if req.model_path.endswith(".zip") else f"{req.model_path}.zip"
    if not Path(model_zip).exists():
        raise HTTPException(404, f"Model not found: {model_zip}")

    try:
        trainer = _get_trainer()

        # Fetch recent data for OOS evaluation
        df_raw = await trainer._fetch_data(
            symbol=req.symbol,
            interval=req.interval,
            lookback_days=TEST_LOOKBACK_DAYS,
        )
        if df_raw is None or len(df_raw) < 60:
            raise HTTPException(422, f"Insufficient data for evaluation: {len(df_raw or [])} bars")

        # Use cached indicators if available, else compute fresh
        cache_path = RL_CACHE_DIR / f"{req.symbol}_{req.interval}_eval.parquet"
        df = await asyncio.to_thread(prepare_dataframe, df_raw, cache_path=cache_path, force_recompute=True)

        test_env = build_env(symbol=req.symbol, df=df)
        agent = RLTradingAgent.load(
            symbol=req.symbol,
            model_path=req.model_path,
            env=test_env,
        )

        metrics = await asyncio.to_thread(agent.evaluate, test_env, n_episodes=1)
        return {
            "symbol": req.symbol,
            "model_path": req.model_path,
            "eval_bars": len(df),
            "metrics": metrics,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[StrategyRouter] Evaluation error: {e}", exc_info=True)
        raise HTTPException(500, f"Evaluation failed: {e}") from e


@router.get("/rl/health")
async def rl_strategy_health() -> dict:
    """Health check for RL strategy module."""
    try:
        import gymnasium  # noqa
        gym_ok = True
    except ImportError:
        gym_ok = False

    try:
        import stable_baselines3  # noqa
        sb3_ok = True
    except ImportError:
        sb3_ok = False

    return {
        "gymnasium_available": gym_ok,
        "stable_baselines3_available": sb3_ok,
        "trainer_initialized": _trainer is not None,
        "ready": gym_ok and sb3_ok,
    }
