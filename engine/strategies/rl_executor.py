"""
JARVIS TRADER — RL Strategy Executor
======================================
Autonomous hourly executor: loads trained PPO model, fetches live bar,
predicts action, applies SafetyLayer gate, routes to IBKR paper trading.

Architecture:
    APScheduler (every 1h at bar close: :59, Mon-Fri 07:00-15:00 CT)
      → fetch latest 150 bars for symbol via data_manager (IBKR → Polygon → CSV cache)
      → compute_all_indicators()
      → build observation vector (18 features)
      → RL agent.predict(obs) → action (HOLD/BUY/SELL/CLOSE)
      → SafetyLayer.check_order() gate
      → If BUY/SELL/CLOSE: route to IBKR paper (port 4002) or simulate
      → Log to pipeline_runs table + in-memory status

Usage:
    from strategies.rl_executor import RLExecutor, get_executor_status

    executor = RLExecutor(symbol="MES", model_path="data/rl_models/MES_v1")
    executor.start()
    status = executor.get_status()
    executor.stop()
"""

from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger

    APSCHEDULER_AVAILABLE = True
except ImportError:
    APSCHEDULER_AVAILABLE = False
    BackgroundScheduler = None  # type: ignore[assignment,misc]
    CronTrigger = None  # type: ignore[assignment,misc]

from backtest.signals import compute_all_indicators
from discord.signal_context import DiscordSignalContext
from strategies.rl_config import (
    ACTION_NAMES,
    Action,
)
from strategies.rl_environment import extract_features

logger = logging.getLogger(__name__)


# ── Module-level executor registry ───────────────────────────────────────────
# Keyed by symbol (upper-case). Allows API layer to retrieve/stop any executor.
# _executor_registry_lock guards multi-step read-modify-write sequences that
# span stop() + create + register — Python's GIL only protects individual dict
# operations, not compound sequences.
_executor_registry: dict[str, "RLExecutor"] = {}
_executor_registry_lock: threading.Lock = threading.Lock()


def get_executor_status() -> dict[str, dict]:
    """Return status dict for every executor currently in the registry."""
    with _executor_registry_lock:
        # Snapshot the registry items under the lock so concurrent start/stop
        # operations don't mutate the dict while we iterate it.
        items = list(_executor_registry.items())
    return {symbol: ex.get_status() for symbol, ex in items}


# ── RLExecutor ────────────────────────────────────────────────────────────────


