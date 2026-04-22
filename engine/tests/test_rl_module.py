"""
JARVIS TRADER — RL Module Tests
=================================
Tests for rl_config, rl_environment, rl_agent (safety contract).
All tests use synthetic data — no network calls required.
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
import pytest

# ── Synthetic data factory ────────────────────────────────────────────────────


def _make_synthetic_ohlcv(n_bars: int = 300) -> pd.DataFrame:
    """
    Create a synthetic OHLCV + indicator DataFrame suitable for TradingEnvironment.

    Includes all columns that extract_features and compute_all_indicators would produce:
    atr, stc_val, ema_21, ema_trend, phase_val, volume_signal, etc.
    """
    rng = np.random.default_rng(seed=42)

    close = 5000.0 + np.cumsum(rng.normal(0, 5, n_bars))
    high = close + rng.uniform(2, 10, n_bars)
    low = close - rng.uniform(2, 10, n_bars)
    open_ = close + rng.normal(0, 3, n_bars)
    volume = rng.integers(1000, 10000, n_bars).astype(float)

    atr = rng.uniform(8, 20, n_bars)

    df = pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            # Required indicator columns
            "atr": atr,
            "stc_val": rng.uniform(10, 90, n_bars),
            "ema_21": close * rng.uniform(0.99, 1.01, n_bars),
            "ema_trend": rng.choice(["bullish", "neutral", "bearish"], n_bars),
            "phase_val": rng.uniform(-50, 50, n_bars),
            "volume_signal": rng.choice(["buyer_dominant", "balanced", "seller_dominant"], n_bars),
            # Additional columns that layer1_regime may access
            "macd_hist": rng.normal(0, 1, n_bars),
            "rsi": rng.uniform(30, 70, n_bars),
            "bb_upper": close + atr * 2,
            "bb_lower": close - atr * 2,
            "adx": rng.uniform(15, 45, n_bars),
        }
    )
    return df


def _make_env(n_bars: int = 300):
    """Build a TradingEnvironment with synthetic data."""
    from strategies.rl_environment import TradingEnvironment

    df = _make_synthetic_ohlcv(n_bars)
    return TradingEnvironment(symbol="MES", df=df, initial_capital=10_000.0)


# ── Test: config ──────────────────────────────────────────────────────────────


class TestRLConfig:
    def test_rl_config_valid(self):
        """TradingConfig values are in valid ranges."""
        from strategies.rl_config import (
            N_ACTIONS,
            N_FEATURES,
            PPO_CONFIG,
            REWARD_CONFIG,
            VALIDATION_GATES,
        )

        assert PPO_CONFIG["learning_rate"] > 0, "learning_rate must be positive"
        assert PPO_CONFIG["n_steps"] > 0, "n_steps must be positive"
        assert PPO_CONFIG["batch_size"] > 0, "batch_size must be positive"
        assert 0.0 < PPO_CONFIG["gamma"] <= 1.0, "gamma must be in (0, 1]"
        assert 0.0 <= PPO_CONFIG["clip_range"] <= 1.0, "clip_range must be in [0, 1]"

        assert REWARD_CONFIG["entry_cost"] < 0, "entry_cost should penalise overtrading"
        assert REWARD_CONFIG["flat_hold_reward"] >= 0, "flat_hold_reward should be non-negative"

        assert VALIDATION_GATES["min_profit_factor"] > 1.0
        assert 0.0 < VALIDATION_GATES["min_win_rate"] < 1.0
        assert VALIDATION_GATES["max_drawdown"] < 1.0
        assert VALIDATION_GATES["min_hold_rate"] >= 0.0

        assert N_FEATURES == 23, f"Expected 23 features, got {N_FEATURES}"
        assert N_ACTIONS == 4, f"Expected 4 actions, got {N_ACTIONS}"

    def test_action_enum_values(self):
        """Action enum integer values are stable."""
        from strategies.rl_config import Action

        assert int(Action.HOLD) == 0
        assert int(Action.BUY) == 1
        assert int(Action.SELL) == 2
        assert int(Action.CLOSE) == 3

    def test_get_instrument_params_defaults(self):
        """get_instrument_params returns valid tuple for known and unknown symbols."""
        from strategies.rl_config import get_instrument_params

        mes_params = get_instrument_params("MES")
        assert len(mes_params) == 7
        assert mes_params[0] < mes_params[1], "stc_os must be < stc_ob"

        # Unknown symbol falls back to defaults
        unknown = get_instrument_params("UNKNOWN_SYM")
        assert len(unknown) == 7


# ── Test: environment ─────────────────────────────────────────────────────────


class TestRLEnvironment:
    def test_rl_environment_reset(self):
        """env.reset() returns a valid observation with correct shape."""
        from strategies.rl_config import N_FEATURES

        env = _make_env()
        obs, info = env.reset()

        assert obs.shape == (N_FEATURES,), f"Expected ({N_FEATURES},), got {obs.shape}"
        assert obs.dtype == np.float32
        assert not np.any(np.isnan(obs)), "Observation must not contain NaN"
        assert not np.any(np.isinf(obs)), "Observation must not contain Inf"
        assert isinstance(info, dict)

    def test_rl_environment_step_hold(self):
        """env.step(HOLD=0) advances bar without error."""
        env = _make_env()
        obs, _ = env.reset()

        obs2, reward, terminated, truncated, info = env.step(0)  # HOLD

        assert obs2.shape == obs.shape
        assert isinstance(reward, float)
        assert isinstance(terminated, bool)
        assert isinstance(truncated, bool)
        assert truncated is False, "truncated is always False per spec"
        assert isinstance(info, dict)
        assert "n_trades" in info

    def test_rl_environment_step(self):
        """env.reset() and env.step(0) work without error (HOLD action)."""
        env = _make_env()
        obs, _ = env.reset()

        # Run a few HOLD steps to verify the episode loop is stable
        for _ in range(10):
            obs, reward, terminated, truncated, info = env.step(0)
            if terminated:
                break

        assert obs is not None

    def test_rl_environment_buy_sell_close(self):
        """BUY, SELL, CLOSE actions execute without raising exceptions."""
        from strategies.rl_config import Action

        env = _make_env(n_bars=200)
        env.reset()

        env.step(int(Action.BUY))  # open long
        env.step(int(Action.HOLD))  # hold
        env.step(int(Action.CLOSE))  # close long
        env.step(int(Action.SELL))  # open short
        env.step(int(Action.CLOSE))  # close short

    def test_rl_environment_episode_metrics(self):
        """get_episode_metrics returns dict with expected keys."""
        env = _make_env()
        obs, _ = env.reset()

        # Run to termination
        done = False
        while not done:
            obs, _r, terminated, truncated, _info = env.step(0)  # all HOLD
            done = terminated or truncated

        metrics = env.get_episode_metrics()
        for key in ("n_trades", "win_rate", "profit_factor", "total_pnl", "max_drawdown"):
            assert key in metrics, f"Missing key: {key}"

    def test_rl_environment_full_episode_no_crash(self):
        """A full episode with random actions completes without crashing."""
        rng = np.random.default_rng(seed=99)
        env = _make_env(n_bars=150)
        env.reset()

        done = False
        steps = 0
        while not done:
            action = int(rng.integers(0, 4))
            _obs, _r, terminated, truncated, _info = env.step(action)
            done = terminated or truncated
            steps += 1

        assert steps > 0


# ── Test: safety layer integration ───────────────────────────────────────────


class TestSafetyLayerBlocks:
    def test_safety_layer_blocks_when_killed(self, mock_safety_layer):
        """When kill switch is active, agent.predict() must return HOLD (0)."""
        from strategies.rl_agent import RLTradingAgent
        from strategies.rl_config import Action

        env = _make_env()
        agent = RLTradingAgent(symbol="MES", env=env)

        # Agent is untrained — still should return HOLD when kill switch active
        fake_obs = np.zeros(18, dtype=np.float32)
        action = agent.predict(fake_obs, kill_switch_active=True)

        assert action == int(
            Action.HOLD
        ), f"Expected HOLD ({int(Action.HOLD)}) when kill switch active, got {action}"

    def test_safety_layer_blocks_untrained_agent(self):
        """Untrained agent always returns HOLD regardless of observation."""
        from strategies.rl_agent import RLTradingAgent
        from strategies.rl_config import Action

        env = _make_env()
        agent = RLTradingAgent(symbol="MES", env=env)

        obs = np.random.rand(18).astype(np.float32)
        action = agent.predict(obs, kill_switch_active=False)

        assert action == int(Action.HOLD), f"Untrained agent must return HOLD, got {action}"

    def test_kill_switch_reason_manual(self, mock_safety_layer):
        """Kill switch activated with MANUAL reason is captured correctly."""
        from risk.safety_layer import KillSwitchReason

        safety = mock_safety_layer
        safety.activate_kill_switch(KillSwitchReason.MANUAL, "Test halt")

        assert safety.is_killed is True
        status = safety.get_status()
        assert status.get("is_killed") is True

    def test_kill_switch_sync_no_coroutine_runtime_warnings(self, mock_safety_layer):
        """activate/deactivate from sync context must not discard coroutines (no RuntimeWarning)."""
        from risk.safety_layer import KillSwitchReason

        with warnings.catch_warnings(record=True) as recorded:
            warnings.simplefilter("always", category=RuntimeWarning)
            mock_safety_layer.activate_kill_switch(KillSwitchReason.MANUAL, "sync test")
            mock_safety_layer.deactivate_kill_switch("tester")

        bad = [
            w
            for w in recorded
            if issubclass(w.category, RuntimeWarning) and "never awaited" in str(w.message).lower()
        ]
        assert not bad, f"Unexpected RuntimeWarning(s): {[str(w.message) for w in bad]}"
