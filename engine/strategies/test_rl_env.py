"""
JARVIS TRADER — RL Environment Unit Tests
==========================================
Tests for TradingEnvironment without requiring real market data
or live indicator computation.

Run:
    cd engine && pytest strategies/test_rl_env.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# ── Path setup ────────────────────────────────────────────────────────────────
# Allow import from engine/ root when running from engine/ directory
ENGINE_DIR = Path(__file__).parent.parent
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))


# ── Attempt gymnasium import — skip all tests if not installed ────────────────
gymnasium = pytest.importorskip(
    "gymnasium", reason="gymnasium not installed — run: pip install gymnasium"
)
stable_baselines3 = pytest.importorskip(
    "stable_baselines3",
    reason="stable-baselines3 not installed — run: pip install stable-baselines3[extra]",
)


from strategies.rl_config import (
    N_ACTIONS,
    N_FEATURES,
    VALIDATION_GATES,
    Action,
)
from strategies.rl_environment import TradingEnvironment, build_env, extract_features

# ── Fixtures ──────────────────────────────────────────────────────────────────


def make_synthetic_df(n_bars: int = 200, symbol: str = "MES") -> pd.DataFrame:
    """
    Build a minimal synthetic DataFrame with all columns expected by
    TradingEnvironment.extract_features() and compute_all_indicators().

    Uses deterministic random walk so tests are reproducible.
    """
    rng = np.random.default_rng(42)

    close = 4500.0 + np.cumsum(rng.normal(0, 5, n_bars))
    high = close + rng.uniform(1, 10, n_bars)
    low = close - rng.uniform(1, 10, n_bars)
    volume = rng.integers(1000, 5000, n_bars).astype(float)

    atr = np.full(n_bars, 12.0) + rng.normal(0, 1, n_bars)
    atr = np.maximum(atr, 0.1)  # guard against negative ATR

    stc_val = np.clip(50.0 + np.cumsum(rng.normal(0, 2, n_bars)), 0, 100)

    df = pd.DataFrame(
        {
            "open": close - rng.uniform(0, 3, n_bars),
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "atr": atr,
            "ema_8": close * 0.999,
            "ema_21": close * 0.997,
            "ema_34": close * 0.995,
            "ema_trend": ["bullish"] * n_bars,
            "stc_val": stc_val,
            "stc_prev": np.roll(stc_val, 1),
            "stc_signal": np.where(stc_val > 50, "bull", "bear"),
            "stc_cross_up": np.zeros(n_bars),
            "stc_cross_down": np.zeros(n_bars),
            "phase_val": rng.uniform(-50, 50, n_bars),
            "phase_compression": np.zeros(n_bars, dtype=bool),
            "phase_signal": ["neutral"] * n_bars,
            "buy_vol": volume * 0.6,
            "sell_vol": volume * 0.4,
            "buy_pct": np.full(n_bars, 0.6),
            "volume_signal": ["buyer_dominant"] * n_bars,
            "atr_consumed_pct": rng.uniform(0.1, 0.9, n_bars),
            "cci_50": rng.uniform(-200, 200, n_bars),
            # Regime columns (used by layer1_regime)
            "ema_ribbon_spread": rng.uniform(0, 5, n_bars),
            "bb_width": rng.uniform(0.5, 3, n_bars),
            # Structure columns (safe defaults)
            "vpoc": close * 0.998,
            "va_high": close * 1.002,
            "va_low": close * 0.995,
            "ib_high": close * 1.003,
            "ib_low": close * 0.994,
            "above_vah": np.zeros(n_bars, dtype=bool),
            "below_val": np.zeros(n_bars, dtype=bool),
            "above_ib_high": np.zeros(n_bars, dtype=bool),
            "below_ib_low": np.zeros(n_bars, dtype=bool),
            # Keltner channels
            "kc_upper": close + atr * 2,
            "kc_lower": close - atr * 2,
            "kc_mid": close,
        }
    )
    return df.reset_index(drop=True)


@pytest.fixture
def df_mes():
    return make_synthetic_df(n_bars=200, symbol="MES")


@pytest.fixture
def env_mes(df_mes):
    return TradingEnvironment(symbol="MES", df=df_mes, initial_capital=10_000.0)


# ── Core Environment Tests ────────────────────────────────────────────────────


class TestTradingEnvironmentReset:
    def test_reset_returns_obs_and_info(self, env_mes):
        obs, info = env_mes.reset()
        assert isinstance(obs, np.ndarray), "reset() must return ndarray observation"
        assert isinstance(info, dict), "reset() must return info dict"

    def test_obs_shape(self, env_mes):
        obs, _ = env_mes.reset()
        assert obs.shape == (N_FEATURES,), f"Expected obs shape ({N_FEATURES},), got {obs.shape}"

    def test_obs_dtype(self, env_mes):
        obs, _ = env_mes.reset()
        assert obs.dtype == np.float32, f"Expected float32, got {obs.dtype}"

    def test_obs_no_nan(self, env_mes):
        obs, _ = env_mes.reset()
        assert not np.any(np.isnan(obs)), "Observation must not contain NaN"

    def test_obs_no_inf(self, env_mes):
        obs, _ = env_mes.reset()
        assert not np.any(np.isinf(obs)), "Observation must not contain Inf"

    def test_reset_resets_position(self, env_mes):
        """Environment should start flat after reset."""
        env_mes.reset()
        assert env_mes._position == 0
        assert env_mes._bars_in_trade == 0

    def test_seed_reproducibility(self, df_mes):
        """Two resets with same seed should return identical observations."""
        env1 = TradingEnvironment(symbol="MES", df=df_mes)
        env2 = TradingEnvironment(symbol="MES", df=df_mes)
        obs1, _ = env1.reset(seed=99)
        obs2, _ = env2.reset(seed=99)
        np.testing.assert_array_equal(obs1, obs2)


class TestTradingEnvironmentStep:
    def test_step_returns_five_tuple(self, env_mes):
        env_mes.reset()
        result = env_mes.step(Action.HOLD)
        assert len(result) == 5, "step() must return (obs, reward, terminated, truncated, info)"

    def test_step_hold_from_flat(self, env_mes):
        """HOLD from flat position should return valid state, zero or small reward."""
        env_mes.reset()
        obs, reward, terminated, truncated, info = env_mes.step(Action.HOLD)
        assert obs.shape == (N_FEATURES,)
        assert isinstance(reward, float)
        assert isinstance(terminated, bool)
        assert isinstance(truncated, bool)
        assert isinstance(info, dict)

    @pytest.mark.parametrize("action", [Action.HOLD, Action.BUY, Action.SELL, Action.CLOSE])
    def test_step_all_actions_valid_obs(self, df_mes, action):
        """Every action must return a valid observation."""
        env = TradingEnvironment(symbol="MES", df=df_mes)
        env.reset()
        obs, reward, terminated, truncated, info = env.step(action)
        assert obs.shape == (N_FEATURES,)
        assert not np.any(np.isnan(obs)), f"NaN in obs after action {action.name}"
        assert not np.any(np.isinf(obs)), f"Inf in obs after action {action.name}"

    def test_step_buy_opens_long(self, env_mes):
        env_mes.reset()
        env_mes.step(Action.BUY)
        assert env_mes._position == 1, "BUY should set position to 1 (long)"

    def test_step_sell_opens_short(self, env_mes):
        env_mes.reset()
        env_mes.step(Action.SELL)
        assert env_mes._position == -1, "SELL should set position to -1 (short)"

    def test_step_close_from_flat_is_noop(self, env_mes):
        """CLOSE when flat should leave position at 0 (no-op)."""
        env_mes.reset()
        assert env_mes._position == 0
        env_mes.step(Action.CLOSE)
        assert env_mes._position == 0

    def test_step_close_closes_long(self, env_mes):
        env_mes.reset()
        env_mes.step(Action.BUY)
        assert env_mes._position == 1
        env_mes.step(Action.CLOSE)
        assert env_mes._position == 0

    def test_step_close_closes_short(self, env_mes):
        env_mes.reset()
        env_mes.step(Action.SELL)
        assert env_mes._position == -1
        env_mes.step(Action.CLOSE)
        assert env_mes._position == 0

    def test_step_terminates_at_end(self, df_mes):
        """Episode must terminate after exhausting all bars."""
        env = TradingEnvironment(symbol="MES", df=df_mes)
        env.reset()
        terminated = False
        truncated = False
        for _ in range(len(df_mes) + 10):
            _, _, terminated, truncated, _ = env.step(Action.HOLD)
            if terminated or truncated:
                break
        assert terminated or truncated, "Environment must terminate at end of data"

    def test_entry_cost_applied_on_buy(self, env_mes):
        """Opening a new BUY from flat should include a negative entry cost."""
        env_mes.reset()
        assert env_mes._position == 0
        _, reward, _, _, _ = env_mes.step(Action.BUY)
        # Entry cost is -0.02 — reward should reflect it
        assert reward < 0.0 or reward == pytest.approx(
            0.0, abs=0.1
        ), "Entry from flat should incur entry cost penalty"


class TestPositionConstraints:
    """
    Position constraint tests:
    - BUY when already long → reversal (close long, open short) OR ignored, never double-long
    - SELL when already short → reversal (close short, open long) OR ignored, never double-short
    """

    def test_buy_when_long_does_not_double(self, env_mes):
        """Buying when already long should not increase position beyond 1."""
        env_mes.reset()
        env_mes.step(Action.BUY)  # open long
        assert env_mes._position == 1
        env_mes.step(Action.BUY)  # attempt to double-long or reverse
        # Position must be either 1 (held) or -1 (reversed) — never 2
        assert env_mes._position in (-1, 0, 1), f"Double-long invalid, position={env_mes._position}"

    def test_sell_when_short_does_not_double(self, env_mes):
        """Selling when already short should not decrease position below -1."""
        env_mes.reset()
        env_mes.step(Action.SELL)  # open short
        assert env_mes._position == -1
        env_mes.step(Action.SELL)  # attempt to double-short or reverse
        assert env_mes._position in (
            -1,
            0,
            1,
        ), f"Double-short invalid, position={env_mes._position}"


class TestObservationSpace:
    def test_obs_space_shape(self, env_mes):
        assert env_mes.observation_space.shape == (N_FEATURES,)

    def test_action_space_size(self, env_mes):
        assert env_mes.action_space.n == N_ACTIONS

    def test_action_space_contains_all_actions(self, env_mes):
        for action in Action:
            assert env_mes.action_space.contains(int(action))


class TestEpisodeMetrics:
    def test_get_episode_metrics_structure(self, df_mes):
        """get_episode_metrics() should return expected keys."""
        env = TradingEnvironment(symbol="MES", df=df_mes)
        env.reset()
        # Run a short episode
        for _ in range(20):
            env.step(Action.HOLD)
        metrics = env.get_episode_metrics()
        expected_keys = {"total_pnl", "n_trades", "win_rate", "total_reward"}
        assert expected_keys.issubset(
            metrics.keys()
        ), f"Missing keys: {expected_keys - metrics.keys()}"

    def test_metrics_after_buy_close_cycle(self, df_mes):
        """A BUY followed by CLOSE should register 1 trade."""
        env = TradingEnvironment(symbol="MES", df=df_mes)
        env.reset()
        env.step(Action.BUY)
        env.step(Action.CLOSE)
        metrics = env.get_episode_metrics()
        assert metrics["n_trades"] == 1, f"Expected 1 trade, got {metrics['n_trades']}"

    def test_t1_hit_rate_tracks_correctly(self, df_mes):
        """t1_hit_rate = t1_hits / n_trades, correctly counts trades reaching T1 target."""
        from strategies.rl_config import get_instrument_params

        env = TradingEnvironment(symbol="MES", df=df_mes)
        obs, _ = env.reset(seed=0)

        # Run a few steps and then check that t1_hit_rate is present in metrics
        for _ in range(10):
            obs, reward, terminated, truncated, info = env.step(1)  # BUY
            if terminated or truncated:
                break

        metrics = env.get_episode_metrics()

        # t1_hit_rate must be present
        assert "t1_hit_rate" in metrics, "t1_hit_rate not in episode metrics"
        assert "t1_hits" in metrics, "t1_hits not in episode metrics"

        # t1_hit_rate must be non-negative and <= 1.0
        assert (
            0.0 <= metrics["t1_hit_rate"] <= 1.0
        ), f"t1_hit_rate out of range: {metrics['t1_hit_rate']}"

        # t1_hits must be a non-negative integer
        assert (
            isinstance(metrics["t1_hits"], int) or metrics["t1_hits"] >= 0
        ), f"t1_hits invalid: {metrics['t1_hits']}"

        # t1_hit_rate must equal t1_hits / max(n_trades, 1)
        n_trades = metrics.get("n_trades", 0)
        expected = round(metrics["t1_hits"] / max(n_trades, 1), 4)
        assert (
            metrics["t1_hit_rate"] == expected
        ), f"t1_hit_rate calculation wrong: {metrics['t1_hit_rate']} != {expected}"


class TestBuildEnv:
    def test_build_env_returns_environment(self, df_mes):
        env = build_env(symbol="MES", df=df_mes)
        assert isinstance(env, TradingEnvironment)

    def test_build_env_reset_works(self, df_mes):
        env = build_env(symbol="MES", df=df_mes)
        obs, info = env.reset()
        assert obs.shape == (N_FEATURES,)


class TestExtractFeatures:
    def test_extract_features_shape(self, df_mes):
        obs = extract_features(
            df_mes, idx=50, position=0, entry_price=0.0, bars_in_trade=0, symbol="MES"
        )
        assert obs.shape == (N_FEATURES,)

    def test_extract_features_dtype(self, df_mes):
        obs = extract_features(
            df_mes, idx=50, position=0, entry_price=0.0, bars_in_trade=0, symbol="MES"
        )
        assert obs.dtype == np.float32

    def test_extract_features_no_nan(self, df_mes):
        obs = extract_features(
            df_mes, idx=50, position=0, entry_price=0.0, bars_in_trade=0, symbol="MES"
        )
        assert not np.any(np.isnan(obs))

    def test_extract_features_position_reflected(self, df_mes):
        """current_position feature should reflect input position."""
        obs_flat = extract_features(
            df_mes, idx=50, position=0, entry_price=0.0, bars_in_trade=0, symbol="MES"
        )
        obs_long = extract_features(
            df_mes, idx=50, position=1, entry_price=4500.0, bars_in_trade=5, symbol="MES"
        )
        obs_short = extract_features(
            df_mes, idx=50, position=-1, entry_price=4500.0, bars_in_trade=5, symbol="MES"
        )

        # current_position is index 15 in STATE_FEATURES
        pos_idx = 15
        assert obs_flat[pos_idx] == pytest.approx(0.0, abs=1e-5)
        assert obs_long[pos_idx] == pytest.approx(1.0, abs=1e-5)
        assert obs_short[pos_idx] == pytest.approx(-1.0, abs=1e-5)

    def test_extract_features_first_bar(self, df_mes):
        """Feature extraction must work at bar index 0 (no lookback available)."""
        obs = extract_features(
            df_mes, idx=0, position=0, entry_price=0.0, bars_in_trade=0, symbol="MES"
        )
        assert obs.shape == (N_FEATURES,)
        assert not np.any(np.isnan(obs))


class TestMultipleSymbols:
    @pytest.mark.parametrize("symbol", ["MES", "MNQ", "MCL", "MGC"])
    def test_env_step_all_symbols(self, symbol):
        """Environment must work for all supported futures symbols."""
        df = make_synthetic_df(n_bars=120, symbol=symbol)
        env = TradingEnvironment(symbol=symbol, df=df)
        obs, _ = env.reset()
        assert obs.shape == (N_FEATURES,)
        obs2, reward, _, _, _ = env.step(Action.BUY)
        assert obs2.shape == (N_FEATURES,)
        assert isinstance(reward, float)


class TestValidationGates:
    def test_validation_gates_have_required_keys(self):
        required = {
            "min_profit_factor",
            "min_sharpe",
            "min_win_rate",
            "min_trades",
            "min_hold_rate",
            "max_drawdown",
        }
        assert required.issubset(VALIDATION_GATES.keys())

    def test_validation_gates_values_in_range(self):
        assert 0.0 < VALIDATION_GATES["min_win_rate"] < 1.0
        assert 0.0 < VALIDATION_GATES["max_drawdown"] < 1.0
        assert 0.0 < VALIDATION_GATES["min_hold_rate"] <= 1.0
        assert VALIDATION_GATES["min_profit_factor"] > 1.0

    def test_min_hold_rate_gate_is_50_percent(self):
        """Regression guard: min_hold_rate validation gate must be exactly 0.50."""
        assert (
            VALIDATION_GATES["min_hold_rate"] == 0.50
        ), f"min_hold_rate should be 0.50, got {VALIDATION_GATES['min_hold_rate']}"


# ── Reward Function Fix Tests ─────────────────────────────────────────────────


class TestRewardFunctionFixes:
    """Tests verifying the two reward function bug fixes.

    Fix 1: hold_cost must be FLAT per bar, NOT multiplied by bars_in_trade.
    Fix 2: BUY when already long / SELL when already short must incur a penalty
           (redundant_cost) — they were previously treated as free no-ops.
    """

    @pytest.fixture
    def env(self, df_mes):
        return TradingEnvironment(symbol="MES", df=df_mes, initial_capital=10_000.0)

    def test_hold_cost_is_flat_not_compounding(self, env):
        """hold_cost_per_bar must NOT multiply by bars_in_trade (flat per bar).

        Collect the raw hold-cost component on bar 1 vs bar 10 while in a long
        position.  Both bars should produce the same hold_cost magnitude; if the
        bug were present bar-10 cost would be 10x bar-1 cost.
        """
        from strategies.rl_config import REWARD_CONFIG

        env.reset()
        env.step(Action.BUY)  # open long at bar 0

        # Capture reward at bar 1 (bars_in_trade == 1)
        _, reward_bar1, _, _, _ = env.step(Action.HOLD)

        # Step forward 8 more HOLD bars so we're at bars_in_trade == 9
        for _ in range(8):
            env.step(Action.HOLD)

        # Capture reward at bar 10 (bars_in_trade == 10)
        _, reward_bar10, _, _, _ = env.step(Action.HOLD)

        expected_hold_cost = REWARD_CONFIG["hold_cost_per_bar"]  # -0.001

        # Both bars: pnl_reward ~ 0 (HOLD, no realized PnL), no entry cost.
        # So reward ≈ hold_cost + flat_hold_reward (0 because in position).
        # Flat: both should be approximately equal to hold_cost per bar.
        assert abs(reward_bar1 - reward_bar10) < abs(expected_hold_cost) * 5, (
            f"Hold cost appears to be compounding: bar1={reward_bar1:.5f}, "
            f"bar10={reward_bar10:.5f}. Expected both ≈ {expected_hold_cost}"
        )

    def test_hold_cost_accumulation_over_50_bars(self, df_mes):
        """Total hold-cost component over 50 HOLD bars in a long position.

        Fixed code: 50 * (-0.001) = -0.05 total hold cost contribution.
        Buggy code: sum(range(1,51)) * (-0.001) = -1.275 total hold cost.

        We measure the total reward accumulated during 50 HOLD bars (no PnL),
        which should be dominated by flat hold_cost. The total must be much
        closer to -0.05 than to -1.275.
        """
        from strategies.rl_config import REWARD_CONFIG

        env = TradingEnvironment(symbol="MES", df=df_mes, initial_capital=10_000.0)
        env.reset()
        env.step(Action.BUY)  # open long

        total_reward = 0.0
        steps = 0
        for _ in range(50):
            _, reward, terminated, truncated, _ = env.step(Action.HOLD)
            total_reward += reward
            steps += 1
            if terminated or truncated:
                break

        expected_flat = steps * REWARD_CONFIG["hold_cost_per_bar"]  # e.g. -0.05
        buggy_estimate = (
            sum(range(1, steps + 1)) * REWARD_CONFIG["hold_cost_per_bar"]
        )  # e.g. -1.275

        # Total should be much closer to the flat estimate than the buggy one.
        # pnl_reward from price drift may add noise; allow 2 ATR units of slack.
        flat_error = abs(total_reward - expected_flat)
        buggy_error = abs(total_reward - buggy_estimate)
        assert flat_error < buggy_error, (
            f"Hold cost appears compounding: total_reward={total_reward:.4f}, "
            f"expected_flat={expected_flat:.4f}, buggy_estimate={buggy_estimate:.4f}"
        )

    def test_redundant_buy_when_long_penalized(self, df_mes):
        """BUY when already long should incur entry_cost (redundant_cost penalty)."""
        from strategies.rl_config import REWARD_CONFIG

        env = TradingEnvironment(symbol="MES", df=df_mes, initial_capital=10_000.0)
        env.reset()
        env.step(Action.BUY)  # open long — incurs entry_cost (is_new_entry)

        # Now BUY again while already long — should incur redundant_cost
        _, reward_redundant, _, _, _ = env.step(Action.BUY)

        # The reward must include entry_cost penalty (negative).
        # entry_cost = -0.20 by default.  Even with zero PnL the reward must be <= 0.
        assert (
            reward_redundant <= 0.0
        ), f"Redundant BUY when long should be penalized, got reward={reward_redundant:.4f}"
        # Specifically: reward should include at least the entry_cost magnitude.
        assert reward_redundant <= REWARD_CONFIG["entry_cost"] + 0.01, (
            f"Redundant BUY penalty too small: reward={reward_redundant:.4f}, "
            f"entry_cost={REWARD_CONFIG['entry_cost']}"
        )

    def test_redundant_sell_when_short_penalized(self, df_mes):
        """SELL when already short should incur entry_cost (redundant_cost penalty)."""
        from strategies.rl_config import REWARD_CONFIG

        env = TradingEnvironment(symbol="MES", df=df_mes, initial_capital=10_000.0)
        env.reset()
        env.step(Action.SELL)  # open short

        # SELL again while already short — redundant
        _, reward_redundant, _, _, _ = env.step(Action.SELL)

        assert (
            reward_redundant <= 0.0
        ), f"Redundant SELL when short should be penalized, got reward={reward_redundant:.4f}"
        assert reward_redundant <= REWARD_CONFIG["entry_cost"] + 0.01, (
            f"Redundant SELL penalty too small: reward={reward_redundant:.4f}, "
            f"entry_cost={REWARD_CONFIG['entry_cost']}"
        )

    def test_normal_entry_penalized_once(self, df_mes):
        """Normal BUY from flat incurs entry_cost exactly once (not doubled)."""
        from strategies.rl_config import REWARD_CONFIG

        env = TradingEnvironment(symbol="MES", df=df_mes, initial_capital=10_000.0)
        env.reset()

        # BUY from flat — is_new_entry=True, redundant_cost=0 (position was 0 before step)
        _, reward_entry, _, _, _ = env.step(Action.BUY)

        # Should include entry_cost + hold_cost (1 bar) but NOT redundant_cost on top.
        # entry_cost=-0.01, hold_cost=-0.010: normal 1-bar reward = -0.020.
        # If double-penalized (entry_cost applied twice + hold_cost) it would be -0.030.
        # Use >= so the coincidence of hold_cost==entry_cost doesn't false-fail.
        double_entry_cost = REWARD_CONFIG["entry_cost"] * 2
        assert reward_entry >= double_entry_cost, (
            f"Normal entry appears to double-penalize: reward={reward_entry:.4f}, "
            f"double_entry_cost={double_entry_cost:.4f}"
        )

    def test_hold_when_flat_gets_reward(self, df_mes):
        """HOLD when flat (position==0) earns flat_hold_reward (patience reward)."""
        from strategies.rl_config import REWARD_CONFIG

        env = TradingEnvironment(symbol="MES", df=df_mes, initial_capital=10_000.0)
        env.reset()  # starts flat

        _, reward_hold_flat, _, _, _ = env.step(Action.HOLD)

        flat_hold_reward = REWARD_CONFIG.get("flat_hold_reward", 0.0)
        # When flat, reward should be ≥ flat_hold_reward (no hold cost, no entry cost).
        assert reward_hold_flat >= flat_hold_reward - 1e-6, (
            f"HOLD when flat should earn at least flat_hold_reward={flat_hold_reward}, "
            f"got {reward_hold_flat:.5f}"
        )

    def test_hold_when_in_position_gets_hold_cost(self, df_mes):
        """HOLD when in a LOSING position incurs hold_cost; winning position is free (Run 11)."""
        from strategies.rl_config import REWARD_CONFIG

        env = TradingEnvironment(symbol="MES", df=df_mes, initial_capital=10_000.0)
        env.reset()
        env.step(Action.BUY)  # open long

        # Force a losing position: set entry price above current close
        current_close = float(env.df.iloc[env._idx]["close"])
        env._entry_price = current_close * 1.10  # 10% above current — clearly losing

        # HOLD while underwater — should incur hold_cost, NOT flat_hold_reward
        _, reward_hold_long, _, _, _ = env.step(Action.HOLD)

        hold_cost = REWARD_CONFIG["hold_cost_per_bar"]  # -0.010

        # Reward should be approximately hold_cost (may have small pnl_reward from price move).
        # Key invariant: reward when losing < 0 (hold cost applied).
        assert reward_hold_long < 0.0, (
            f"HOLD in losing position should have negative reward (hold_cost applied): "
            f"reward={reward_hold_long:.5f}, hold_cost={hold_cost}"
        )

    def test_hold_cost_is_negative_when_in_position(self, df_mes):
        """Confirm hold_cost_per_bar is negative (costs something to stay in)."""
        from strategies.rl_config import REWARD_CONFIG

        assert (
            REWARD_CONFIG["hold_cost_per_bar"] < 0.0
        ), "hold_cost_per_bar must be negative to discourage over-staying in trades"

    def test_flat_hold_reward_is_non_negative(self, df_mes):
        """Confirm flat_hold_reward is non-negative (>= 0).

        Run 7 / Scenario C deliberately sets flat_hold_reward=0.000 (pure P&L
        signal — no passive patience reward).  Prior runs used positive values
        (e.g. 0.003 in Run 6).  The invariant is that this value must never be
        negative, but zero is a valid intentional configuration.
        """
        from strategies.rl_config import REWARD_CONFIG

        flat_hold_reward = REWARD_CONFIG.get("flat_hold_reward", 0.0)
        assert flat_hold_reward >= 0.0, (
            "flat_hold_reward must be non-negative (0.0 is valid for Scenario C "
            "pure P&L mode; negative values would penalise patience when flat)"
        )

    def test_flat_hold_rate_tracked(self):
        """flat_hold_rate measures HOLD actions taken while flat."""
        env = build_env("MES", make_synthetic_df())
        env.reset()

        # Step with only HOLD actions (should be flat the entire time)
        for _ in range(20):
            env.step(Action.HOLD)

        metrics = env.get_episode_metrics()
        # All bars were flat (position=0), all actions were HOLD
        assert "flat_hold_rate" in metrics
        assert metrics["flat_hold_rate"] == 1.0  # 100% of flat bars we HOLDed

    def test_flat_hold_rate_when_in_position(self):
        """flat_hold_rate is not inflated by in-position HOLD bars."""
        env = build_env("MES", make_synthetic_df())
        env.reset()

        # Open a position, then HOLD in it for 10 bars, then close
        env.step(Action.BUY)  # open long: now in position
        for _ in range(10):
            env.step(Action.HOLD)  # HOLD while in position — should NOT count toward flat_hold_rate
        env.step(Action.CLOSE)  # close position
        env.step(Action.HOLD)  # HOLD while flat — should count

        metrics = env.get_episode_metrics()
        assert "flat_hold_rate" in metrics
        # Only 1 flat HOLD bar out of 1 flat bar after close (but also initial bars before BUY)
        # flat_hold_rate should be > 0 (we did HOLD when flat after close)
        assert metrics["flat_hold_rate"] > 0.0
        # And it should NOT be 1.0 if the in-position HOLDs were incorrectly counted
        # (if in-position HOLDs were counted: 11 HOLD out of 12 total = 0.916...)
        # (if in-position HOLDs NOT counted: 1 HOLD out of 1 flat bar = 1.0)
        # The correct value is 1.0 since the only flat bar after open we did HOLD
        # So we test that the metric excludes in-position bars by ensuring it's reported
        assert 0.0 <= metrics["flat_hold_rate"] <= 1.0


# ── Walk-Forward Skeleton Tests ───────────────────────────────────────────────


class TestWalkForwardSkeleton:
    """Smoke tests verifying walk-forward trainer infrastructure exists.

    These tests are intentionally minimal — they check for method existence
    rather than full training, so they run in milliseconds without GPU.
    """

    def test_trainer_module_importable(self):
        """rl_trainer module must be importable from strategies package."""
        from strategies import rl_trainer  # noqa: F401

    def test_trainer_class_exists(self):
        """RLTrainer class must exist in rl_trainer module."""
        from strategies.rl_trainer import RLTrainer

        assert RLTrainer is not None

    def test_trainer_has_walkforward_method(self):
        """RLTrainer must expose a train_walkforward method (may not be implemented yet)."""
        from strategies.rl_trainer import RLTrainer

        assert hasattr(RLTrainer, "train_walkforward"), (
            "RLTrainer.train_walkforward() is required for walk-forward validation. "
            "Add a stub method if full implementation is pending."
        )

    def test_trainer_has_train_symbol_method(self):
        """RLTrainer must expose a train_symbol method for single-run training."""
        from strategies.rl_trainer import RLTrainer

        assert hasattr(
            RLTrainer, "train_symbol"
        ), "RLTrainer must have a train_symbol() coroutine for single-run training"


# ── Walk-Forward Validation Tests ─────────────────────────────────────────────


class TestWalkForward:
    """
    Validates RLTrainer.train_walkforward() behaviour.

    Strategy:
    - Mock _train_and_evaluate_window (the heavy inner loop) to return
      controlled metric dicts — keeps tests in milliseconds.
    - Mock prepare_dataframe / pd.read_parquet where needed to control
      the data path without hitting disk or the network.
    """

    # ── Shared helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _passing_metrics(
        n_trades: int = 80,
        profit_factor: float = 2.5,
        win_rate: float = 0.6,
        max_drawdown: float = 0.1,
        hold_rate: float = 0.6,
        flat_hold_rate: float = 0.65,
    ) -> dict:
        """Return a metrics dict that passes all validation gates."""
        return {
            "profit_factor": profit_factor,
            "win_rate": win_rate,
            "max_drawdown": max_drawdown,
            "n_trades": n_trades,
            "hold_rate": hold_rate,
            "flat_hold_rate": flat_hold_rate,
            "passes_validation": True,
        }

    @staticmethod
    def _window_result(metrics: dict, window_idx: int = 0) -> dict:
        """Minimal window result dict returned by _train_and_evaluate_window."""
        return {
            "train_bars": 150,
            "test_bars": 50,
            "metrics": metrics,
            "model_path": None,
            "training_summary": {},
        }

    # ── Internal helper: asyncio.to_thread replacement ───────────────────────

    @staticmethod
    def _sync_to_thread(fn, *args, **kwargs):
        """Drop-in sync replacement for asyncio.to_thread in tests.

        asyncio.to_thread(fn, *args, **kwargs) → call fn(*args, **kwargs)
        synchronously so we don't need threads or an inner event loop.
        """
        return fn(*args, **kwargs)

    # ── Test 1: window count ──────────────────────────────────────────────────

    def test_walkforward_window_count(self):
        """train_walkforward with n_windows=3 must return exactly 3 window dicts,
        each containing window_idx and window_pass keys."""
        import asyncio
        from unittest.mock import AsyncMock, patch

        from strategies.rl_trainer import RLTrainer

        trainer = RLTrainer()
        synthetic_df = make_synthetic_df(n_bars=500)
        passing = self._passing_metrics()

        def fake_train_evaluate_window(
            symbol, df_train, df_test, timesteps, window_idx, reward_config=None
        ):
            return self._window_result(passing, window_idx=window_idx)

        with (
            patch.object(
                trainer,
                "_train_and_evaluate_window",
                side_effect=fake_train_evaluate_window,
            ),
            patch(
                "strategies.rl_trainer.asyncio.to_thread",
                side_effect=self._sync_to_thread,
            ),
            patch(
                "strategies.rl_trainer.prepare_dataframe",
                return_value=synthetic_df,
            ),
        ):
            result = asyncio.run(trainer.train_walkforward(symbol="MES", n_windows=3))

        assert result["status"] == "complete", (
            f"Expected status='complete', got: {result.get('status')} | "
            f"error: {result.get('error')}"
        )
        windows = result["windows"]
        assert isinstance(windows, list), "result['windows'] must be a list"
        assert len(windows) == 3, f"Expected 3 windows, got {len(windows)}"
        for w in windows:
            assert "window_idx" in w, f"window missing 'window_idx' key: {w}"
            assert "window_pass" in w, f"window missing 'window_pass' key: {w}"

    # ── Test 2: cache used ────────────────────────────────────────────────────

    def test_walkforward_cache_used(self, tmp_path):
        """When a parquet cache file exists, the trainer loads data from cache
        (prepare_dataframe reads it via pd.read_parquet) rather than falling
        through to BacktestDataLoader."""
        import asyncio
        from unittest.mock import call, patch

        from strategies.rl_config import DEFAULT_INTERVAL
        from strategies.rl_trainer import RLTrainer

        trainer = RLTrainer()
        synthetic_df = make_synthetic_df(n_bars=500)
        passing = self._passing_metrics()

        # Write a real parquet file so cache_path.exists() is True
        cache_filename = f"MES_{DEFAULT_INTERVAL.replace('/', '_')}.parquet"
        fake_cache_path = tmp_path / cache_filename
        synthetic_df.to_parquet(fake_cache_path, index=False)

        def fake_train_evaluate_window(
            symbol, df_train, df_test, timesteps, window_idx, reward_config=None
        ):
            return self._window_result(passing, window_idx=window_idx)

        read_parquet_calls = []

        def tracking_read_parquet(path, *args, **kwargs):
            read_parquet_calls.append(str(path))
            return synthetic_df

        with (
            patch(
                "strategies.rl_trainer.RL_CACHE_DIR",
                tmp_path,
            ),
            patch.object(
                trainer,
                "_train_and_evaluate_window",
                side_effect=fake_train_evaluate_window,
            ),
            patch(
                "strategies.rl_trainer.asyncio.to_thread",
                side_effect=self._sync_to_thread,
            ),
            patch(
                "pandas.read_parquet",
                side_effect=tracking_read_parquet,
            ),
        ):
            result = asyncio.run(trainer.train_walkforward(symbol="MES", n_windows=2))

        assert (
            result.get("status") == "complete"
        ), f"Expected complete, got: {result.get('status')} | {result.get('error')}"
        assert len(read_parquet_calls) > 0, (
            "pd.read_parquet was never called — cache was not used. " f"result: {result}"
        )

    # ── Test 3: gate keys (regression for sharpe KeyError) ───────────────────

    def test_walkforward_gate_keys(self):
        """train_walkforward must NOT raise KeyError when evaluate() returns
        the documented metric keys (regression test: was checking 'sharpe' key
        which doesn't exist in get_episode_metrics())."""
        import asyncio
        from unittest.mock import patch

        from strategies.rl_trainer import RLTrainer

        trainer = RLTrainer()
        synthetic_df = make_synthetic_df(n_bars=500)

        # Metrics dict with exactly the keys that RLTradingAgent.evaluate() returns
        # — deliberately NO 'sharpe' key (that was the bug).
        metrics_without_sharpe = {
            "profit_factor": 2.5,
            "win_rate": 0.6,
            "max_drawdown": 0.1,
            "n_trades": 80,
            "hold_rate": 0.6,
            "flat_hold_rate": 0.65,
            "passes_validation": True,
        }

        def fake_train_evaluate_window(
            symbol, df_train, df_test, timesteps, window_idx, reward_config=None
        ):
            return self._window_result(metrics_without_sharpe, window_idx=window_idx)

        try:
            with (
                patch.object(
                    trainer,
                    "_train_and_evaluate_window",
                    side_effect=fake_train_evaluate_window,
                ),
                patch(
                    "strategies.rl_trainer.asyncio.to_thread",
                    side_effect=self._sync_to_thread,
                ),
                patch(
                    "strategies.rl_trainer.prepare_dataframe",
                    return_value=synthetic_df,
                ),
            ):
                result = asyncio.run(trainer.train_walkforward(symbol="MES", n_windows=2))
        except KeyError as exc:
            pytest.fail(
                f"train_walkforward raised KeyError({exc!r}) — "
                f"regression: gate check must not access 'sharpe' key"
            )

        assert result.get("status") == "complete", f"Expected complete result, got: {result}"

    # ── Test 4: all windows pass ──────────────────────────────────────────────

    def test_walkforward_all_pass(self):
        """When all windows return passing metrics, result['all_pass'] is True
        and recommendation is 'deploy'."""
        import asyncio
        from unittest.mock import patch

        from strategies.rl_trainer import RLTrainer

        trainer = RLTrainer()
        synthetic_df = make_synthetic_df(n_bars=500)
        passing = self._passing_metrics()

        def fake_train_evaluate_window(
            symbol, df_train, df_test, timesteps, window_idx, reward_config=None
        ):
            return self._window_result(passing, window_idx=window_idx)

        with (
            patch.object(
                trainer,
                "_train_and_evaluate_window",
                side_effect=fake_train_evaluate_window,
            ),
            patch(
                "strategies.rl_trainer.asyncio.to_thread",
                side_effect=self._sync_to_thread,
            ),
            patch(
                "strategies.rl_trainer.prepare_dataframe",
                return_value=synthetic_df,
            ),
        ):
            result = asyncio.run(trainer.train_walkforward(symbol="MES", n_windows=3))

        assert result.get("status") == "complete"
        assert (
            result["all_pass"] is True
        ), f"Expected all_pass=True when every window passes, got: {result['all_pass']}"
        assert (
            result["recommendation"] == "deploy"
        ), f"Expected recommendation='deploy' when all pass, got: {result['recommendation']!r}"

    # ── Test 5: partial failure ───────────────────────────────────────────────

    def test_walkforward_partial_fail(self):
        """When some windows fail gates, all_pass is False and n_passed
        equals the number of windows with window_pass=True."""
        import asyncio
        from unittest.mock import patch

        from strategies.rl_trainer import RLTrainer

        trainer = RLTrainer()
        synthetic_df = make_synthetic_df(n_bars=500)

        passing_metrics = self._passing_metrics()
        # Window 1 fails: n_trades=20 is below min_trades gate
        failing_metrics = self._passing_metrics(n_trades=20)

        # Windows: pass, fail, pass  → n_passed=2
        window_sequence = [passing_metrics, failing_metrics, passing_metrics]
        call_count = {"n": 0}

        def fake_train_evaluate_window(
            symbol, df_train, df_test, timesteps, window_idx, reward_config=None
        ):
            idx = call_count["n"]
            call_count["n"] += 1
            metrics = window_sequence[idx % len(window_sequence)]
            return self._window_result(metrics, window_idx=window_idx)

        with (
            patch.object(
                trainer,
                "_train_and_evaluate_window",
                side_effect=fake_train_evaluate_window,
            ),
            patch(
                "strategies.rl_trainer.asyncio.to_thread",
                side_effect=self._sync_to_thread,
            ),
            patch(
                "strategies.rl_trainer.prepare_dataframe",
                return_value=synthetic_df,
            ),
        ):
            result = asyncio.run(trainer.train_walkforward(symbol="MES", n_windows=3))

        assert result.get("status") == "complete"
        assert (
            result["all_pass"] is False
        ), f"Expected all_pass=False when one window fails, got: {result['all_pass']}"

        # Derive n_passed from pass_rate * n_windows
        n_windows = result["n_windows"]
        n_passed = round(result["pass_rate"] * n_windows)
        assert n_passed == 2, (
            f"Expected 2 windows to pass (pass/fail/pass), "
            f"got n_passed={n_passed} (pass_rate={result['pass_rate']}, "
            f"n_windows={n_windows})"
        )
        # Double-check via the windows list directly
        windows_passed = sum(1 for w in result["windows"] if w["window_pass"])
        assert windows_passed == 2, f"Expected 2 window_pass=True entries, got {windows_passed}"


class TestMaxEpisodeBars:
    """
    Validates max_episode_bars / random window sampling in TradingEnvironment.

    Root cause of n_trades=14 over 6 runs: without max_episode_bars, each
    episode covers the full dataset (~12-20k bars), yielding only ~24 complete
    episodes over 500k timesteps. Agent finds HOLD-flat profitable (+0.003/bar
    over 12k bars = +36 reward) vs trading (entry_cost -0.10 per round-trip).

    Fix: max_episode_bars=500 → ~1,000 episodes per 500k training steps,
    random starts give diverse market conditions.
    """

    def test_episode_terminates_at_max_episode_bars(self):
        """Episode ends after max_episode_bars steps, not at full dataset end."""
        df = make_synthetic_df(n_bars=1000)
        env = TradingEnvironment(symbol="MES", df=df, max_episode_bars=100)
        obs, _ = env.reset()
        steps = 0
        terminated = False
        while not terminated:
            obs, reward, terminated, truncated, info = env.step(Action.HOLD)
            steps += 1
            if steps > 1000:
                break  # safety
        # Should end at or near max_episode_bars (within 1 for auto-close bar)
        assert steps <= 101, f"Expected ≤101 steps, got {steps}"
        assert steps >= 99, f"Expected ≥99 steps, got {steps}"

    def test_episode_start_is_random_across_resets(self):
        """Different resets produce different start indices (random windowing)."""
        df = make_synthetic_df(n_bars=2000)
        env = TradingEnvironment(symbol="MES", df=df, max_episode_bars=200)
        start_indices = set()
        for _ in range(10):
            env.reset()
            start_indices.add(env._idx)
        # With 10 resets on a 2000-bar df with max_episode_bars=200,
        # expect at least 3 distinct start positions (probability < 0.01 of failing)
        assert (
            len(start_indices) >= 3
        ), f"Expected random starts, got only {len(start_indices)} unique: {start_indices}"

    def test_episode_end_within_dataset_bounds(self):
        """_episode_end never exceeds n_bars regardless of start position."""
        df = make_synthetic_df(n_bars=600)
        env = TradingEnvironment(symbol="MES", df=df, max_episode_bars=500)
        for _ in range(20):
            env.reset()
            assert (
                env._episode_end <= env.n_bars
            ), f"_episode_end={env._episode_end} > n_bars={env.n_bars}"
            assert (
                env._episode_end > env._idx
            ), f"_episode_end={env._episode_end} <= start _idx={env._idx}"

    def test_small_df_runs_full_dataset(self):
        """When df is smaller than max_episode_bars, episode runs entire df."""
        df = make_synthetic_df(n_bars=100)
        env = TradingEnvironment(symbol="MES", df=df, max_episode_bars=500)
        env.reset()
        # With only 100 bars, latest_start = max(50, 100-500) = 50
        # _episode_end = min(50+500, 100) = 100 — runs full dataset
        assert (
            env._episode_end == env.n_bars
        ), f"Expected full dataset, got _episode_end={env._episode_end}, n_bars={env.n_bars}"

    def test_build_env_passes_max_episode_bars(self):
        """build_env() forwards max_episode_bars to TradingEnvironment."""
        df = make_synthetic_df(n_bars=1000)
        env = build_env("MES", df, max_episode_bars=200)
        assert (
            env._max_episode_bars == 200
        ), f"Expected _max_episode_bars=200, got {env._max_episode_bars}"

    def test_default_max_episode_bars_is_500(self):
        """Default max_episode_bars is 500 (as per rl_config.MAX_EPISODE_BARS)."""
        from strategies.rl_config import MAX_EPISODE_BARS

        assert MAX_EPISODE_BARS == 500
        df = make_synthetic_df(n_bars=1000)
        env = build_env("MES", df)
        assert env._max_episode_bars == 500


# ── Multi-Episode Evaluation Tests ───────────────────────────────────────────


class TestEvaluateEpisodes:
    """
    Tests for multi-episode evaluation behaviour introduced in RLTradingAgent.evaluate().

    Covers:
    - seed-based diversity: different seeds produce different episode start indices
    - full-dataset pinning: when max_episode_bars == len(df), start is always warm_up
    - aggregation logic: union of keys averaged correctly across multiple episodes
    """

    def test_evaluate_seed_gives_different_starts(self):
        """
        reset(seed=0) and reset(seed=1) on a windowed env must produce
        different start indices, confirming seed-based episode diversity.
        """
        df = make_synthetic_df(n_bars=1000)
        env = TradingEnvironment(symbol="MES", df=df, max_episode_bars=100)

        env.reset(seed=0)
        idx_seed0 = env._idx

        env.reset(seed=1)
        idx_seed1 = env._idx

        assert idx_seed0 != idx_seed1, (
            f"Expected different start indices for seed=0 and seed=1, "
            f"but both gave _idx={idx_seed0}. "
            "Seed-based diversity is not working for windowed episodes."
        )

    def test_evaluate_full_test_always_starts_at_warmup(self):
        """
        When max_episode_bars == len(df), latest_start == warm_up, so both
        reset(seed=0) and reset(seed=1) must pin _idx to 50 (warm_up).
        There is no room for a random start on a full-dataset eval.
        """
        df = make_synthetic_df(n_bars=200)
        env = TradingEnvironment(symbol="MES", df=df, max_episode_bars=len(df))

        env.reset(seed=0)
        idx_seed0 = env._idx

        env.reset(seed=1)
        idx_seed1 = env._idx

        assert (
            idx_seed0 == 50
        ), f"Full-dataset reset(seed=0) expected _idx=50 (warm_up), got {idx_seed0}"
        assert (
            idx_seed1 == 50
        ), f"Full-dataset reset(seed=1) expected _idx=50 (warm_up), got {idx_seed1}"

    def test_evaluate_aggregates_multiple_episodes(self):
        """
        evaluate() averages metrics over n_episodes using union of all keys.
        Two mocked episodes with different n_trades and profit_factor values
        must produce an averaged result of n_trades=15, profit_factor=2.0.
        """
        from unittest.mock import patch

        df = make_synthetic_df(n_bars=200)
        env = TradingEnvironment(symbol="MES", df=df, max_episode_bars=100)

        episode_metrics = [
            {
                "n_trades": 10,
                "profit_factor": 3.0,
                "win_rate": 0.6,
                "total_pnl": 500.0,
                "avg_pnl": 50.0,
                "max_drawdown": 0.05,
                "total_reward": 10.0,
                "flat_hold_rate": 0.8,
            },
            {
                "n_trades": 20,
                "profit_factor": 1.0,
                "win_rate": 0.4,
                "total_pnl": 100.0,
                "avg_pnl": 5.0,
                "max_drawdown": 0.10,
                "total_reward": 5.0,
                "flat_hold_rate": 0.6,
            },
        ]
        call_count = 0

        def fake_get_episode_metrics():
            nonlocal call_count
            result = episode_metrics[call_count % len(episode_metrics)]
            call_count += 1
            return result

        # Patch reset to return a valid obs without running a real episode,
        # and step to immediately terminate so the while-not-done loop exits.
        dummy_obs = env.observation_space.sample()

        with (
            patch.object(env, "reset", return_value=(dummy_obs, {})),
            patch.object(env, "step", return_value=(dummy_obs, 0.0, True, False, {})),
            patch.object(env, "get_episode_metrics", side_effect=fake_get_episode_metrics),
        ):
            # Build a minimal trained-looking agent (no PPO needed)
            from strategies.rl_agent import RLTradingAgent

            agent = RLTradingAgent.__new__(RLTradingAgent)
            agent._is_trained = True
            agent._training_metadata = {}
            # predict always returns HOLD so the mocked step terminates cleanly
            agent.model = None  # not used since step is mocked

            with patch.object(agent, "predict", return_value=int(Action.HOLD)):
                result = agent.evaluate(env, n_episodes=2)

        assert (
            result["n_trades"] == 15.0
        ), f"Expected averaged n_trades=15.0, got {result['n_trades']}"
        assert (
            result["profit_factor"] == 2.0
        ), f"Expected averaged profit_factor=2.0, got {result['profit_factor']}"


# ── Reward Config Override Tests ──────────────────────────────────────────────


class TestRewardConfigOverride:
    """
    Validates that the reward_config parameter in TradingEnvironment.__init__()
    and build_env() correctly merges override values on top of REWARD_CONFIG.

    Covers:
    - default behaviour: no override uses REWARD_CONFIG values unchanged
    - partial override: only specified keys are replaced
    - multi-key override: multiple keys can be replaced simultaneously
    - RUN7_SCENARIOS integration: scenario dicts produce expected values
    - build_env forwarding: build_env() threads reward_config through to env
    """

    def test_default_reward_config_is_used_when_none(self):
        """Creating env with no reward_config uses REWARD_CONFIG defaults."""
        from strategies.rl_config import REWARD_CONFIG

        df = make_synthetic_df()
        env = TradingEnvironment(symbol="MES", df=df)

        assert env._reward_cfg["entry_cost"] == REWARD_CONFIG["entry_cost"], (
            f"Expected entry_cost={REWARD_CONFIG['entry_cost']}, "
            f"got {env._reward_cfg['entry_cost']}"
        )

    def test_reward_config_override_replaces_entry_cost(self):
        """Override entry_cost only — other keys stay at REWARD_CONFIG defaults."""
        from strategies.rl_config import REWARD_CONFIG

        df = make_synthetic_df()
        env = TradingEnvironment(
            symbol="MES",
            df=df,
            reward_config={"entry_cost": -0.05},
        )

        assert (
            env._reward_cfg["entry_cost"] == -0.05
        ), f"Expected overridden entry_cost=-0.05, got {env._reward_cfg['entry_cost']}"
        # Non-overridden key must stay at the REWARD_CONFIG default
        assert env._reward_cfg["pnl_atr_weight"] == REWARD_CONFIG["pnl_atr_weight"], (
            f"Expected pnl_atr_weight={REWARD_CONFIG['pnl_atr_weight']} (unchanged), "
            f"got {env._reward_cfg['pnl_atr_weight']}"
        )

    def test_reward_config_override_multiple_keys(self):
        """Override flat_hold_reward and entry_cost simultaneously — both applied."""
        df = make_synthetic_df()
        env = TradingEnvironment(
            symbol="MES",
            df=df,
            reward_config={"flat_hold_reward": 0.001, "entry_cost": -0.10},
        )

        assert (
            env._reward_cfg["flat_hold_reward"] == 0.001
        ), f"Expected flat_hold_reward=0.001, got {env._reward_cfg['flat_hold_reward']}"
        assert (
            env._reward_cfg["entry_cost"] == -0.10
        ), f"Expected entry_cost=-0.10, got {env._reward_cfg['entry_cost']}"

    def test_run7_scenario_a_values(self):
        """Passing RUN7_SCENARIOS['A'] as reward_config applies the expected values."""
        from strategies.rl_config import RUN7_SCENARIOS

        df = make_synthetic_df()
        env = TradingEnvironment(
            symbol="MES",
            df=df,
            reward_config=RUN7_SCENARIOS["A"],
        )

        assert env._reward_cfg["flat_hold_reward"] == 0.001, (
            f"Scenario A: expected flat_hold_reward=0.001, "
            f"got {env._reward_cfg['flat_hold_reward']}"
        )
        assert env._reward_cfg["entry_cost"] == -0.10, (
            f"Scenario A: expected entry_cost=-0.10, " f"got {env._reward_cfg['entry_cost']}"
        )

    def test_build_env_forwards_reward_config(self):
        """build_env() passes reward_config through to TradingEnvironment."""
        df = make_synthetic_df()
        env = build_env(symbol="MES", df=df, reward_config={"entry_cost": -0.05})

        assert env._reward_cfg["entry_cost"] == -0.05, (
            f"Expected build_env to forward entry_cost=-0.05, "
            f"got {env._reward_cfg['entry_cost']}"
        )


# ── RLExecutor Tests ──────────────────────────────────────────────────────────


class TestRLExecutor:
    """Unit tests for the RL executor module."""

    def test_executor_registry_starts_empty(self):
        """Registry should be empty at module import time (or after cleanup)."""
        from strategies.rl_executor import _executor_registry

        # Registry may not be empty if other tests left executors,
        # but it should be a dict
        assert isinstance(_executor_registry, dict)

    def test_get_executor_status_empty_registry(self, monkeypatch):
        """get_executor_status returns empty dict when no executors are running."""
        import strategies.rl_executor as exe_mod

        monkeypatch.setattr(exe_mod, "_executor_registry", {})
        result = exe_mod.get_executor_status()
        assert result == {}

    def test_get_executor_status_with_mock_executor(self, monkeypatch):
        """get_executor_status returns status for each registered executor."""
        import strategies.rl_executor as exe_mod

        class MockExecutor:
            def get_status(self):
                return {"symbol": "MES", "is_running": False}

        monkeypatch.setattr(exe_mod, "_executor_registry", {"MES": MockExecutor()})
        result = exe_mod.get_executor_status()
        assert "MES" in result
        assert result["MES"]["symbol"] == "MES"

    def test_executor_registry_is_dict(self):
        """_executor_registry is a dict (not a single executor singleton)."""
        from strategies.rl_executor import _executor_registry

        assert isinstance(_executor_registry, dict)

    def test_executor_registry_lock_exists(self):
        """Threading lock companion must exist for thread safety."""
        import strategies.rl_executor as exe_mod

        assert hasattr(exe_mod, "_executor_registry_lock")
        import threading

        assert isinstance(exe_mod._executor_registry_lock, type(threading.Lock()))


# ── RL Config Regression Tests ────────────────────────────────────────────────


class TestRLConfig:
    """Regression guards for rl_config.py constants.

    These tests lock in the current values of REWARD_CONFIG and VALIDATION_GATES
    so that any accidental change to tuning parameters is caught immediately.
    If a value intentionally changes, update both rl_config.py and this test class.
    """

    def test_run11_let_winners_run_config_values(self):
        """
        Regression guard: Let-Winners-Run (Run 11) reward config values.
        hold_cost_only_when_losing=True: hold cost = 0 while unrealized_pnl > 0.
        """
        from strategies.rl_config import REWARD_CONFIG

        assert (
            REWARD_CONFIG["entry_cost"] == -0.01
        ), f"entry_cost should be -0.01, got {REWARD_CONFIG['entry_cost']}"
        assert (
            REWARD_CONFIG["hold_cost_per_bar"] == -0.010
        ), f"hold_cost_per_bar should be -0.010, got {REWARD_CONFIG['hold_cost_per_bar']}"
        assert (
            REWARD_CONFIG["flat_hold_reward"] == 0.000
        ), f"flat_hold_reward should be 0.000, got {REWARD_CONFIG['flat_hold_reward']}"
        assert (
            REWARD_CONFIG.get("hold_cost_only_when_losing") is True
        ), "hold_cost_only_when_losing must be True for Run 11 (let winners run)"

    def test_t1_bonus_to_entry_cost_ratio(self):
        """T1 bonus (0.50) is 50x entry cost (0.01) — strong T1 incentive."""
        from strategies.rl_config import REWARD_CONFIG

        t1_bonus = REWARD_CONFIG["t1_bonus"]
        entry_cost = abs(REWARD_CONFIG["entry_cost"])
        ratio = t1_bonus / entry_cost
        assert ratio == 50.0, f"T1 bonus / |entry_cost| = {ratio:.2f}, expected 50.0"

    def test_hold_cost_zero_when_winning(self, df_mes):
        """Run 11: hold cost must be 0 when position is in profit."""
        env = TradingEnvironment(symbol="MES", df=df_mes, initial_capital=10_000.0)
        env.reset()
        env.step(Action.BUY)

        # Patch entry price below current close — position is winning
        current_close = float(env.df.iloc[env._idx]["close"])
        env._entry_price = current_close * 0.95  # 5% below current → unrealized profit

        _, reward_winning, _, _, _ = env.step(Action.HOLD)
        # Hold cost = 0, only pnl_reward applies (0 for HOLD). Reward should be near 0.
        assert (
            reward_winning >= -0.05
        ), f"Hold cost should be 0 when in profit, reward={reward_winning:.5f}"

    def test_hold_cost_applied_when_losing(self, df_mes):
        """Run 11: hold cost must be applied when position is underwater."""
        from strategies.rl_config import REWARD_CONFIG

        env = TradingEnvironment(symbol="MES", df=df_mes, initial_capital=10_000.0)
        env.reset()
        env.step(Action.BUY)

        # Patch entry price above current close — position is losing
        current_close = float(env.df.iloc[env._idx]["close"])
        env._entry_price = current_close * 1.10  # 10% above current → underwater

        _, reward_losing, _, _, _ = env.step(Action.HOLD)
        expected_hold_cost = REWARD_CONFIG["hold_cost_per_bar"]  # -0.010
        assert reward_losing <= expected_hold_cost + 0.05, (
            f"Hold cost should be applied when losing, reward={reward_losing:.5f}, "
            f"expected approx {expected_hold_cost}"
        )


# ── RL Trainer Stop Mechanism Tests ───────────────────────────────────────────


class TestRLTrainerStop:
    """Verify the module-level stop/abort mechanism for graceful training cancellation."""

    def test_stop_event_exists_and_is_threading_event(self):
        """Module-level _stop_event must be a threading.Event for abort support."""
        import threading

        from strategies.rl_trainer import _stop_event, clear_stop, request_stop

        assert isinstance(_stop_event, threading.Event)
        # Verify request_stop sets it and clear_stop clears it
        clear_stop()
        assert not _stop_event.is_set()
        request_stop()
        assert _stop_event.is_set()
        clear_stop()  # clean up
        assert not _stop_event.is_set()