class RLExecutor:
    """
    Autonomous hourly execution loop for a trained PPO model.

    - Loads the model via the lazy-import pattern (avoids importing
      stable-baselines3 at module level so the engine starts even without SB3).
    - Fires on a BackgroundScheduler at minute :59 during CT trading hours.
    - Works in simulation mode when IBKR is not connected — logs the action
      but does NOT place an order.

    Parameters
    ----------
    symbol      : Futures symbol (MES, MNQ, MCL …)
    model_path  : Path to saved PPO model (without .zip extension)
    data_manager: Optional MarketDataManager — used to fetch bars from IBKR
                  if available; falls back to BacktestDataLoader when None or disconnected.
    safety_layer: Optional SafetyLayer — used for pre-trade risk gate.
                  When None, orders are only simulated (no IBKR submission).
    """

    def __init__(
        self,
        symbol: str,
        model_path: str,
        data_manager: Optional[Any] = None,
        safety_layer: Optional[Any] = None,
    ):
        self.symbol = symbol.upper()
        self.model_path = model_path
        self._data_manager = data_manager
        self._safety_layer = safety_layer

        # Scheduler state
        self._scheduler: Optional[BackgroundScheduler] = None
        self._is_running: bool = False

        # Per-cycle state (persists across cycles for position tracking)
        self._paper_position: int = 0  # 1=long, 0=flat, -1=short
        self._entry_price: float = 0.0
        self._bars_in_trade: int = 0

        # Status / telemetry
        self._last_action: Optional[str] = None
        self._last_prediction_time: Optional[str] = None
        self._bars_executed: int = 0
        self._last_error: Optional[str] = None
        self._last_obs: Optional[np.ndarray] = None

        # Lazy-loaded model (loaded once on first run or at start())
        self._agent = None  # RLTradingAgent instance
        self._model_loaded: bool = False

        # Discord signal context for 5 additional RL features (indices 18-22)
        self._discord_ctx = DiscordSignalContext()

        logger.info("[RLExecutor] Created executor for %s | model_path=%s", self.symbol, model_path)

    # ── Model loading (lazy) ──────────────────────────────────────────────

    def _load_model(self) -> bool:
        """
        Load the PPO model. Returns True on success.

        Uses a minimal dummy environment for shape inference only — the
        executor never trains, only infers.
        """
        if self._model_loaded and self._agent is not None:
            return True

        model_file = Path(self.model_path)
        # stable-baselines3 appends .zip automatically
        if not model_file.exists() and not Path(f"{self.model_path}.zip").exists():
            logger.warning(
                "[RLExecutor] Model file not found: %s — executor will run in simulation mode",
                self.model_path,
            )
            self._model_loaded = False
            return False

        try:
            from strategies.rl_agent import RLTradingAgent
            from strategies.rl_environment import build_env

            # Build a minimal DataFrame for a dummy environment (needed by SB3 to
            # know the observation/action shape; no real data required here)
            dummy_df = _build_dummy_df(n_bars=60)
            dummy_env = build_env(self.symbol, dummy_df)
            self._agent = RLTradingAgent.load(
                symbol=self.symbol,
                model_path=self.model_path,
                env=dummy_env,
            )
            self._model_loaded = True
            logger.info("[RLExecutor] Model loaded: %s", self.model_path)
            return True

        except Exception as exc:
            logger.error("[RLExecutor] Failed to load model %s: %s", self.model_path, exc)
            self._last_error = f"model_load_failed: {exc}"
            self._model_loaded = False
            return False

    # ── Bar fetching ──────────────────────────────────────────────────────

    def _fetch_latest_bars(self, n: int = 150) -> Optional[pd.DataFrame]:
        """
        Fetch the most recent *n* 1-hour bars for self.symbol.

        Priority:
          1. data_manager (IBKR) when connected
          2. data_manager.get_bars (Polygon) as fallback
          3. BacktestDataLoader (CSV cache) as final fallback

        Returns a raw OHLCV DataFrame with lower-case column names,
        or None on failure.
        """
        # Try IBKR data_manager first
        if self._data_manager is not None:
            try:
                ibkr = getattr(self._data_manager, "ibkr", None)
                # IBKRDataConnector exposes is_connected() (snake_case); the
                # camelCase isConnected() is ib_insync's raw IB API and does NOT
                # exist on our wrapper — calling it raised AttributeError every
                # cycle, so the IBKR bar path was dead and always fell to Polygon.
                if ibkr is not None and ibkr.is_connected():
                    # Run the async IB fetch in a fresh event loop slice;
                    # the executor runs in a BackgroundScheduler thread.
                    loop = _get_or_create_event_loop()
                    df = loop.run_until_complete(
                        self._data_manager.get_historical_bars(
                            symbol=self.symbol,
                            bar_size="1 hour",
                            n_bars=n,
                        )
                    )
                    if df is not None and len(df) >= 60:
                        df.columns = [c.lower() for c in df.columns]
                        logger.debug(
                            "[RLExecutor] Fetched %d bars via IBKR for %s", len(df), self.symbol
                        )
                        return df
            except Exception as exc:
                logger.warning(
                    "[RLExecutor] IBKR fetch failed for %s (%s) — trying Polygon",
                    self.symbol,
                    exc,
                )

            # Try Polygon via data_manager.get_bars
            try:
                loop = _get_or_create_event_loop()
                df = loop.run_until_complete(
                    self._data_manager.get_bars(
                        symbol=self.symbol,
                        lookback_days=60,
                        timeframe="1h",
                        is_futures=True,
                    )
                )
                if df is not None and len(df) >= 60:
                    df.columns = [c.lower() for c in df.columns]
                    df = df.tail(n).reset_index(drop=True)
                    logger.debug(
                        "[RLExecutor] Fetched %d bars via Polygon for %s", len(df), self.symbol
                    )
                    return df
            except Exception as exc:
                logger.warning(
                    "[RLExecutor] Polygon fetch failed for %s (%s) — falling back to CSV cache",
                    self.symbol,
                    exc,
                )

        # Final fallback: BacktestDataLoader (CSV cache)
        try:
            from datetime import datetime, timedelta

            from backtest.data_loader import BacktestDataLoader

            end_date = datetime.utcnow().strftime("%Y-%m-%d")
            start_date = (datetime.utcnow() - timedelta(days=60)).strftime("%Y-%m-%d")
            loader = BacktestDataLoader()
            df = loader.load(self.symbol, start_date, end_date, "1h")
            if df is not None and len(df) >= 60:
                if isinstance(df.columns, pd.Index):
                    df.columns = [c.lower() for c in df.columns]
                df = df.tail(n).reset_index(drop=True)
                logger.debug(
                    "[RLExecutor] Fetched %d bars via CSV cache for %s", len(df), self.symbol
                )
                return df
        except Exception as exc:
            logger.error(
                "[RLExecutor] BacktestDataLoader fetch failed for %s: %s", self.symbol, exc
            )

        logger.error("[RLExecutor] All data sources failed for %s — cannot fetch bars", self.symbol)
        return None

    # ── Observation builder ───────────────────────────────────────────────

    def _compute_obs(self, df: pd.DataFrame) -> tuple[Optional[np.ndarray], Optional[pd.DataFrame]]:
        """
        Run compute_all_indicators on *df* and build the 23-feature observation
        vector for the most recent bar (last row), using the executor's current
        paper position state.

        Features 0-17: base technical indicators (from extract_features)
        Features 18-22: Discord signal context (from DiscordSignalContext)

        Returns
        -------
        (obs, df_indicators)
            obs          : np.ndarray of shape (23,), or None on failure.
            df_indicators: Fully processed DataFrame with all indicator columns,
                           or None on failure.  Callers can read the last-bar
                           close price directly from this instead of re-running
                           compute_all_indicators().
        """
        try:
            df_ind = compute_all_indicators(df)
            df_ind = df_ind.dropna(subset=["atr", "stc_val"]).reset_index(drop=True)

            if len(df_ind) < 2:
                logger.warning("[RLExecutor] Not enough bars after indicator computation.")
                return None, None

            idx = len(df_ind) - 1
            last_row = df_ind.iloc[idx]
            base_obs = extract_features(
                df=df_ind,
                idx=idx,
                position=self._paper_position,
                entry_price=self._entry_price,
                bars_in_trade=self._bars_in_trade,
                symbol=self.symbol,
            )

            # Append Discord signal context features (indices 18-22)
            try:
                # After reset_index(drop=True) the index is an integer — fall back to now()
                raw_name = last_row.name
                if hasattr(raw_name, "to_pydatetime"):
                    last_ts = raw_name.to_pydatetime()
                else:
                    last_ts = datetime.now(timezone.utc)
                atr_val = float(last_row.get("atr", 1.0) or 1.0)
                price_val = float(last_row.get("close", 0.0) or 0.0)
                discord_feats = self._discord_ctx.get_feature_list(
                    symbol=self.symbol,
                    timestamp=last_ts,
                    price=price_val,
                    atr=atr_val,
                )
                discord_arr = np.array(discord_feats, dtype=np.float32)
            except Exception:
                discord_arr = np.array([0.0, 0.5, 0.0, 0.0, 0.0], dtype=np.float32)

            obs = np.concatenate([base_obs, discord_arr])
            return obs, df_ind

        except KeyError as exc:
            logger.warning(
                "[RLExecutor] Missing column in indicator DataFrame — cannot build obs: %s", exc
            )
            return None, None
        except Exception as exc:
            logger.error("[RLExecutor] Failed to compute observation: %s", exc)
            return None, None

    # ── Action routing ────────────────────────────────────────────────────

    def _route_action(self, action: int, current_price: float) -> dict:
        """
        Apply position-state logic and route action to safety/IB layer.

        Returns a result dict describing what happened.
        """
        action_name = ACTION_NAMES.get(action, "UNKNOWN")
        result: dict[str, Any] = {
            "action": action_name,
            "price": current_price,
            "symbol": self.symbol,
            "position_before": self._paper_position,
            "position_after": self._paper_position,
            "simulated": True,
            "routed_to_ib": False,
            "approved": False,
            "reason": "no_order_needed",
        }

        # Resolve what order direction is needed (None = no order)
        ib_action: Optional[str] = None
        new_position: Optional[int] = None

        if action == Action.BUY:
            if self._paper_position == 0:
                ib_action = "BUY"
                new_position = 1
            elif self._paper_position == -1:
                # Close short + open long
                ib_action = "BUY"
                new_position = 1
            # Already long → HOLD (no-op)

        elif action == Action.SELL:
            if self._paper_position == 0:
                ib_action = "SELL"
                new_position = -1
            elif self._paper_position == 1:
                # Close long + open short
                ib_action = "SELL"
                new_position = -1
            # Already short → HOLD (no-op)

        elif action == Action.CLOSE:
            if self._paper_position == 1:
                ib_action = "SELL"
                new_position = 0
            elif self._paper_position == -1:
                ib_action = "BUY"
                new_position = 0
            # Already flat → HOLD (no-op)

        # action == Action.HOLD → ib_action stays None

        if ib_action is None:
            result["reason"] = "hold_or_noop"
            result["approved"] = True
            return result

        # Safety gate (runs synchronously — check_order is not async)
        safety_approved = True
        rejection_reason = None

        if self._safety_layer is not None:
            # Build a minimal OrderRequest for the gate
            try:
                from risk.safety_layer import OrderRequest

                qty = 1  # RL trades 1 contract
                order = OrderRequest(
                    symbol=self.symbol,
                    quantity=qty if ib_action == "BUY" else -qty,
                    order_type="market",
                    is_futures=True,
                    estimated_value=current_price * qty,
                )
                portfolio_equity = getattr(self._safety_layer, "_current_equity", 0.0) or 10_000.0
                risk_result = self._safety_layer.check_order(order, portfolio_equity)
                safety_approved = risk_result.approved
                rejection_reason = risk_result.rejection_reason
            except Exception as exc:
                logger.warning("[RLExecutor] SafetyLayer check raised: %s", exc)
                safety_approved = False
                rejection_reason = f"safety_check_exception: {exc}"

        if not safety_approved:
            result["approved"] = False
            result["reason"] = rejection_reason or "safety_rejected"
            logger.warning(
                "[RLExecutor] Order REJECTED by SafetyLayer: %s | %s %s @ %.2f",
                rejection_reason,
                ib_action,
                self.symbol,
                current_price,
            )
            return result

        # Attempt IBKR paper submission
        result["approved"] = True
        if (
            self._safety_layer is not None
            and getattr(self._safety_layer, "_ib_gateway", None) is not None
        ):
            try:
                loop = _get_or_create_event_loop()
                ib_result = loop.run_until_complete(
                    self._safety_layer.submit_paper_order(
                        symbol=self.symbol,
                        action=ib_action,
                        quantity=1,
                        price=current_price,
                        order_type="MKT",
                    )
                )
                result["routed_to_ib"] = ib_result.get("routed_to_ib", False)
                result["reason"] = ib_result.get("reason", "submitted")
                result["order_id"] = ib_result.get("order_id")
                result["simulated"] = not result["routed_to_ib"]
            except Exception as exc:
                logger.error("[RLExecutor] IB submission failed: %s", exc)
                result["reason"] = f"ib_submission_error: {exc}"
                result["simulated"] = True
        else:
            result["simulated"] = True
            result["reason"] = "ib_not_connected (simulated)"
            logger.info(
                "[RLExecutor] SIMULATED order: %s %s @ %.2f (no IB gateway)",
                ib_action,
                self.symbol,
                current_price,
            )

        # Fire WhatsApp notifications for BUY/SELL entries and CLOSE exits
        try:
            import asyncio as _aio

            from notifications.openclaw_notifier import (
                notify_signal as _oc_sig,
            )
            from notifications.openclaw_notifier import (
                notify_trade_closed as _oc_tc,
            )

            _loop = _aio.get_event_loop()
            if action_name in ("BUY", "SELL"):
                _coro = _oc_sig(
                    symbol=self.symbol,
                    action=action_name,
                    confidence=0.0,
                    reason=f"RL model → pos {self._paper_position}→{new_position}",
                    market=self.symbol,
                )
            elif action_name == "CLOSE":
                _entry = self._entry_price or current_price
                _pnl_est = (current_price - _entry) * (1 if self._paper_position == 1 else -1)
                _coro = _oc_tc(
                    symbol=self.symbol,
                    action=ib_action,
                    entry_price=_entry,
                    exit_price=current_price,
                    pnl=_pnl_est,
                    quantity=1,
                )
            else:
                _coro = None

            if _coro is not None:
                if _loop.is_running():
                    _loop.create_task(_coro)
                else:
                    _loop.run_until_complete(_coro)
        except Exception:
            pass  # Non-blocking, best-effort

        # Update paper position state
        if new_position is not None:
            if new_position != 0:
                self._entry_price = current_price
                self._bars_in_trade = 0
            else:
                self._entry_price = 0.0
                self._bars_in_trade = 0
            self._paper_position = new_position

        result["position_after"] = self._paper_position
        return result

    # ── Single execution cycle ────────────────────────────────────────────

    def run_once(self) -> dict:
        """
        Execute one full prediction + routing cycle.

        Callable manually (e.g., from the API) or triggered by the scheduler.

        Returns a status dict describing what happened.
        """
        now_utc = datetime.now(timezone.utc).isoformat()
        logger.info("[RLExecutor] run_once() called for %s at %s", self.symbol, now_utc)

        # 1. Kill switch fast-path
        if self._safety_layer is not None and getattr(self._safety_layer, "is_killed", False):
            logger.warning("[RLExecutor] Kill switch active — skipping cycle for %s", self.symbol)
            self._last_action = "HOLD (kill_switch)"
            self._last_prediction_time = now_utc
            return {
                "symbol": self.symbol,
                "action": "HOLD",
                "reason": "kill_switch_active",
                "timestamp": now_utc,
                "simulated": True,
            }

        # 2. Ensure model is loaded
        if not self._model_loaded:
            ok = self._load_model()
            if not ok:
                logger.warning(
                    "[RLExecutor] Model not loaded — running in pure-simulation mode for %s",
                    self.symbol,
                )

        # 3. Fetch bars
        raw_df = self._fetch_latest_bars(n=150)
        if raw_df is None or len(raw_df) < 60:
            self._last_error = "insufficient_bars"
            logger.error(
                "[RLExecutor] Could not fetch enough bars for %s — skipping cycle", self.symbol
            )
            return {
                "symbol": self.symbol,
                "action": "HOLD",
                "reason": "insufficient_bars",
                "timestamp": now_utc,
                "error": self._last_error,
            }

        # 4. Compute observation
        # _compute_obs returns (obs, df_indicators) so we can reuse the
        # processed DataFrame for the current-bar price without a second
        # expensive compute_all_indicators() call.
        obs, df_ind = self._compute_obs(raw_df)
        if obs is None:
            self._last_error = "obs_computation_failed"
            logger.error(
                "[RLExecutor] Observation computation failed for %s — skipping cycle", self.symbol
            )
            return {
                "symbol": self.symbol,
                "action": "HOLD",
                "reason": "obs_computation_failed",
                "timestamp": now_utc,
                "error": self._last_error,
            }

        self._last_obs = obs

        # 5. Predict
        kill_switch_active = (
            self._safety_layer.is_killed if self._safety_layer is not None else False
        )

        if self._model_loaded and self._agent is not None:
            try:
                action = self._agent.predict(obs, kill_switch_active=kill_switch_active)
            except Exception as exc:
                logger.error("[RLExecutor] Agent predict() raised: %s", exc)
                action = int(Action.HOLD)
        else:
            # No model — always HOLD in simulation
            action = int(Action.HOLD)

        action_name = ACTION_NAMES.get(action, "UNKNOWN")
        logger.info(
            "[RLExecutor] %s predicted action=%s (pos=%d, bars_in_trade=%d)",
            self.symbol,
            action_name,
            self._paper_position,
            self._bars_in_trade,
        )

        # 6. Get current price from the already-processed DataFrame.
        # df_ind is guaranteed non-None here (obs is not None).
        # Avoids re-running compute_all_indicators() a second time.
        try:
            current_price = float(df_ind.iloc[-1]["close"])
        except Exception:
            current_price = float(raw_df.iloc[-1]["close"])

        # 7. Route action through safety layer / IB
        route_result = self._route_action(action, current_price)

        # 8. Increment bars_in_trade if still in a position AFTER the action
        # has been applied (position state updated inside _route_action).
        # This matches the training environment (TradingEnvironment.step) where
        # bars_in_trade increments at the END of each step after the position
        # is already updated — keeping inference and training in sync.
        if self._paper_position != 0:
            self._bars_in_trade += 1

        # 9. Update telemetry
        self._last_action = action_name
        self._last_prediction_time = now_utc
        self._bars_executed += 1
        self._last_error = None

        cycle_result = {
            "symbol": self.symbol,
            "timestamp": now_utc,
            "action": action_name,
            "price": current_price,
            "position": self._paper_position,
            "bars_in_trade": self._bars_in_trade,
            "routed_to_ib": route_result.get("routed_to_ib", False),
            "simulated": route_result.get("simulated", True),
            "approved": route_result.get("approved", False),
            "reason": route_result.get("reason", ""),
        }

        logger.info(
            "[RLExecutor] Cycle complete: %s | action=%s | pos=%d | price=%.2f | routed=%s",
            self.symbol,
            action_name,
            self._paper_position,
            current_price,
            route_result.get("routed_to_ib", False),
        )

        # 10. Persist to pipeline_runs table so every RL prediction is auditable.
        #     Uses get_db() which returns None-safe (logs a warning and skips if
        #     the DB singleton was not initialised yet — executor can run standalone).
        try:
            from database.schema import get_db

            db = get_db()
            db.insert_pipeline_run(
                {
                    "run_id": uuid.uuid4().hex[:8],
                    "symbol": self.symbol,
                    "source": "rl_executor",
                    "webhook_action": action_name,
                    "final_action": action_name.lower(),
                    "final_quantity": 1,
                    "requires_human": False,
                    "status": "completed",
                    "summary": (
                        f"RL {action_name} @ {current_price:.2f} | "
                        f"pos={self._paper_position} | "
                        f"routed_to_ib={route_result.get('routed_to_ib', False)}"
                    ),
                    "duration_ms": None,
                    "created_at": now_utc,
                }
            )
        except RuntimeError:
            # DB not initialised (standalone / test usage) — skip silently
            logger.debug("[RLExecutor] DB not initialised — skipping pipeline_runs insert")
        except Exception as db_exc:
            logger.warning("[RLExecutor] Failed to log to pipeline_runs: %s", db_exc)

        return cycle_result

    # ── Scheduler management ──────────────────────────────────────────────

    def start(self) -> None:
        """
        Start the APScheduler background job.

        Fires at minute :59 of every hour, Mon–Fri, 07:00–15:00 CT
        (covers pre-market + RTH for MES/MNQ/MCL).
        """
        if self._is_running:
            logger.warning("[RLExecutor] Executor already running for %s", self.symbol)
            return

        if not APSCHEDULER_AVAILABLE:
            raise ImportError("apscheduler is required: pip install apscheduler")

        # Attempt to pre-load model so first cycle fires immediately
        self._load_model()

        self._scheduler = BackgroundScheduler(timezone="America/Chicago")
        self._scheduler.add_job(
            self.run_once,
            CronTrigger(
                day_of_week="mon-fri",
                hour="7-15",
                minute=59,
                timezone="America/Chicago",
            ),
            id=f"rl_executor_{self.symbol}",
            replace_existing=True,
            misfire_grace_time=300,  # 5-minute grace window
        )
        # Register in module-level registry BEFORE starting the scheduler so
        # there is never a window where the scheduler is running but the
        # executor is not visible to get_executor_status().
        with _executor_registry_lock:
            _executor_registry[self.symbol] = self

        self._scheduler.start()
        self._is_running = True

        logger.info(
            "[RLExecutor] Scheduler started for %s — fires at :59 every hour "
            "Mon-Fri 07:00-15:00 CT",
            self.symbol,
        )

    def stop(self) -> None:
        """Stop the scheduler and remove from registry."""
        if self._scheduler is not None and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
        self._scheduler = None
        self._is_running = False
        with _executor_registry_lock:
            _executor_registry.pop(self.symbol, None)
        logger.info("[RLExecutor] Scheduler stopped for %s", self.symbol)

    # ── Status ────────────────────────────────────────────────────────────

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
        scheduler_running = self._scheduler is not None and self._scheduler.running
        # Expose obs shape (not the full array) so callers can verify the
        # feature vector is the expected (N_FEATURES,) without JSON serialisation issues.
        last_obs_shape = list(self._last_obs.shape) if self._last_obs is not None else None
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


