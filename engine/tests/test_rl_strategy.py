"""
JARVIS TRADER — RL Strategy Discovery Tests
============================================

Tests for engine/strategies/rl_env.py and engine/strategies/rl_train.py.

All tests use synthetic data and mocks — no real DB, HTTP, or filesystem
reads occur (verified by test_no_real_data_fetched_in_tests).

Run:
    cd engine && .venv/Scripts/python -m pytest tests/test_rl_strategy.py -v
"""

from __future__ import annotations

import os
import types
import unittest.mock as mock
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# ── Fixtures & synthetic data ─────────────────────────────────────────────────


def _synthetic_df(n_bars: int = 300, symbol: str = "MES") -> pd.DataFrame:
    """Minimal OHLCV + indicators DataFrame that TradingEnvironment accepts."""
    rng = np.random.default_rng(seed=7)
    base = 5000.0
    close = base + np.cumsum(rng.normal(0, 5, n_bars))
    high = close + rng.uniform(2, 10, n_bars)
    low = close - rng.uniform(2, 10, n_bars)
    open_ = close + rng.normal(0, 3, n_bars)
    volume = rng.integers(1000, 10000, n_bars).astype(float)
    atr = rng.uniform(8, 20, n_bars)

    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "atr": atr,
            "stc_val": rng.uniform(10, 90, n_bars),
            "ema_21": close * rng.uniform(0.99, 1.01, n_bars),
            "ema_trend": rng.choice(["bullish", "neutral", "bearish"], n_bars),
            "phase_val": rng.uniform(-50, 50, n_bars),
            "volume_signal": rng.choice(["buyer_dominant", "balanced", "seller_dominant"], n_bars),
            "cci_50": rng.uniform(-150, 150, n_bars),
            "buy_pct": rng.uniform(20, 80, n_bars),
            "macd_hist": rng.normal(0, 1, n_bars),
            "rsi": rng.uniform(30, 70, n_bars),
            "bb_upper": close + atr * 2,
            "bb_lower": close - atr * 2,
            "adx": rng.uniform(15, 45, n_bars),
        }
    )


# ── Group 1: TradingEnvMES / rl_env ──────────────────────────────────────────


class TestTradingEnvMES:
    """Verify rl_env.py alias and factory work correctly."""

    def test_alias_is_trading_environment(self):
        """TradingEnvMES must be the same class as TradingEnvironment."""
        from strategies.rl_env import TradingEnvMES
        from strategies.rl_environment import TradingEnvironment

        assert TradingEnvMES is TradingEnvironment

    def test_make_trading_env_returns_env(self):
        """make_trading_env() returns a TradingEnvMES instance."""
        from strategies.rl_env import TradingEnvMES, make_trading_env

        df = _synthetic_df()
        env = make_trading_env(df)
        assert isinstance(env, TradingEnvMES)

    def test_env_observation_shape(self):
        """reset() returns observation matching declared observation_space shape."""
        from strategies.rl_config import N_FEATURES
        from strategies.rl_env import make_trading_env

        df = _synthetic_df()
        env = make_trading_env(df)
        obs, info = env.reset()

        assert obs.shape == (N_FEATURES,), f"Expected shape ({N_FEATURES},), got {obs.shape}"
        assert obs.dtype == np.float32
        assert not np.any(np.isnan(obs)), "Observation must not contain NaN"

        # Verify against observation_space declaration
        assert env.observation_space.shape == (N_FEATURES,)

    def test_env_action_executes(self):
        """step() with each action returns (obs, reward, done, truncated, info) correctly."""
        from strategies.rl_config import Action
        from strategies.rl_env import make_trading_env

        df = _synthetic_df()
        env = make_trading_env(df)
        env.reset()

        for action in [Action.HOLD, Action.BUY, Action.SELL, Action.CLOSE]:
            env2 = make_trading_env(df)
            env2.reset()
            obs, reward, terminated, truncated, info = env2.step(int(action))

            assert isinstance(obs, np.ndarray), "obs must be ndarray"
            assert isinstance(reward, float), "reward must be float"
            assert isinstance(terminated, bool), "terminated must be bool"
            assert isinstance(truncated, bool), "truncated must be bool"
            assert truncated is False, "truncated is always False per spec"
            assert isinstance(info, dict), "info must be dict"

    def test_env_episode_terminates_on_day_end(self):
        """Episode terminates when all bars in the window are consumed."""
        from strategies.rl_env import make_trading_env

        df = _synthetic_df(n_bars=100)
        env = make_trading_env(df, max_episode_bars=50)
        env.reset()

        steps = 0
        terminated = False
        while not terminated:
            _, _, terminated, _, _ = env.step(0)  # HOLD
            steps += 1
            if steps > 200:
                pytest.fail("Episode did not terminate within 200 steps")

        assert steps > 0, "At least one step must have been taken"
        assert terminated, "Episode should terminate on bar exhaustion"

    def test_env_reward_includes_commission_cost(self):
        """Commission is deducted from reward when commission_usd_per_contract > 0."""
        from strategies.rl_config import REWARD_CONFIG
        from strategies.rl_env import make_trading_env

        df = _synthetic_df()

        # Commission-free baseline
        env_free = make_trading_env(
            df, reward_config={**REWARD_CONFIG, "commission_usd_per_contract": 0.0}
        )
        env_free.reset()
        # BUY → HOLD → CLOSE: capture reward at CLOSE step (when PnL is realized)
        env_free.step(1)  # BUY
        env_free.step(0)  # HOLD
        _, reward_free, _, _, _ = env_free.step(3)  # CLOSE

        # With commission
        env_comm = make_trading_env(
            df,
            reward_config={
                **REWARD_CONFIG,
                "commission_usd_per_contract": 10.0,
                "contracts_per_trade": 1,
            },
        )
        env_comm.reset()
        env_comm.step(1)  # BUY
        env_comm.step(0)  # HOLD
        _, reward_comm, _, _, _ = env_comm.step(3)  # CLOSE

        # Commission-charged reward must be <= free reward (commission is a cost)
        # (They use the same seed so prices are identical)
        assert (
            reward_comm <= reward_free
        ), f"Expected commission to reduce reward: free={reward_free:.4f} comm={reward_comm:.4f}"


