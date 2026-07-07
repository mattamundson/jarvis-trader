"""Quick test that RL training works with 23 features."""

import sys

sys.path.insert(0, r"C:\Users\mattm\ThinkorSwim\jarvis-trader\engine")

import numpy as np
import pandas as pd

# ── Replicate _make_synthetic_ohlcv and _make_env from test_rl_module ──────────


def _make_synthetic_ohlcv(n_bars: int = 300) -> pd.DataFrame:
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
            "atr": atr,
            "stc_val": rng.uniform(10, 90, n_bars),
            "ema_21": close * rng.uniform(0.99, 1.01, n_bars),
            "ema_trend": rng.choice(["bullish", "neutral", "bearish"], n_bars),
            "phase_val": rng.uniform(-50, 50, n_bars),
            "volume_signal": rng.choice(["buyer_dominant", "balanced", "seller_dominant"], n_bars),
            "macd_hist": rng.normal(0, 1, n_bars),
            "rsi": rng.uniform(30, 70, n_bars),
            "bb_upper": close + atr * 2,
            "bb_lower": close - atr * 2,
            "adx": rng.uniform(15, 45, n_bars),
        }
    )
    return df


def _make_env(n_bars: int = 300):
    from strategies.rl_environment import TradingEnvironment

    df = _make_synthetic_ohlcv(n_bars)
    return TradingEnvironment(symbol="MES", df=df, initial_capital=10_000.0)


# ── Step 1: Verify N_FEATURES == 23 ──────────────────────────────────────────

from strategies.rl_config import N_FEATURES, TIMESTEPS_QUICK

print(f"N_FEATURES = {N_FEATURES}")
assert N_FEATURES == 23, f"Expected 23 features, got {N_FEATURES}"
print("  [OK] N_FEATURES == 23")

# ── Step 2: Test environment observation shape ────────────────────────────────

print("\nBuilding environment with 300 synthetic bars...")
env = _make_env(n_bars=300)
obs, info = env.reset()
print(f"  Observation shape: {obs.shape}")
print(f"  Observation dtype: {obs.dtype}")
assert obs.shape == (N_FEATURES,), f"Wrong obs shape: {obs.shape}"
assert obs.dtype == np.float32, f"Wrong dtype: {obs.dtype}"
assert not np.any(np.isnan(obs)), "Observation contains NaN!"
assert not np.any(np.isinf(obs)), "Observation contains Inf!"
print("  [OK] Environment observation shape (23,) confirmed")

# ── Step 3: Run 10 environment steps ─────────────────────────────────────────

print("\nRunning 10 environment steps (all HOLD)...")
for i in range(10):
    obs, reward, terminated, truncated, info = env.step(0)  # HOLD
    if terminated:
        print(f"  Episode terminated at step {i+1}")
        break
print(f"  Last obs shape: {obs.shape}, reward: {reward:.4f}")
print("  [OK] Environment steps passed")

# ── Step 4: Test all 4 actions ────────────────────────────────────────────────

print("\nTesting all 4 actions (BUY/HOLD/CLOSE/SELL/CLOSE)...")
env2 = _make_env(n_bars=200)
env2.reset()
from strategies.rl_config import Action

env2.step(int(Action.BUY))
env2.step(int(Action.HOLD))
env2.step(int(Action.CLOSE))
env2.step(int(Action.SELL))
env2.step(int(Action.CLOSE))
print("  [OK] All 4 actions execute without error")

# ── Step 5: Create RLTradingAgent ─────────────────────────────────────────────

print("\nCreating RLTradingAgent for MES...")
from strategies.rl_agent import RLTradingAgent

agent = RLTradingAgent(symbol="MES", env=env)
print(f"  Agent symbol: {agent.symbol}")
print(f"  Agent trained: {agent._is_trained}")
print(f"  Model type: {type(agent.model).__name__}")
print("  [OK] RLTradingAgent created")

# ── Step 6: Test predict (untrained = HOLD) ───────────────────────────────────

print("\nTesting predict on untrained agent...")
fake_obs = np.zeros(N_FEATURES, dtype=np.float32)
action = agent.predict(fake_obs, kill_switch_active=False)
assert action == int(Action.HOLD), f"Untrained agent must return HOLD, got {action}"
print(f"  Untrained agent returned: {action} (HOLD=0) [OK]")

# ── Step 7: Short training run (TIMESTEPS_QUICK = 10,000) ────────────────────

print(f"\nStarting PPO training: {TIMESTEPS_QUICK:,} timesteps (quick smoke test)...")
print("  (This will take ~15-30 seconds on a modern CPU...)")
import time

t0 = time.time()
train_env = _make_env(n_bars=1000)  # larger dataset for more diverse episodes
agent2 = RLTradingAgent(symbol="MES", env=train_env)
summary = agent2.train(total_timesteps=TIMESTEPS_QUICK)
elapsed = time.time() - t0

print(f"  Training completed in {elapsed:.1f}s")
print(f"  Timesteps: {summary.get('total_timesteps', '?'):,}")
print(f"  HOLD rate: {summary.get('action_distribution', {}).get('HOLD', '?')}")
print(f"  Action distribution: {summary.get('action_distribution', {})}")
if summary.get("episode_rewards"):
    print(f"  Last mean reward: {summary['episode_rewards'][-1]:.4f}")
print("  [OK] Training run completed")

# ── Step 8: Evaluate on test environment ─────────────────────────────────────

print("\nEvaluating agent on test environment...")
test_env = _make_env(n_bars=300)
metrics = agent2.evaluate(test_env, n_episodes=1)
print(f"  n_trades:      {metrics.get('n_trades', '?')}")
print(f"  win_rate:      {metrics.get('win_rate', '?')}")
print(f"  profit_factor: {metrics.get('profit_factor', '?')}")
print(f"  max_drawdown:  {metrics.get('max_drawdown', '?')}")
print(f"  sharpe:        {metrics.get('sharpe', '?')}")
print(f"  hold_rate:     {metrics.get('hold_rate', '?')}")
print(f"  flat_hold_rate:{metrics.get('flat_hold_rate', '?')}")
print(f"  passes_validation: {metrics.get('passes_validation', '?')}")
print("  [OK] Evaluation completed")

# ── Step 9: Save model ────────────────────────────────────────────────────────

print("\nSaving model...")
import os

os.makedirs(r"C:\Users\mattm\ThinkorSwim\jarvis-trader\data\rl_models", exist_ok=True)
model_path = agent2.save(r"C:\Users\mattm\ThinkorSwim\jarvis-trader\data\rl_models\MES_smoke_test")
print(f"  Saved to: {model_path}.zip")
print("  [OK] Model saved")

# ── Summary ───────────────────────────────────────────────────────────────────

print("\n" + "=" * 60)
print("ALL TESTS PASSED")
print("=" * 60)
print(f"  N_FEATURES    : {N_FEATURES} (expected 23)")
print(f"  obs.shape     : {obs.shape}")
print(f"  Training time : {elapsed:.1f}s for {TIMESTEPS_QUICK:,} steps")
print(f"  n_trades      : {metrics.get('n_trades', '?')} (need >= 60 for production)")
print(f"  profit_factor : {metrics.get('profit_factor', '?')} (need >= 2.0)")
print(f"  win_rate      : {metrics.get('win_rate', '?')} (need >= 0.55)")
print(f"  passes gates  : {metrics.get('passes_validation', False)}")
print()
print("NOTE: Synthetic data results are not meaningful for trading.")
print("For real training, use RLTrainer.train_symbol('MES') with Polygon/IBKR data.")
