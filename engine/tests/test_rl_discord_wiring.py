"""Tests for US-2504 — discord_context wired into rl_trainer build_env calls."""
import inspect

import numpy as np
import pandas as pd
import pytest


def _make_df(n: int = 50) -> pd.DataFrame:
    idx = pd.date_range("2025-01-06", periods=n, freq="1h", tz="UTC")
    rng = np.random.default_rng(42)
    return pd.DataFrame(
        {
            "open": rng.uniform(70, 75, n),
            "high": rng.uniform(74, 76, n),
            "low": rng.uniform(69, 72, n),
            "close": rng.uniform(70, 75, n),
            "volume": rng.integers(1000, 5000, n),
        },
        index=idx,
    )


def test_discord_signal_context_importable():
    """DiscordSignalContext can be imported without error."""
    from discord.signal_context import DiscordSignalContext
    assert DiscordSignalContext is not None


def test_train_and_evaluate_window_accepts_discord_context():
    """_train_and_evaluate_window() signature includes discord_context parameter."""
    from strategies.rl_trainer import RLTrainer
    sig = inspect.signature(RLTrainer._train_and_evaluate_window)
    assert "discord_context" in sig.parameters, (
        "_train_and_evaluate_window() is missing discord_context — "
        "train_walkforward() will TypeError at runtime without it."
    )


def test_train_and_evaluate_window_discord_context_defaults_none():
    """discord_context parameter defaults to None."""
    from strategies.rl_trainer import RLTrainer
    sig = inspect.signature(RLTrainer._train_and_evaluate_window)
    assert sig.parameters["discord_context"].default is None


def test_build_env_accepts_discord_context_none():
    """build_env() accepts discord_context=None without error."""
    from strategies.rl_environment import build_env
    df = _make_df()
    env = build_env(symbol="MCL", df=df, max_episode_bars=20, discord_context=None)
    assert env is not None
    env.close()


def test_observation_space_is_23():
    """Observation space is (23,) when discord_context=None (neutral defaults fill slots 18-22)."""
    from strategies.rl_environment import build_env
    df = _make_df()
    env = build_env(symbol="MCL", df=df, max_episode_bars=20, discord_context=None)
    assert env.observation_space.shape == (23,), (
        f"Expected (23,) but got {env.observation_space.shape}"
    )
    env.close()


def test_discord_intelligence_endpoint_importable():
    """get_discord_intelligence endpoint function is importable."""
    from routers.discord_router import get_discord_intelligence
    assert callable(get_discord_intelligence)