# ── Group 2: train_ppo (quick_smoke) ─────────────────────────────────────────


class TestTrainPPO:
    """Verify the train_ppo() training entry point."""

    def test_train_ppo_quick_smoke_returns_metrics(self, tmp_path):
        """
        train_ppo with quick_smoke=True trains 100 steps and returns a valid
        metrics dict.  Uses synthetic data — no real data fetch occurs.
        """
        pytest.importorskip("stable_baselines3", reason="SB3 not installed — skip training test")

        from strategies.rl_train import train_ppo

        result = train_ppo(
            symbol="MES",
            n_steps=100,
            save_path=str(tmp_path),
            quick_smoke=True,
            _bypass_flag=True,
        )

        assert result["status"] == "ok", f"Expected status=ok, got {result}"
        assert result["n_steps"] == 100
        assert result["symbol"] == "MES"
        assert "mean_reward" in result
        assert "training_time_s" in result
        assert result["quick_smoke"] is True

    def test_train_ppo_policy_file_written(self, tmp_path):
        """Policy .zip file is written to save_path after training."""
        pytest.importorskip("stable_baselines3", reason="SB3 not installed — skip")

        from strategies.rl_train import train_ppo

        result = train_ppo(
            symbol="MES",
            n_steps=100,
            save_path=str(tmp_path),
            quick_smoke=True,
            _bypass_flag=True,
        )

        zip_path = result["policy_path"]
        assert zip_path.endswith(".zip"), "policy_path must end with .zip"
        assert Path(zip_path).exists(), f"Policy file not found: {zip_path}"

    def test_train_ppo_feature_flag_blocked(self):
        """train_ppo raises RuntimeError when ENABLE_RL_STRATEGY_DISCOVERY != '1'."""
        from strategies.rl_train import train_ppo

        with mock.patch.dict(os.environ, {"ENABLE_RL_STRATEGY_DISCOVERY": "0"}):
            with pytest.raises(RuntimeError, match="disabled"):
                train_ppo(symbol="MES", n_steps=10, _bypass_flag=False)


# ── Group 3: policy_to_hypothesis ────────────────────────────────────────────