# ── Helpers ───────────────────────────────────────────────────────────────────


def _build_dummy_df(n_bars: int = 60) -> pd.DataFrame:
    """
    Build a minimal synthetic OHLCV DataFrame with plausible values.
    Used only to construct a dummy TradingEnvironment for SB3 shape inference.
    """
    rng = np.random.default_rng(42)
    closes = 5_000.0 + np.cumsum(rng.normal(0, 10, n_bars))
    highs = closes + rng.uniform(0, 20, n_bars)
    lows = closes - rng.uniform(0, 20, n_bars)
    opens = closes - rng.normal(0, 5, n_bars)
    vols = rng.integers(10_000, 100_000, n_bars).astype(float)
    return pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": vols,
        }
    )


def _get_or_create_event_loop() -> asyncio.AbstractEventLoop:
    """
    Return an event loop suitable for running coroutines from a
    BackgroundScheduler (non-async) thread.

    Python 3.10+ deprecated ``asyncio.get_event_loop()`` when called with no
    running loop — it emits a DeprecationWarning and will raise RuntimeError
    in future versions.  We always create a fresh loop in scheduler threads
    because there is guaranteed to be no running loop there.  Using
    ``get_running_loop()`` confirms this: if it raises RuntimeError (no running
    loop), we create and register a new one.  If it somehow succeeds (caller
    is already inside an async context), we return it so the caller can use
    ``loop.run_until_complete()`` safely — though that path should not occur
    in normal BackgroundScheduler usage.
    """
    try:
        # Will raise RuntimeError when no loop is running — the expected path
        # in a BackgroundScheduler thread.
        return asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop
