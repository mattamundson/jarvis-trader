"""
JARVIS TRADER — RL Strategies Router
======================================
5 API endpoints for RL training, status polling, model listing,
results retrieval, and out-of-sample evaluation.

Endpoints:
    POST /strategies/rl/train         — start background PPO training
    GET  /strategies/rl/status        — poll current training status
    GET  /strategies/rl/models        — list saved RL model files on disk
    GET  /strategies/rl/results/{run_id} — walk-forward results for a run
    POST /strategies/rl/evaluate      — run OOS evaluation on saved model
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, Field

from middleware.rate_limit import get_limiter
from strategies.rl_config import (
    DEFAULT_INTERVAL,
    RUN7_SCENARIOS,
    TIMESTEPS_DEFAULT,
    TIMESTEPS_QUICK,
)
from strategies.rl_trainer import RLTrainer, _training_status, get_training_status, request_stop

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/strategies", tags=["strategies"])

# Get limiter instance for rate limiting
limiter = get_limiter()

# ── Module-level dependency singletons ────────────────────────────────────────
# Injected at startup by main.py via inject_deps().
# When None the executor runs without SafetyLayer / data_manager (simulation mode).
_safety_layer: Optional[object] = None
_data_manager: Optional[object] = None


def inject_deps(safety_layer: Optional[object], data_manager: Optional[object]) -> None:
    """
    Wire the engine-wide SafetyLayer and MarketDataManager into the strategies
    router so that RLExecutors created by the deploy endpoint receive them.

    Called once during the FastAPI lifespan startup in main.py.
    """
    global _safety_layer, _data_manager
    _safety_layer = safety_layer
    _data_manager = data_manager
    logger.info(
        "[StrategiesRouter] inject_deps: safety_layer=%s data_manager=%s",
        type(safety_layer).__name__ if safety_layer is not None else "None",
        type(data_manager).__name__ if data_manager is not None else "None",
    )


# ── In-memory run registry (keyed by run_id) ──────────────────────────────────
# Each entry: {run_id, symbol, status, result, started_at, error}
_run_registry: dict[str, dict] = {}


# ── Request / Response Models ─────────────────────────────────────────────────


class TrainRequest(BaseModel):
    symbol: str = Field("MES", description="Futures symbol: MES, MNQ, MCL, MGC")
    interval: str = Field(DEFAULT_INTERVAL, description="Bar interval: 1h, 4h, 1d")
    timesteps: int = Field(
        TIMESTEPS_DEFAULT,
        ge=1000,
        le=2_000_000,
        description="PPO training timesteps",
    )
    quick: bool = Field(
        False, description="If True, use TIMESTEPS_QUICK (10k steps) for smoke test"
    )
    reward_scenario: Optional[str] = Field(
        None,
        description='RUN7 reward scenario override: "A", "B", or "C". '
        "Merges the chosen scenario's keys into REWARD_CONFIG for this run only.",
    )


class EvaluateRequest(BaseModel):
    symbol: str = Field("MES", description="Futures symbol to evaluate")
    start_date: str = Field(..., description="ISO date string e.g. 2025-10-01")
    end_date: str = Field(..., description="ISO date string e.g. 2026-04-01")
    model_path: Optional[str] = Field(
        None,
        description=(
            "Path to saved model (without .zip). "
            "If omitted, uses latest saved model for the symbol."
        ),
    )


class WalkForwardRequest(BaseModel):
    symbol: str = Field("MES", description="Futures symbol: MES, MNQ, MCL, MGC")
    interval: str = Field("1h", description="Bar interval: 1h, 4h, 1d")
    timesteps_per_window: int = Field(
        100_000,
        ge=1_000,
        le=2_000_000,
        description="PPO training timesteps per walk-forward window",
    )
    n_windows: int = Field(
        8,
        ge=2,
        le=20,
        description="Number of rolling walk-forward windows (default 8)",
    )
    reward_scenario: Optional[str] = Field(
        None,
        description='RUN7 reward scenario override: "A", "B", or "C". '
        "Merges the chosen scenario's keys into REWARD_CONFIG for each window.",
    )


# ── Helper ────────────────────────────────────────────────────────────────────


async def _run_training(run_id: str, req: TrainRequest) -> None:
    """Background task that calls RLTrainer.train_symbol and updates the registry."""
    trainer = RLTrainer(data_manager=None)
    timesteps = TIMESTEPS_QUICK if req.quick else req.timesteps

    # Resolve reward_scenario → reward_config dict (validated at enqueue time,
    # but guard here in case registry was bypassed).
    reward_config: Optional[dict] = None
    if req.reward_scenario:
        reward_config = RUN7_SCENARIOS.get(req.reward_scenario.upper())

    _run_registry[run_id]["status"] = "running"
    _run_registry[run_id]["timesteps"] = timesteps

    try:
        result = await trainer.train_symbol(
            symbol=req.symbol,
            interval=req.interval,
            timesteps=timesteps,
            reward_config=reward_config,
        )
        _run_registry[run_id]["status"] = result.get("status", "complete")
        _run_registry[run_id]["result"] = result
        _run_registry[run_id]["completed_at"] = datetime.now(timezone.utc).isoformat()
        logger.info(f"[StrategiesRouter] Training run {run_id} complete for {req.symbol}")

    except Exception as exc:
        logger.error(f"[StrategiesRouter] Training run {run_id} failed: {exc}")
        _run_registry[run_id]["status"] = "error"
        _run_registry[run_id]["error"] = str(exc)
        _run_registry[run_id]["completed_at"] = datetime.now(timezone.utc).isoformat()


async def _run_walkforward(run_id: str, req: WalkForwardRequest) -> None:
    """Background task that calls RLTrainer.train_walkforward and updates the registry."""
    trainer = RLTrainer(data_manager=None)

    # Resolve reward_scenario → reward_config dict.
    reward_config: Optional[dict] = None
    if req.reward_scenario:
        reward_config = RUN7_SCENARIOS.get(req.reward_scenario.upper())

    _run_registry[run_id]["status"] = "running"

    try:
        result = await trainer.train_walkforward(
            symbol=req.symbol,
            interval=req.interval,
            timesteps_per_window=req.timesteps_per_window,
            n_windows=req.n_windows,
            reward_config=reward_config,
        )
        _run_registry[run_id]["status"] = result.get("status", "complete")
        _run_registry[run_id]["result"] = result
        _run_registry[run_id]["completed_at"] = datetime.now(timezone.utc).isoformat()
        logger.info(
            f"[StrategiesRouter] Walk-forward run {run_id} complete for {req.symbol} | "
            f"recommendation={result.get('recommendation', 'unknown')}"
        )

    except Exception as exc:
        logger.error(f"[StrategiesRouter] Walk-forward run {run_id} failed: {exc}")
        _run_registry[run_id]["status"] = "error"
        _run_registry[run_id]["error"] = str(exc)
        _run_registry[run_id]["completed_at"] = datetime.now(timezone.utc).isoformat()


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post(
    "/rl/train",
    description="Start background PPO training for a symbol with configurable timesteps and reward scenario.",
)
@limiter.limit("10/minute")
async def start_rl_training(
    request: Request,
    req: TrainRequest,
    background_tasks: BackgroundTasks,
) -> dict:
    """
    Start PPO training for a symbol in the background.

    Returns run_id immediately. Poll GET /strategies/rl/status or
    GET /strategies/rl/results/{run_id} to check progress.

    - **symbol**: MES, MNQ, MCL, MGC
    - **timesteps**: 1,000 – 2,000,000 (default 100,000)
    - **quick**: If true, uses 10,000 steps for a fast smoke test
    """
    # Validate reward_scenario before queuing
    if req.reward_scenario and req.reward_scenario.upper() not in RUN7_SCENARIOS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown reward_scenario '{req.reward_scenario}'. "
                f"Valid values: {', '.join(sorted(RUN7_SCENARIOS.keys()))}"
            ),
        )

    # Block duplicate runs for same symbol
    current = get_training_status()
    if current.get("running") and current.get("symbol") == req.symbol.upper():
        raise HTTPException(
            status_code=409,
            detail=(
                f"Training already running for {req.symbol}. "
                "Wait for it to complete or check /strategies/rl/status."
            ),
        )

    run_id = str(uuid.uuid4())
    _run_registry[run_id] = {
        "run_id": run_id,
        "symbol": req.symbol.upper(),
        "interval": req.interval,
        "reward_scenario": req.reward_scenario.upper() if req.reward_scenario else None,
        "status": "queued",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
        "result": None,
        "error": None,
    }

    background_tasks.add_task(_run_training, run_id, req)
    logger.info(
        f"[StrategiesRouter] Training queued run_id={run_id} "
        f"symbol={req.symbol} timesteps={TIMESTEPS_QUICK if req.quick else req.timesteps}"
    )

    return {
        "run_id": run_id,
        "status": "started",
        "symbol": req.symbol.upper(),
        "message": (
            f"Training started for {req.symbol}. "
            f"Poll GET /api/v1/strategies/rl/status for progress."
        ),
    }


@router.post(
    "/rl/stop",
    description="Request graceful abort of the active training run with window-aware stopping for walk-forward validation.",
)
@limiter.limit("10/minute")
async def stop_rl_training(request: Request) -> dict:
    """
    Request graceful abort of the active training run.

    For single-symbol runs: stops before the blocking PPO.learn() phase begins.
    If PPO.learn() is already running it will complete its current call, but any
    subsequent phases (evaluate, save) will be skipped.

    For walk-forward runs: stops between windows at the next window boundary.
    A window already in progress will run to completion before the abort takes effect.

    Returns immediately — poll GET /strategies/rl/status for completion.
    """
    request_stop()

    # Update status to show abort was requested
    if _training_status.get("running"):
        _training_status["abort_requested"] = True

    return {
        "message": "Stop requested. Training will abort at the next safe checkpoint.",
        "abort_requested": True,
        "note": (
            "Single-symbol runs: abort takes effect between training phases. "
            "Walk-forward: stops between windows."
        ),
    }


@router.post(
    "/rl/train-walkforward",
    description="Start walk-forward training with rolling windows where ALL windows must pass validation gates for deployment recommendation.",
)
@limiter.limit("10/minute")
async def train_walkforward(
    request: Request,
    req: WalkForwardRequest,
    background_tasks: BackgroundTasks,
) -> dict:
    """
    Start walk-forward training (rolling windows, ALL must pass validation gates).

    Runs **n_windows** independent PPO train/evaluate cycles over rolling
    slices of historical data. A model is only recommended for deployment if
    EVERY window passes ALL validation gates (profit_factor, win_rate,
    max_drawdown, n_trades). Note: Sharpe is not available from per-episode
    metrics and is not checked here.

    - **symbol**: MES, MNQ, MCL, MGC
    - **interval**: 1h, 4h, 1d
    - **timesteps_per_window**: PPO steps for each of the n_windows models
    - **n_windows**: number of rolling windows (default 8)

    Returns run_id immediately. Poll GET /strategies/rl/status for progress;
    walkforward_windows shows per-window results as they complete.
    GET /strategies/rl/results/{run_id} returns final aggregate results.
    """
    # Validate reward_scenario before queuing
    if req.reward_scenario and req.reward_scenario.upper() not in RUN7_SCENARIOS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown reward_scenario '{req.reward_scenario}'. "
                f"Valid values: {', '.join(sorted(RUN7_SCENARIOS.keys()))}"
            ),
        )

    # Block duplicate runs for same symbol
    current = get_training_status()
    if current.get("running") and current.get("symbol") == req.symbol.upper():
        raise HTTPException(
            status_code=409,
            detail=(
                f"Training already running for {req.symbol}. "
                "Wait for it to complete or check /strategies/rl/status."
            ),
        )

    run_id = str(uuid.uuid4())
    _run_registry[run_id] = {
        "run_id": run_id,
        "symbol": req.symbol.upper(),
        "interval": req.interval,
        "mode": "walkforward",
        "n_windows": req.n_windows,
        "reward_scenario": req.reward_scenario.upper() if req.reward_scenario else None,
        "status": "queued",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
        "result": None,
        "error": None,
    }

    background_tasks.add_task(_run_walkforward, run_id, req)
    logger.info(
        f"[StrategiesRouter] Walk-forward queued run_id={run_id} "
        f"symbol={req.symbol} n_windows={req.n_windows} "
        f"timesteps_per_window={req.timesteps_per_window}"
    )

    return {
        "run_id": run_id,
        "status": "started",
        "symbol": req.symbol.upper(),
        "n_windows": req.n_windows,
        "message": (
            f"Walk-forward training started for {req.symbol} "
            f"({req.n_windows} windows). "
            f"Poll GET /api/v1/strategies/rl/status for per-window progress."
        ),
    }


@router.get(
    "/rl/status",
    description="Return current RL training status with progress percentage, recent runs, and walk-forward window results.",
)
async def get_rl_training_status() -> dict:
    """
    Return current RL training status from the trainer's module-level state.

    Includes the most recent training run result when available.
    """
    try:
        status = get_training_status()
        # Enrich with recent runs summary
        recent_runs = [
            {
                "run_id": v["run_id"],
                "symbol": v["symbol"],
                "status": v["status"],
                "started_at": v["started_at"],
                "completed_at": v.get("completed_at"),
            }
            for v in sorted(
                _run_registry.values(),
                key=lambda x: x.get("started_at", ""),
                reverse=True,
            )[:5]
        ]
        return {
            "training_active": status.get("running", False),
            "current_symbol": status.get("symbol"),
            "started_at": status.get("started_at"),
            "progress_pct": status.get("progress_pct", 0),
            "last_result": status.get("last_result"),
            "error": status.get("error"),
            "recent_runs": recent_runs,
            # Walk-forward fields
            "walkforward_windows": status.get("walkforward_windows", []),
            "walkforward_n_windows": status.get("walkforward_n_windows", 0),
            "walkforward_complete": status.get("walkforward_complete", False),
        }
    except Exception as exc:
        logger.error(f"[StrategiesRouter] Status check failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/rl/models",
    description="List all saved RL model files on disk with optional symbol filter and metadata for each model.",
)
async def list_rl_models(symbol: Optional[str] = None) -> dict:
    """
    List all saved RL model files on disk.

    Scans RL_MODELS_DIR for .zip model files and returns metadata for each.
    An optional ?symbol=MES query parameter filters results to a single symbol.

    - **symbol**: Optional futures symbol filter (e.g. MES, MNQ, MCL)
    """
    try:
        trainer = RLTrainer(data_manager=None)
        models = trainer.list_models(symbol=symbol)
        return {
            "count": len(models),
            "symbol_filter": symbol.upper() if symbol else None,
            "models": models,
        }
    except Exception as exc:
        logger.error(f"[StrategiesRouter] list_rl_models failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/rl/results/{run_id}",
    description="Return walk-forward results for a specific training run with metrics, windows, and deployment recommendation.",
)
async def get_rl_results(run_id: str) -> dict:
    """
    Return walk-forward results for a specific training run.

    - **run_id**: UUID returned by POST /strategies/rl/train
    """
    entry = _run_registry.get(run_id)
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail=f"run_id '{run_id}' not found. It may have been cleared on server restart.",
        )

    response: dict = {
        "run_id": run_id,
        "symbol": entry.get("symbol"),
        "status": entry.get("status"),
        "started_at": entry.get("started_at"),
        "completed_at": entry.get("completed_at"),
        "error": entry.get("error"),
    }

    result = entry.get("result")
    if result:
        # Standard training fields
        response["metrics"] = result.get("metrics", {})
        response["training_summary"] = result.get("training_summary", {})
        response["model_path"] = result.get("model_path")
        response["train_bars"] = result.get("train_bars")
        response["test_bars"] = result.get("test_bars")
        response["interval"] = result.get("interval")
        response["timesteps"] = result.get("timesteps")

        # Walk-forward specific fields (populated only for walk-forward runs)
        if entry.get("mode") == "walkforward" or "windows" in result:
            response["windows"] = result.get("windows", [])
            response["all_pass"] = result.get("all_pass")
            response["pass_rate"] = result.get("pass_rate")
            response["aggregate_metrics"] = result.get("aggregate_metrics", {})
            response["best_model_path"] = result.get("best_model_path")
            response["recommendation"] = result.get("recommendation")
            response["n_windows"] = result.get("n_windows")

    return response


@router.post(
    "/rl/evaluate",
    description="Run out-of-sample evaluation on a saved RL model with full metrics and validation gate assessment.",
)
@limiter.limit("10/minute")
async def run_rl_evaluation(request: Request, req: EvaluateRequest) -> dict:
    """
    Run out-of-sample evaluation on a saved RL model.

    Loads the saved PPO model and runs deterministic inference over the
    specified date range. Returns full metrics: Sharpe, PF, WR, MaxDD,
    HOLD rate, n_trades, passes_validation.

    - **symbol**: Futures symbol (MES, MNQ, MCL)
    - **start_date**: ISO date e.g. "2025-10-01"
    - **end_date**: ISO date e.g. "2026-04-01"
    - **model_path**: Optional path to model file (auto-resolved if omitted)
    """
    if req is None:
        raise HTTPException(status_code=422, detail="Request body is required")

    try:
        from strategies.rl_evaluator import OOSEvaluator

        evaluator = OOSEvaluator(model_path=req.model_path)
        metrics = await asyncio.to_thread(
            evaluator.evaluate,
            req.symbol,
            req.start_date,
            req.end_date,
        )
        return metrics

    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="RL evaluator not available") from exc
    except Exception as exc:
        logger.error(f"[StrategiesRouter] Evaluation failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ── Executor endpoints ────────────────────────────────────────────────────────


class DeployRequest(BaseModel):
    symbol: str = Field("MES", description="Futures symbol: MES, MNQ, MCL, MGC")
    model_path: str = Field(
        ...,
        description="Path to saved PPO model (without .zip extension)",
    )
    active: bool = Field(
        True,
        description="True to start the executor, False to stop it",
    )


@router.post(
    "/rl/deploy",
    description="Activate or deactivate a trained RL model for live hourly execution with SafetyLayer integration.",
)
@limiter.limit("10/minute")
async def deploy_model(
    request: Request,
    req: DeployRequest,
    background_tasks: BackgroundTasks,
) -> dict:
    """
    Activate or deactivate a trained RL model for live hourly execution.

    When **active=True**: creates an RLExecutor for the symbol and starts the
    APScheduler job that fires at minute :59 Mon-Fri 07:00-15:00 CT.

    When **active=False**: stops the scheduler and removes the executor from the
    registry.

    - **symbol**: MES, MNQ, MCL, MGC
    - **model_path**: path to saved model file (without .zip extension)
    - **active**: True to deploy, False to deactivate
    """
    from strategies.rl_executor import RLExecutor, _executor_registry, _executor_registry_lock

    symbol = req.symbol.upper()

    if req.active:
        # Validate model_path exists before touching the executor registry.
        # RLExecutor._load_model() silently falls back to simulation mode when
        # the file is missing, so without this guard the caller would receive
        # HTTP 200 even for a bad path.
        _model_file = Path(req.model_path)
        if not _model_file.exists() and not Path(f"{req.model_path}.zip").exists():
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Model file not found: '{req.model_path}' "
                    "(neither the exact path nor the .zip variant exists). "
                    "Train a model first via POST /strategies/rl/train."
                ),
            )

        # Build the new executor object first (before acquiring the lock) so
        # we hold the lock for the shortest possible time.
        # Wire the engine-wide SafetyLayer and MarketDataManager so that
        # the executor uses IBKR data and submits orders through the safety gate.
        executor = RLExecutor(
            symbol=symbol,
            model_path=req.model_path,
            safety_layer=_safety_layer,
            data_manager=_data_manager,
        )

        # Atomically swap the registry entry so concurrent status reads never
        # see a gap between the old executor being removed and the new one
        # being registered.  existing.stop() is called AFTER we release the
        # lock to avoid holding it while the scheduler shuts down.
        with _executor_registry_lock:
            existing = _executor_registry.get(symbol)
            # Pre-register the new executor immediately so the status endpoint
            # returns it even before the background start() fires.
            _executor_registry[symbol] = executor

        if existing is not None:
            existing.stop()
            logger.info(
                "[StrategiesRouter] Stopped existing executor for %s before redeployment", symbol
            )

        # Start scheduler in background so the API call returns immediately
        background_tasks.add_task(executor.start)

        logger.info(
            "[StrategiesRouter] Deployed RL executor for %s | model=%s", symbol, req.model_path
        )
        return {
            "status": "deployed",
            "symbol": symbol,
            "model_path": req.model_path,
            "message": (
                f"Executor deployed for {symbol}. Fires at :59 every hour "
                "Mon-Fri 07:00-15:00 CT. Use GET /strategies/rl/executor/status to monitor."
            ),
        }
    else:
        # Acquire the registry lock for the entire read+remove sequence so a
        # concurrent deploy() cannot replace the entry between our get() and
        # the stop() call.
        with _executor_registry_lock:
            executor = _executor_registry.get(symbol)
        if executor is None:
            raise HTTPException(
                status_code=404,
                detail=f"No active executor found for {symbol}. Nothing to deactivate.",
            )
        executor.stop()  # stop() acquires the lock internally to pop from registry
        logger.info("[StrategiesRouter] Deactivated RL executor for %s", symbol)
        return {
            "status": "deactivated",
            "symbol": symbol,
            "message": f"Executor for {symbol} has been stopped.",
        }


@router.get(
    "/rl/executor/status",
    description="Return status snapshot for all currently running RL executors with model state and execution metrics.",
)
async def executor_status() -> dict:
    """
    Return status snapshot for all currently running RL executors.

    Each entry in ``executors`` contains: symbol, model_path, is_running,
    model_loaded, last_action, last_prediction_time, bars_executed,
    paper_position, entry_price, bars_in_trade, last_error, next_fire_time.

    Also includes a flattened top-level view consumed by the dashboard's
    simplified RLExecutorStatusCard (dashboard/app/strategies/page.tsx):
    ``deployed``, ``symbol``, ``model_path``, ``last_prediction``,
    ``last_prediction_time``, ``next_fire_time``. These mirror one real
    executor's fields (last_action -> last_prediction) rather than
    fabricated values. When zero executors are deployed, deployed=False
    and the rest are None. When more than one executor is deployed (the
    engine trades multiple symbols, e.g. MES + MGC), the executor with the
    most recent last_prediction_time is surfaced here as "primary"; ties
    or an all-unpredicted set fall back to registry insertion order. The
    full per-symbol detail is always available in ``executors`` regardless
    of how many are deployed.
    """
    from strategies.rl_executor import get_executor_status

    try:
        statuses = get_executor_status()

        primary: Optional[dict] = None
        if statuses:
            entries = list(statuses.values())
            predicted = [e for e in entries if e.get("last_prediction_time")]
            primary = max(predicted, key=lambda e: e["last_prediction_time"]) if predicted else entries[0]

        return {
            "executor_count": len(statuses),
            "executors": statuses,
            "deployed": primary is not None,
            "symbol": primary.get("symbol") if primary else None,
            "model_path": primary.get("model_path") if primary else None,
            "last_prediction": primary.get("last_action") if primary else None,
            "last_prediction_time": primary.get("last_prediction_time") if primary else None,
            "next_fire_time": primary.get("next_fire_time") if primary else None,
        }
    except Exception as exc:
        logger.error(f"[StrategiesRouter] executor_status failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post(
    "/rl/executor/run-now",
    description="Manually trigger one execution cycle for a running executor outside the normal :59 schedule.",
)
@limiter.limit("10/minute")
async def run_executor_now(request: Request, symbol: str = None) -> dict:
    """
    Manually trigger one execution cycle for a running executor.

    Useful for testing — fires the full predict + safety-gate + route pipeline
    immediately, outside the normal :59 schedule.

    - **symbol**: The symbol whose executor to trigger (e.g. MES)
    """
    from strategies.rl_executor import _executor_registry

    sym = symbol.upper()
    executor = _executor_registry.get(sym)
    if executor is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No active executor found for {sym}. "
                "Deploy one first via POST /strategies/rl/deploy."
            ),
        )

    try:
        result = await asyncio.to_thread(executor.run_once)
        return result
    except Exception as exc:
        logger.error(f"[StrategiesRouter] run_executor_now failed for {sym}: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/rl/health",
    description="Health check for the RL strategy module dependencies including stable-baselines3 and PyTorch.",
)
async def rl_strategy_health() -> dict:
    """Health check for the RL strategy module dependencies.

    Schema matches dashboard/app/strategies/page.tsx (uses ``*_available``)
    and tests/test_integration_rl_endpoints.py::TestRLHealth. Older bare
    ``gymnasium`` / ``stable_baselines3`` keys were dropped — they had no
    remaining callers and every consumer expects the ``_available`` suffix
    plus a roll-up ``ready`` boolean.
    """
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
        "ready": gym_ok and sb3_ok,
    }


# ── MES Experiment Search Endpoints ───────────────────────────────────────────


@router.get(
    "/experiments/mes/status",
    description="Return current MES experiment search status, best WFE found, and Sprint 18 recommendation.",
)
async def get_mes_experiment_status() -> dict:
    """Return current MES experiment search status."""
    import json
    import os

    log_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "strategies",
        "experiment_log.json",
    )

    experiments: list[dict] = []
    if os.path.exists(log_path):
        try:
            with open(log_path) as f:
                experiments = json.load(f)
        except Exception:
            experiments = []

    best_wfe = 0.0
    best_config: dict = {}
    if experiments:
        best = max(experiments, key=lambda r: r.get("wfe", 0.0))
        best_wfe = best.get("wfe", 0.0)
        best_config = best.get("config_used", {})

    gate_threshold = 0.50
    wfe_gate_passed = best_wfe >= gate_threshold

    sprint18_recommendation = (
        "Pivot to 4h timeframe experiments — no MES edge found in 1h STC configs"
        if experiments and best_wfe < 0.15
        else (
            "Continue 1h experiments — promising region found, run 11-30 in Sprint 18"
            if best_wfe >= 0.30
            else "Run experiments 11-30 in Sprint 18 across broader parameter space"
        )
        if experiments
        else "Run experiments 1-10 first via: python -m strategies.run_experiment --symbol MES --config strategies/mes_search_space.json --n 10"
    )

    return {
        "experiments_run": len(experiments),
        "best_wfe": round(best_wfe, 4),
        "best_config": best_config,
        "wfe_gate_passed": wfe_gate_passed,
        "gate_threshold": gate_threshold,
        "sprint18_recommendation": sprint18_recommendation,
    }