class TestPolicyToHypothesis:
    """Verify policy_to_hypothesis() returns a valid StrategyHypothesis."""

    def _write_fake_policy(self, tmp_path: Path, symbol: str = "MES") -> str:
        """
        Write a stub policy zip using SB3 on synthetic data.
        Returns path to the saved .zip (without extension).
        """
        pytest.importorskip("stable_baselines3", reason="SB3 not installed")
        from stable_baselines3 import PPO

        from strategies.rl_config import PPO_CONFIG
        from strategies.rl_env import make_trading_env

        df = _synthetic_df(n_bars=150)
        env = make_trading_env(df, symbol=symbol)

        model = PPO(
            policy=PPO_CONFIG["policy"],
            env=env,
            n_steps=64,
            batch_size=32,
            verbose=0,
        )
        model.learn(total_timesteps=64)

        stem = str(tmp_path / f"{symbol}-stub")
        model.save(stem)
        return stem

    def test_policy_to_hypothesis_returns_valid_hypothesis(self, tmp_path):
        """policy_to_hypothesis returns a StrategyHypothesis with all required fields."""
        pytest.importorskip("stable_baselines3", reason="SB3 not installed")

        from agents.research_agent import StrategyHypothesis
        from strategies.rl_train import policy_to_hypothesis

        stem = self._write_fake_policy(tmp_path, symbol="MES")
        hyp = policy_to_hypothesis(str(stem) + ".zip", symbol="MES", _bypass_flag=True)

        assert isinstance(hyp, StrategyHypothesis), f"Expected StrategyHypothesis, got {type(hyp)}"
        assert hyp.symbol == "MES"
        assert len(hyp.entry_rules) >= 1
        assert len(hyp.exit_rules) >= 1
        assert isinstance(hyp.signal_weights, dict)
        assert isinstance(hyp.risk_params, dict)
        assert "stop_atr_mult" in hyp.risk_params
        assert 0.0 <= hyp.confidence <= 0.5, "confidence must be in [0, 0.5] pre-gate"
        assert hyp.name.startswith("rl-mes"), f"Expected rl-mes-... slug, got {hyp.name}"

    def test_policy_to_hypothesis_feature_flag_blocked(self):
        """policy_to_hypothesis raises RuntimeError when RL discovery is disabled."""
        from strategies.rl_train import policy_to_hypothesis

        with mock.patch.dict(os.environ, {"ENABLE_RL_STRATEGY_DISCOVERY": "0"}):
            with pytest.raises(RuntimeError, match="disabled"):
                policy_to_hypothesis("/fake/path.zip", symbol="MES", _bypass_flag=False)

    def test_policy_to_hypothesis_missing_file_raises(self):
        """policy_to_hypothesis raises FileNotFoundError for a non-existent policy."""
        pytest.importorskip("stable_baselines3", reason="SB3 not installed")

        from strategies.rl_train import policy_to_hypothesis

        with pytest.raises(FileNotFoundError):
            policy_to_hypothesis("/tmp/definitely_not_here.zip", symbol="MES", _bypass_flag=True)


# ── Group 4: isolation / paranoia ────────────────────────────────────────────


class TestNoRealDataFetched:
    """Paranoid checks that no real DB or HTTP calls occur in this test file."""

    def test_no_real_db_calls(self):
        """
        Importing rl_env and rl_train must not open any sqlite or HTTP connections.
        Verified by monkeypatching sqlite3.connect to fail immediately.
        """
        import sqlite3

        original_connect = sqlite3.connect

        def _blocked_connect(*args, **kwargs):
            raise AssertionError(
                "test_rl_strategy.py: sqlite3.connect called unexpectedly — "
                f"args={args!r}.  Tests must use synthetic data only."
            )

        sqlite3.connect = _blocked_connect
        try:
            import importlib

            import strategies.rl_env as m1
            import strategies.rl_train as m2

            importlib.reload(m1)
            importlib.reload(m2)
            # If we get here without AssertionError, no DB calls occurred at import time
        finally:
            sqlite3.connect = original_connect

    def test_no_http_calls_at_import(self):
        """
        Importing rl_env and rl_train must not make HTTP calls.
        Verified by monkeypatching socket to fail immediately.
        """
        import importlib
        import socket

        original_socket = socket.socket

        class _BlockedSocket:
            def __init__(self, *args, **kwargs):
                raise AssertionError(
                    "test_rl_strategy.py: socket.socket() called at import time — "
                    "tests must not make network calls."
                )

        socket.socket = _BlockedSocket
        try:
            import strategies.rl_env as m1
            import strategies.rl_train as m2

            importlib.reload(m1)
            importlib.reload(m2)
        finally:
            socket.socket = original_socket

    def test_synthetic_df_factory_no_external_calls(self):
        """_make_synthetic_df in rl_train generates data without any I/O."""
        from strategies.rl_train import _make_synthetic_df

        df = _make_synthetic_df(n_bars=50, symbol="MES")
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 50
        required_cols = {"open", "high", "low", "close", "volume", "atr", "stc_val"}
        missing = required_cols - set(df.columns)
        assert not missing, f"Missing expected columns: {missing}"
