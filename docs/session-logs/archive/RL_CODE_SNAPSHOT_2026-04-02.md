# RL Code Snapshot — JARVIS TRADER
**Generated:** 2026-04-02
**Purpose:** Verbatim code extraction for session report inclusion.
**Source files:** 6 strategy/router files + main.py lifespan excerpt.

---

## Table of Contents

1. [rl_config.py](#1-rl_configpy)
2. [rl_environment.py](#2-rl_environmentpy)
3. [rl_trainer.py](#3-rl_trainerpy)
4. [rl_agent.py](#4-rl_agentpy)
5. [rl_executor.py](#5-rl_executorpy)
6. [strategies_router.py](#6-strategies_routerpy)
7. [main.py (lifespan excerpt)](#7-mainpy-lifespan-excerpt)
8. [Summary](#8-summary)

---

## 1. rl_config.py

**Path:** `C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\strategies\rl_config.py`
**Line count:** 333

### Classes and Functions

| Name | Type | Line |
|------|------|------|
| `Action` | class (IntEnum) | 17 |
| `get_instrument_params` | function | 105 |

### REWARD_CONFIG (verbatim, lines 111–134)

```python
REWARD_CONFIG = {
    # Primary: P&L normalized by ATR so reward is scale-invariant across instruments
    "pnl_atr_weight": 1.0,

    # Holding cost per bar when in a position (encourages closing losers quickly)
    # Run 8 (Two-Lever): doubled from -0.001 → -0.002.
    # Run 7 result: hold_rate=98.8%, n_trades=3. Agent learned to HOLD everything.
    # Doubling hold_cost makes long in-position holds more expensive, forcing
    # faster position cycling and more frequent close+reopen decisions.
    "hold_cost_per_bar": -0.002,

    # Entry cost fired on each new BUY or SELL (discourages overtrading)
    # Run 8 (Two-Lever): quartered from -0.05 → -0.02.
    # At -0.05, break-even hold = 50 bars. At -0.02, break-even = 10 bars.
    # Drastically lowers the per-trade barrier so the agent explores entries freely.
    "entry_cost": -0.02,

    # Bonus for reaching T1 ATR target (reinforces quality exits)
    "t1_bonus": 0.10,

    # No flat reward — pure P&L signal (unchanged from Run 7 / Scenario C).
    # Agent never earned flat_hold_reward in prior runs anyway.
    "flat_hold_reward": 0.000,
}
```

### PPO_CONFIG (verbatim, lines 287–300)

```python
PPO_CONFIG = {
    "policy": "MlpPolicy",
    "learning_rate": 3e-4,
    "n_steps": 2048,
    "batch_size": 64,
    "n_epochs": 10,
    "gamma": 0.99,
    "gae_lambda": 0.95,
    "clip_range": 0.2,
    "ent_coef": 0.05,       # Entropy bonus encourages HOLD exploration (raised from 0.01)
    "vf_coef": 0.5,
    "max_grad_norm": 0.5,
    "verbose": 0,
}
```

### VALIDATION_GATES (verbatim, lines 324–333)

```python
VALIDATION_GATES = {
    "min_profit_factor": 2.0,
    "min_sharpe": 1.5,
    "min_win_rate": 0.55,
    "min_trades": 60,
    "min_hold_rate": 0.50,
    "max_drawdown": 0.15,
    "max_consecutive_losses": 5,
}
```

### RL_INSTRUMENT_PARAMS (verbatim, lines 95–100)

```python
RL_INSTRUMENT_PARAMS = {
    "MES": (15, 83,  0.50, 2.00, 3.236, 4.00, False),
    "MNQ": (15, 92,  0.70, 1.00, 1.80,  2.618, True),
    "MCL": (15, 83,  0.90, 1.50, 2.618, 4.00,  True),
    "MGC": (17, 88,  0.30, 1.50, 2.618, 4.00,  True),
}
```

**Format:** `(STC_OS, STC_OB, STOP_ATR, T1_ATR, T2_ATR, T3_ATR, REGIME_FILTER)`

### Timestep Constants (verbatim, lines 303–305)

```python
TIMESTEPS_QUICK   = 10_000    # smoke test
TIMESTEPS_DEFAULT = 100_000   # usable model
TIMESTEPS_FULL    = 500_000   # production quality (~10k episodes of 50 bars)
```

### MAX_EPISODE_BARS (verbatim, line 314)

```python
MAX_EPISODE_BARS    = 500
```

### RUN7_SCENARIOS dict (verbatim, lines 268–283)

```python
RUN7_SCENARIOS = {
    # Scenario A — conservative: reduce flat_hold_reward 5x, keep entry_cost
    # Break-even: 100 flat bars (40% of episode). Expected hold_rate: 55-70%.
    # Over-trading risk: LOW. Use if Run 6 produces < 30 trades.
    "A": {"flat_hold_reward": 0.001, "entry_cost": -0.10},

    # Scenario B — moderate: halve entry_cost AND reduce flat_hold_reward
    # Break-even: 16.7 flat bars (6.7% of episode). Expected hold_rate: 50-65%.
    # Over-trading risk: MODERATE. Use if Run 6 produces 30-55 trades.
    "B": {"flat_hold_reward": 0.003, "entry_cost": -0.05},

    # Scenario C — aggressive: pure P&L signal, no flat reward, lower entry cost
    # No flat break-even (flat HOLD yields zero). Expected hold_rate: 40-55%.
    # Over-trading risk: MODERATE-HIGH. Use if Scenario B still < 60 trades.
    "C": {"flat_hold_reward": 0.000, "entry_cost": -0.05},
}
```

---

## 2. rl_environment.py

**Path:** `C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\strategies\rl_environment.py`
**Line count:** 600

### Classes and Functions

| Name | Type | Line |
|------|------|------|
| `extract_features` | function | 55 |
| `TradingEnvironment` | class | 179 |
| `TradingEnvironment.__init__` | method | 194 |
| `TradingEnvironment.reset` | method | 245 |
| `TradingEnvironment.step` | method | 288 |
| `TradingEnvironment.render` | method | 399 |
| `TradingEnvironment.close` | method | 408 |
| `TradingEnvironment._get_obs` | method | 413 |
| `TradingEnvironment._get_info` | method | 424 |
| `TradingEnvironment._calculate_reward` | method | 437 |
| `TradingEnvironment._record_trade` | method | 477 |
| `TradingEnvironment.get_episode_metrics` | method | 488 |
| `prepare_dataframe` | function | 545 |
| `build_env` | function | 583 |

### STATE_FEATURES list (verbatim, lines 35–65)

```python
STATE_FEATURES = [
    # Price features
    "close_normalized",     # z-score of close over 50-bar window
    "high_low_range",       # (high - low) / atr
    "close_vs_ema21",       # (close - ema_21) / atr

    # STC (Schaff Trend Cycle)
    "stc_value",            # stc_val / 100  →  [0, 1]
    "stc_slope",            # diff(stc_val, 1) / 100
    "stc_above_os",         # 1 if stc_val > STC_OS threshold else 0
    "stc_below_ob",         # 1 if stc_val < STC_OB threshold else 0

    # ATR / volatility
    "atr_14",               # raw ATR-14 value
    "atr_normalized",       # atr / close
    "atr_vs_20d_avg",       # atr / rolling(20).mean() of atr

    # Regime & trend
    "regime_score",         # float: TRENDING_BULL=1, RANGE_BOUND=0, TRENDING_BEAR=-1, etc.
    "trend_direction",      # float: ema_trend bullish=1, neutral=0, bearish=-1
    "phase_value",          # phase_val / 100  →  [-1, 1] approx

    # Volume
    "volume_vs_avg",        # volume / rolling(10).mean()
    "volume_signal",        # buy_pct: buyer_dominant=1, balanced=0, seller_dominant=-1

    # Position state (internal environment tracking)
    "current_position",     # 1=long, 0=flat, -1=short
    "unrealized_pnl_atr",   # unrealized_pnl / atr  (negative when underwater)
    "bars_in_trade",        # number of bars since position opened (normalized /100)
]

N_FEATURES = len(STATE_FEATURES)  # 18
```

**Note:** N_FEATURES = 18 (the list has 18 entries despite the comment saying 18 — confirmed by counting).
**Note:** rl_config.py line 67 shows `N_FEATURES = len(STATE_FEATURES)  # 18`

### extract_features() signature (verbatim, lines 55–62)

```python
def extract_features(
    df: pd.DataFrame,
    idx: int,
    position: int,
    entry_price: float,
    bars_in_trade: int,
    symbol: str,
) -> np.ndarray:
```

### _calculate_reward() — complete method body (verbatim, lines 437–475)

```python
def _calculate_reward(
    self,
    action: int,
    realized_pnl: float,
    atr: float,
    is_new_entry: bool,
) -> float:
    cfg = self._reward_cfg

    # Primary: P&L in ATR units (scale-invariant across instruments)
    pnl_reward = (realized_pnl / atr * cfg["pnl_atr_weight"]) if atr > 0 else 0.0

    # Flat holding cost per bar when in a position (NOT compounding — was a bug)
    hold_cost = cfg["hold_cost_per_bar"] if self._position != 0 else 0.0

    # Small reward for HOLDing when flat — teaches patience, pushes hold_rate up
    flat_hold_reward = cfg.get("flat_hold_reward", 0.0) if (action == Action.HOLD and self._position == 0) else 0.0

    # Overtrading penalty per new entry
    entry_cost = cfg["entry_cost"] if is_new_entry else 0.0

    # Penalty for redundant/invalid actions: BUY when already long, SELL when already short
    # These are no-ops in the env but agent was discovering them as "free HOLD" — stop that.
    # Guard with `not is_new_entry` so a genuine entry from flat is not double-charged
    # (position is already updated to 1/-1 before this method is called).
    redundant_cost = cfg["entry_cost"] if (
        not is_new_entry and (
            (action == Action.BUY and self._position == 1) or
            (action == Action.SELL and self._position == -1)
        )
    ) else 0.0

    # Bonus for reaching T1 target
    t1_bonus = 0.0
    if realized_pnl > 0 and atr > 0 and (realized_pnl / atr) >= self.t1_atr:
        t1_bonus = cfg["t1_bonus"]
        self._t1_hits += 1

    return float(pnl_reward + hold_cost + flat_hold_reward + entry_cost + redundant_cost + t1_bonus)
```

### get_episode_metrics() return dict keys (verbatim, lines 496–540)

The method returns a dict with the following keys (two paths: empty trades and non-empty):

**Empty trades path:**
```python
return {
    "n_trades": 0, "win_rate": 0.0, "profit_factor": 0.0,
    "total_pnl": 0.0, "avg_pnl": 0.0,
    "max_drawdown": 0.0, "total_reward": self._total_reward,
    "flat_hold_rate": round(flat_hold_rate, 4),
    "t1_hits": self._t1_hits,
    "t1_hit_rate": 0.0,
    "avg_bars_in_trade": 0.0,
}
```

**Non-empty trades path:**
```python
return {
    "n_trades": len(trades),
    "win_rate": round(win_rate, 4),
    "profit_factor": round(profit_factor, 4),
    "total_pnl": round(sum(pnls), 2),
    "avg_pnl": round(sum(pnls) / len(pnls), 2),
    "max_drawdown": round(max_dd, 4),
    "total_reward": round(self._total_reward, 4),
    "flat_hold_rate": round(flat_hold_rate, 4),
    "t1_hits": self._t1_hits,
    "t1_hit_rate": round(self._t1_hits / max(len(trades), 1), 4),
    "avg_bars_in_trade": avg_bars_in_trade,
}
```

---

## 3. rl_trainer.py

**Path:** `C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\strategies\rl_trainer.py`
**Line count:** 750

### Classes and Functions

| Name | Type | Line |
|------|------|------|
| `request_stop` | function | 44 |
| `clear_stop` | function | 49 |
| `get_training_status` | function | 70 |
| `RLTrainer` | class | 74 |
| `RLTrainer.__init__` | method | 93 |
| `RLTrainer.train_symbol` | method | 96 |
| `RLTrainer.train_walkforward` | method | 261 |
| `RLTrainer._train_and_evaluate_window` | method | 585 |
| `RLTrainer._fetch_data` | method | 631 |
| `RLTrainer._fetch_yfinance` | method | 660 |
| `RLTrainer._normalize_columns` | method | 704 |
| `RLTrainer.list_models` | method | 717 |

### _stop_event declaration (verbatim, line 41)

```python
_stop_event: threading.Event = threading.Event()
```

### request_stop() and clear_stop() function bodies (verbatim, lines 44–51)

```python
def request_stop() -> None:
    """Signal active training to stop at the next safe checkpoint."""
    _stop_event.set()


def clear_stop() -> None:
    """Clear stop flag (called at start of each new training run)."""
    _stop_event.clear()
```

### _training_status initial dict (verbatim, lines 56–67)

```python
_training_status: dict = {
    "running": False,
    "symbol": None,
    "started_at": None,
    "progress_pct": 0,
    "last_result": None,
    "error": None,
    # Walk-forward fields (populated during train_walkforward)
    "walkforward_windows": [],
    "walkforward_n_windows": 0,
    "walkforward_complete": False,
}
```

### train_symbol() signature + key phase comments (verbatim, lines 96–246)

```python
async def train_symbol(
    self,
    symbol: str,
    interval: str = DEFAULT_INTERVAL,
    timesteps: int = TIMESTEPS_DEFAULT,
    force_recompute: bool = False,
    reward_config: dict | None = None,
) -> dict:
    """
    Full training pipeline for one symbol.
    ...
    Returns
    -------
    dict with keys: symbol, metrics, model_path, duration_seconds, status
    """
    # ── 1 & 2. Load from cache or fetch+compute ───────────────────────
    # ── 3. Train/test split ──────────────────────────────────────────
    # ── 4. Build environments ────────────────────────────────────────
    # ── 5. Train agent ───────────────────────────────────────────────
    # ── 6. Evaluate OOS ──────────────────────────────────────────────
    # ── 7. Save model ────────────────────────────────────────────────
    # ── 8. Build result ──────────────────────────────────────────────
```

### train_walkforward() signature (verbatim, lines 261–269)

```python
async def train_walkforward(
    self,
    symbol: str,
    interval: str = DEFAULT_INTERVAL,
    timesteps_per_window: int = TIMESTEPS_DEFAULT,
    n_windows: int = 8,
    window_size_bars: int = None,
    reward_config: dict | None = None,
) -> dict:
```

---

## 4. rl_agent.py

**Path:** `C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\strategies\rl_agent.py`
**Line count:** 361

### Classes and Functions

| Name | Type | Line |
|------|------|------|
| `TrainingProgressCallback` | class | 47 |
| `TrainingProgressCallback.__init__` | method | 53 |
| `TrainingProgressCallback._on_step` | method | 60 |
| `TrainingProgressCallback.get_summary` | method | 80 |
| `RLTradingAgent` | class | 93 |
| `RLTradingAgent.__init__` | method | 107 |
| `RLTradingAgent.train` | method | 147 |
| `RLTradingAgent.predict` | method | 194 |
| `RLTradingAgent.evaluate` | method | 224 |
| `RLTradingAgent.save` | method | 311 |
| `RLTradingAgent.load` | classmethod | 338 |
| `RLTradingAgent.get_status` | method | 352 |

### get_status() method (verbatim, lines 352–360)

```python
def get_status(self) -> dict:
    summary = self._callback.get_summary() if self._callback else {}
    return {
        "symbol": self.symbol,
        "is_trained": self._is_trained,
        "timesteps_trained": summary.get("timesteps", 0),
        "action_distribution": summary.get("action_distribution", {}),
        "last_rewards": summary.get("episode_rewards", []),
    }
```

---

## 5. rl_executor.py

**Path:** `C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\strategies\rl_executor.py`
**Line count:** 769

### Classes and Functions

| Name | Type | Line |
|------|------|------|
| `get_executor_status` | function | 87 |
| `RLExecutor` | class | 98 |
| `RLExecutor.__init__` | method | 118 |
| `RLExecutor._load_model` | method | 156 |
| `RLExecutor._fetch_latest_bars` | method | 201 |
| `RLExecutor._compute_obs` | method | 274 |
| `RLExecutor._route_action` | method | 321 |
| `RLExecutor.run_once` | method | 462 |
| `RLExecutor.start` | method | 624 |
| `RLExecutor.stop` | method | 669 |
| `RLExecutor.get_status` | method | 681 |
| `_build_dummy_df` | function | 729 |
| `_get_or_create_event_loop` | function | 746 |

### _executor_registry declaration (verbatim, lines 83–84)

```python
_executor_registry: dict[str, "RLExecutor"] = {}
_executor_registry_lock: threading.Lock = threading.Lock()
```

### get_status() method (verbatim, lines 681–724)

```python
def get_status(self) -> dict:
    """
    Return a status snapshot suitable for the /rl/executor/status endpoint.

    Keys
    ----
    symbol, model_path, is_running, scheduler_running, model_loaded,
    last_action, last_prediction_time, bars_executed,
    paper_position, entry_price, bars_in_trade, last_error

    Notes
    -----
    ``is_running`` reflects the logical state set by start()/stop().
    ``scheduler_running`` reflects the actual APScheduler internal state.
    If they diverge it indicates the scheduler crashed after start().
    """
    scheduler_running = (
        self._scheduler is not None and self._scheduler.running
    )
    # Expose obs shape (not the full array) so callers can verify the
    # feature vector is the expected (N_FEATURES,) without JSON serialisation issues.
    last_obs_shape = (
        list(self._last_obs.shape) if self._last_obs is not None else None
    )
    return {
        "symbol": self.symbol,
        "model_path": self.model_path,
        "is_running": self._is_running,
        "scheduler_running": scheduler_running,
        "model_loaded": self._model_loaded,
        "last_action": self._last_action,
        "last_prediction_time": self._last_prediction_time,
        "bars_executed": self._bars_executed,
        "paper_position": self._paper_position,
        "entry_price": self._entry_price,
        "bars_in_trade": self._bars_in_trade,
        "last_error": self._last_error,
        "last_obs_shape": last_obs_shape,
        "next_fire_time": (
            self._scheduler.get_jobs()[0].next_run_time.isoformat()
            if self._scheduler and self._scheduler.get_jobs()
            else None
        ),
    }
```

---

## 6. strategies_router.py

**Path:** `C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\routers\strategies_router.py`
**Line count:** 699

### Classes and Functions

| Name | Type | Line |
|------|------|------|
| `inject_deps` | function | 45 |
| `TrainRequest` | class (Pydantic) | 69 |
| `EvaluateRequest` | class (Pydantic) | 88 |
| `WalkForwardRequest` | class (Pydantic) | 101 |
| `_run_training` | async function | 125 |
| `_run_walkforward` | async function | 158 |
| `start_rl_training` | async function | 195 |
| `stop_rl_training` | async function | 261 |
| `train_walkforward` | async function | 291 |
| `get_rl_training_status` | async function | 369 |
| `list_rl_models` | async function | 411 |
| `get_rl_results` | async function | 434 |
| `run_rl_evaluation` | async function | 481 |
| `DeployRequest` | class (Pydantic) | 518 |
| `deploy_model` | async function | 530 |
| `executor_status` | async function | 626 |
| `run_executor_now` | async function | 648 |
| `rl_strategy_health` | async function | 679 |

### All @router.XXX decorators with path strings

```python
@router.post("/rl/train")           # line 194 — start_rl_training
@router.post("/rl/stop")            # line 260 — stop_rl_training
@router.post("/rl/train-walkforward")  # line 290 — train_walkforward
@router.get("/rl/status")           # line 369 — get_rl_training_status
@router.get("/rl/models")           # line 411 — list_rl_models
@router.get("/rl/results/{run_id}") # line 434 — get_rl_results
@router.post("/rl/evaluate")        # line 481 — run_rl_evaluation
@router.post("/rl/deploy")          # line 530 — deploy_model
@router.get("/rl/executor/status")  # line 626 — executor_status
@router.post("/rl/executor/run-now") # line 648 — run_executor_now
@router.get("/rl/health")           # line 679 — rl_strategy_health
```

**Router prefix:** `/strategies`
**Full paths:** All prefixed with `/strategies`, e.g. `POST /strategies/rl/train`

### POST /rl/stop endpoint body (verbatim, lines 260–287)

```python
@router.post("/rl/stop")
async def stop_rl_training() -> dict:
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
```

---

## 7. main.py (Lifespan Excerpt)

**Path:** `C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\main.py`
**Lines read:** 1–50 (imports/header) and 415–444 (lifespan shutdown)

### Lines 1–50: Imports and module docstring

```python
"""
JARVIS TRADER — Main Server
============================
FastAPI backend for the trading engine.
Runs on port 8010 (separate from GMS JARVIS on 8009).

Start with: uvicorn main:app --reload --port 8010
"""

import json
import logging
import logging.handlers
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded

from middleware.api_key_middleware import APIKeyMiddleware
from middleware.rate_limit import limiter, rate_limit_exception_handler

from agents.bear_researcher import BearResearcherAgent
from agents.bull_researcher import BullResearcherAgent
from agents.debate import DebateOrchestrator
from agents.fund_manager import FundManagerAgent
from agents.fundamental_analyst import FundamentalistAgent
from agents.news_analyst import NewsAnalystAgent
from agents.pipeline import TradingPipeline
from agents.risk_manager import RiskManagerAgent
from agents.social_analyst import SocialAnalystAgent
from agents.technical_analyst import TechnicalAnalystAgent
from agents.trader import TraderAgent
from config import settings
from data.market_data import MarketDataManager
from data.price_cache import PriceCache
from database.schema import DatabaseManager, init_db
from execution.ib_order_manager import IBOrderManager
from llm.cost_tracker import CostTracker
from portfolio.tracker import PortfolioTracker
from risk.loss_tracker import ConsecutiveLossTracker
from risk.pnl_monitor import PnLMonitor
from risk.safety_layer import SafetyLayer
```

### Lines 415–444: Lifespan shutdown — RL executor teardown

```python
    inject_prices_deps(price_cache)
    inject_sentiment_deps(data_manager)
    inject_thinkscript_deps(technical_analyst)
    # set_strategy_dm removed — strategy_router consolidated into strategies_router

    logger.info("✅ JARVIS TRADER ready. Dashboard: http://localhost:3010")
    logger.info("   API docs: http://localhost:8010/docs")

    yield

    if data_manager and data_manager.ibkr:
        await data_manager.ibkr.disconnect()
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)

    try:
        from orchestrator import get_orchestrator as _get_orch
        _orch = _get_orch()
        if _orch:
            await _orch.stop()
    except Exception:
        pass

    # Stop all RL executors gracefully
    try:
        from strategies.rl_executor import _executor_registry
        for _sym, _executor in list(_executor_registry.items()):
            _executor.stop()
            logger.info(f"RL executor stopped for {_sym}")
    except ImportError:
```

---

## 8. Summary

### File Line Counts

| File | Line Count |
|------|------------|
| rl_config.py | 333 |
| rl_environment.py | 600 |
| rl_trainer.py | 750 |
| rl_agent.py | 361 |
| rl_executor.py | 769 |
| strategies_router.py | 699 |
| main.py (full file, excerpt only read) | 444+ |
| **Total (RL files)** | **3,512** |

### Function/Class Inventory

| File | Classes | Functions/Methods | Total |
|------|---------|-------------------|-------|
| rl_config.py | 1 (Action) | 1 (get_instrument_params) | 2 |
| rl_environment.py | 1 (TradingEnvironment) | 13 (incl. methods) | 14 |
| rl_trainer.py | 1 (RLTrainer) | 11 (incl. methods) | 12 |
| rl_agent.py | 2 (TrainingProgressCallback, RLTradingAgent) | 10 (incl. methods) | 12 |
| rl_executor.py | 1 (RLExecutor) | 12 (incl. methods + helpers) | 13 |
| strategies_router.py | 3 (Pydantic models) | 15 (endpoints + helpers) | 18 |
| **Total** | **9** | **62** | **71** |

### Key Configuration Values Quick Reference

| Constant | Value |
|----------|-------|
| N_FEATURES | 18 |
| N_ACTIONS | 4 (HOLD=0, BUY=1, SELL=2, CLOSE=3) |
| MAX_EPISODE_BARS | 500 |
| TIMESTEPS_QUICK | 10,000 |
| TIMESTEPS_DEFAULT | 100,000 |
| TIMESTEPS_FULL | 500,000 |
| TRAIN_LOOKBACK_DAYS | 1,460 (4 years) |
| TEST_LOOKBACK_DAYS | 180 (6 months) |
| DEFAULT_INTERVAL | "1h" |
| REWARD: pnl_atr_weight | 1.0 |
| REWARD: hold_cost_per_bar | -0.002 (Run 8 value) |
| REWARD: entry_cost | -0.02 (Run 8 value) |
| REWARD: t1_bonus | 0.10 |
| REWARD: flat_hold_reward | 0.000 |
| PPO: learning_rate | 3e-4 |
| PPO: n_steps | 2,048 |
| PPO: batch_size | 64 |
| PPO: ent_coef | 0.05 |
| GATE: min_profit_factor | 2.0 |
| GATE: min_sharpe | 1.5 |
| GATE: min_win_rate | 0.55 |
| GATE: min_trades | 60 |
| GATE: min_hold_rate | 0.50 |
| GATE: max_drawdown | 0.15 |

### API Endpoints Summary (11 RL endpoints)

| Method | Path | Function |
|--------|------|----------|
| POST | /strategies/rl/train | start_rl_training |
| POST | /strategies/rl/stop | stop_rl_training |
| POST | /strategies/rl/train-walkforward | train_walkforward |
| GET | /strategies/rl/status | get_rl_training_status |
| GET | /strategies/rl/models | list_rl_models |
| GET | /strategies/rl/results/{run_id} | get_rl_results |
| POST | /strategies/rl/evaluate | run_rl_evaluation |
| POST | /strategies/rl/deploy | deploy_model |
| GET | /strategies/rl/executor/status | executor_status |
| POST | /strategies/rl/executor/run-now | run_executor_now |
| GET | /strategies/rl/health | rl_strategy_health |

### Reward Tuning History (from inline comments in rl_config.py)

| Run | entry_cost | hold_cost_per_bar | flat_hold_reward | Result |
|-----|-----------|-------------------|------------------|--------|
| 1–5 | -0.10 to -0.20 | (not tracked) | (not tracked) | n_trades=14 (no windowing) |
| 6 | -0.10 | -0.001 | 0.005 | ROOT CAUSE FIXED (windowed episodes) |
| 7 (Scenario C) | -0.05 | -0.001 | 0.000 | hold_rate=98.8%, n_trades=3 |
| 8 (Two-Lever) | **-0.02** | **-0.002** | 0.000 | Current config |

---

*End of RL Code Snapshot — 2026-04-02*
