"""
JARVIS TRADER — RL Trading Agent
==================================
PPO-based trading agent wrapping stable-baselines3.
All actions are validated through SafetyLayer before execution.

Usage:
    from strategies.rl_agent import RLTradingAgent

    agent = RLTradingAgent(symbol="MES", env=env)
    agent.train(timesteps=100_000)
    action = agent.predict(obs)
    agent.save("data/rl_models/MES_v1")
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np

# ── Lazy SB3/torch import ─────────────────────────────────────────────────────
# stable-baselines3 pulls in torch, whose first import compiles bytecode for
# minutes and holds the GIL. Importing it eagerly at module load (this module is
# imported via strategies_router -> rl_trainer at engine boot) froze the event
# loop: /health returned 000 and port_guardian killed the engine every 360s
# (crash loop, 2026-08-17). RL is disabled by default (ENABLE_RL_TRADING=False),
# so defer the import until an agent is actually constructed.

SB3_AVAILABLE: bool = False
PPO = None  # type: ignore
BaseCallback = None  # type: ignore


def _ensure_sb3() -> bool:
    """Import stable-baselines3 on first real use (lazy, off the boot path).

    Returns True when SB3 is importable. On failure sets SB3_AVAILABLE=False
    so the agent's ImportError path (__init__) stays authoritative. Never
    raises into the caller — a training/model-load call is the only place that
    should surface a missing-SB3 error.
    """
    global SB3_AVAILABLE, PPO, BaseCallback, TrainingProgressCallback
    if SB3_AVAILABLE:
        return True
    try:
        from stable_baselines3 import PPO as _PPO  # type: ignore[import]
        from stable_baselines3.common.callbacks import (
            BaseCallback as _BaseCallback,  # type: ignore[import]
        )

        PPO = _PPO
        BaseCallback = _BaseCallback
        SB3_AVAILABLE = True

        class TrainingProgressCallback(BaseCallback):  # noqa: F811
            """
            Logs episode reward and action distribution at each checkpoint interval.
            Stores progress for retrieval via the API.
            """

            def __init__(self, log_interval: int = 1000, verbose: int = 0):
                super().__init__(verbose=verbose)
                self.log_interval = log_interval
                self.episode_rewards: list[float] = []
                self.action_counts: dict[str, int] = dict.fromkeys(ACTION_NAMES.values(), 0)
                self._last_log_step = 0

            def _on_step(self) -> bool:
                # Track actions
                if hasattr(self, "locals") and "actions" in self.locals:
                    for act in np.atleast_1d(self.locals["actions"]):
                        name = ACTION_NAMES.get(int(act), "UNKNOWN")
                        self.action_counts[name] = self.action_counts.get(name, 0) + 1

                # Log at interval
                if self.num_timesteps - self._last_log_step >= self.log_interval:
                    self._last_log_step = self.num_timesteps
                    if self.model.ep_info_buffer:
                        mean_reward = np.mean([ep["r"] for ep in self.model.ep_info_buffer])
                        self.episode_rewards.append(float(mean_reward))
                        logger.debug(
                            f"[RL] Step {self.num_timesteps:,} | "
                            f"Mean ep reward: {mean_reward:.4f} | "
                            f"Actions: {self.action_counts}"
                        )
                return True

            def get_summary(self) -> dict:
                total = sum(self.action_counts.values()) or 1
                return {
                    "timesteps": self.num_timesteps,
                    "episode_rewards": self.episode_rewards[-20:],  # last 20 checkpoints
                    "action_distribution": {
                        k: round(v / total, 4) for k, v in self.action_counts.items()
                    },
                }

    except Exception as exc:  # noqa: BLE001 — lazy path must degrade cleanly
        logger.warning("[RL] stable-baselines3 unavailable (lazy import failed): %s", exc)
        SB3_AVAILABLE = False
        PPO = None
        BaseCallback = None
    return SB3_AVAILABLE


class TrainingProgressCallback:  # noqa
    """Dummy stub when stable-baselines3 is not available or not yet imported."""

    def __init__(self, *args, **kwargs):
        pass

from strategies.rl_config import (  # noqa: E402
    ACTION_NAMES,
    PPO_CONFIG,
    RL_MODELS_DIR,
    VALIDATION_GATES,
    Action,
)
from strategies.rl_environment import TradingEnvironment  # noqa: E402

logger = logging.getLogger(__name__)


# ── Agent ─────────────────────────────────────────────────────────────────────


class RLTradingAgent:
    """
    PPO trading agent for jarvis-trader.

    Safety contract: predict() returns Action.HOLD when safety checks fail.
    The caller is responsible for passing valid observations.

    Parameters
    ----------
    symbol      : Futures symbol (MES, MNQ, MCL)
    env         : TradingEnvironment instance used for training
    model_path  : Optional path to load a pre-trained model
    """

    def __init__(
        self,
        symbol: str,
        env: TradingEnvironment,
        model_path: Optional[str] = None,
    ):
        if not _ensure_sb3():
            raise ImportError("stable-baselines3 is required: pip install stable-baselines3[extra]")

        self.symbol = symbol.upper()
        self.env = env
        self._callback = TrainingProgressCallback(log_interval=1000)
        self._is_trained = False
        self._training_metadata: dict = {}

        if model_path and Path(model_path).exists():
            logger.info(f"[RL] Loading model from {model_path}")
            self.model = PPO.load(model_path, env=env)
            self._is_trained = True
        else:
            self.model = PPO(
                policy=PPO_CONFIG["policy"],
                env=env,
                learning_rate=PPO_CONFIG["learning_rate"],
                n_steps=PPO_CONFIG["n_steps"],
                batch_size=PPO_CONFIG["batch_size"],
                n_epochs=PPO_CONFIG["n_epochs"],
                gamma=PPO_CONFIG["gamma"],
                gae_lambda=PPO_CONFIG["gae_lambda"],
                clip_range=PPO_CONFIG["clip_range"],
                ent_coef=PPO_CONFIG["ent_coef"],
                vf_coef=PPO_CONFIG["vf_coef"],
                max_grad_norm=PPO_CONFIG["max_grad_norm"],
                verbose=PPO_CONFIG["verbose"],
            )

    # ── Training ──────────────────────────────────────────────────────────

    def train(self, total_timesteps: int = 100_000) -> dict:
        """
        Train the PPO agent.

        Parameters
        ----------
        total_timesteps : Number of environment steps for training

        Returns
        -------
        Training summary dict with action distribution and reward history
        """
        if not SB3_AVAILABLE:
            raise ImportError("stable-baselines3 required")

        logger.info(f"[RL] Training {self.symbol} agent for {total_timesteps:,} timesteps...")
        start = datetime.now(timezone.utc)

        self._callback = TrainingProgressCallback(log_interval=max(1000, total_timesteps // 100))

        self.model.learn(
            total_timesteps=total_timesteps,
            callback=self._callback,
            reset_num_timesteps=True,
            progress_bar=False,
        )

        elapsed = (datetime.now(timezone.utc) - start).total_seconds()
        self._is_trained = True

        summary = self._callback.get_summary()
        summary["elapsed_seconds"] = round(elapsed, 1)
        summary["total_timesteps"] = total_timesteps
        summary["symbol"] = self.symbol
        self._training_metadata = summary

        hold_rate = summary["action_distribution"].get("HOLD", 0.0)
        logger.info(f"[RL] Training complete in {elapsed:.0f}s | " f"HOLD rate: {hold_rate:.1%}")
        return summary

    # ── Inference ─────────────────────────────────────────────────────────

    def predict(self, obs: np.ndarray, kill_switch_active: bool = False) -> int:
        """
        Get next action for the given observation.

        Safety rules:
        - If kill_switch_active is True → always return HOLD
        - If model not trained → return HOLD

        Parameters
        ----------
        obs                : Observation array of shape (N_FEATURES,)
        kill_switch_active : Pass True when SafetyLayer.is_killed is True

        Returns
        -------
        int action from Action enum
        """
        if kill_switch_active:
            logger.debug("[RL] Kill switch active — forced HOLD")
            return int(Action.HOLD)

        if not self._is_trained:
            logger.warning("[RL] Model not trained yet — returning HOLD")
            return int(Action.HOLD)

        action, _ = self.model.predict(np.array(obs, dtype=np.float32), deterministic=True)
        return int(action)

    # ── Evaluation ────────────────────────────────────────────────────────

    def evaluate(self, test_env: TradingEnvironment, n_episodes: int = 1) -> dict:
        """
        Evaluate agent on a test environment.

        Returns
        -------
        dict with episode metrics averaged over n_episodes
        """
        if not self._is_trained:
            raise RuntimeError("Train the agent before evaluating.")

        all_metrics: list[dict] = []
        for i in range(n_episodes):
            # Pass seed=i so each episode gets an independent random start when
            # the test env has a windowed max_episode_bars < len(df).  For the
            # full-dataset eval path (max_episode_bars == len(df)) the seed has
            # no effect because latest_start == warm_up and the start is fixed,
            # but seeding defensively ensures correct behaviour if the caller
            # switches to a windowed test env.
            obs, _ = test_env.reset(seed=i)
            done = False
            while not done:
                action = self.predict(obs)
                obs, _reward, terminated, truncated, _info = test_env.step(action)
                done = terminated or truncated
            all_metrics.append(test_env.get_episode_metrics())

        # Average across episodes — use union of all keys for forward/backward compat
        keys = set().union(*[m.keys() for m in all_metrics])
        averaged = {k: round(float(np.mean([m.get(k, 0.0) for m in all_metrics])), 4) for k in keys}

        # Explicitly surface flat_hold_rate (backward compat: default 0.0 if missing).
        # flat_hold_rate = HOLD actions when flat / total flat bars.
        # This is the meaningful overtrading signal — unlike the blended hold_rate from
        # the PPO callback which includes HOLD-while-in-position.
        averaged["flat_hold_rate"] = round(
            sum(m.get("flat_hold_rate", 0.0) for m in all_metrics) / max(len(all_metrics), 1),
            4,
        )

        # Check validation gates
        gates = VALIDATION_GATES

        # Action distribution from training callback (blended: includes HOLD-in-position)
        hold_rate = 0.0
        if self._training_metadata.get("action_distribution"):
            hold_rate = self._training_metadata["action_distribution"].get("HOLD", 0.0)
            averaged["hold_rate"] = hold_rate
            averaged["passes_hold_gate"] = hold_rate >= gates["min_hold_rate"]

        # Compute Sharpe from per-episode trades (mirrors OOSEvaluator._compute_sharpe)
        sharpe_values = []
        for ep_env in [test_env]:
            trades = getattr(ep_env, "_episode_trades", [])
            if trades and len(trades) >= 2:
                returns = np.array([t["pnl"] / ep_env.initial_capital for t in trades])
                mean_r = float(np.mean(returns))
                std_r = float(np.std(returns))
                if std_r >= 1e-9:
                    sharpe_values.append((mean_r / std_r) * np.sqrt(252))
        sharpe = round(float(np.mean(sharpe_values)), 4) if sharpe_values else 0.0
        averaged["sharpe"] = sharpe
        averaged["passes_sharpe_gate"] = sharpe >= gates["min_sharpe"]

        averaged["passes_validation"] = all(
            [
                averaged.get("profit_factor", 0) >= gates["min_profit_factor"],
                averaged.get("win_rate", 0) >= gates["min_win_rate"],
                averaged.get("max_drawdown", 1) <= gates["max_drawdown"],
                averaged.get("n_trades", 0) >= gates["min_trades"],
                hold_rate >= gates["min_hold_rate"],
                sharpe >= gates["min_sharpe"],
            ]
        )

        # TODO (recommendation): add flat_hold_rate validation gate once sufficient OOS data:
        #   averaged["passes_flat_hold_gate"] = averaged["flat_hold_rate"] >= 0.50
        # flat_hold_rate >= 0.50 is a stronger overtrading guard than the blended hold_rate
        # because it isolates the decision quality when the agent has no open position.
        # Suggested addition to VALIDATION_GATES in rl_config.py:
        #   "min_flat_hold_rate": 0.50

        return averaged

    # ── Persistence ───────────────────────────────────────────────────────

    def save(self, path: Optional[str] = None) -> str:
        """
        Save model to disk. Returns the saved model path.

        Parameters
        ----------
        path : Optional save path (without .zip extension).
               Defaults to data/rl_models/{SYMBOL}_{timestamp}
        """
        if not self._is_trained:
            raise RuntimeError("Cannot save untrained model.")

        if path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            RL_MODELS_DIR.mkdir(parents=True, exist_ok=True)
            path = str(RL_MODELS_DIR / f"{self.symbol}_{timestamp}")

        self.model.save(path)

        # Save metadata alongside model
        meta_path = f"{path}.json"
        with open(meta_path, "w") as f:
            json.dump(self._training_metadata, f, indent=2, default=str)

        logger.info(f"[RL] Model saved to {path}.zip")
        return path

    @classmethod
    def load(cls, symbol: str, model_path: str, env: TradingEnvironment) -> "RLTradingAgent":
        """Load a previously saved agent."""
        agent = cls(symbol=symbol, env=env, model_path=model_path)

        # Load metadata if available
        meta_path = f"{model_path}.json"
        if Path(meta_path).exists():
            with open(meta_path) as f:
                agent._training_metadata = json.load(f)
        return agent

    # ── Status ────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        summary = self._callback.get_summary() if self._callback else {}
        return {
            "symbol": self.symbol,
            "is_trained": self._is_trained,
            "timesteps_trained": summary.get("timesteps", 0),
            "action_distribution": summary.get("action_distribution", {}),
            "last_rewards": summary.get("episode_rewards", []),
        }
