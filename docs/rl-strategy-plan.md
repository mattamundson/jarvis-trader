# RL Strategy Module — Project Plan
**jarvis-trader** | `engine/strategies/` | Status: PLANNED

---

## Background

The `engine/strategies/` directory has been empty since Phase 1. This plan implements a reinforcement learning strategy discovery module, filling that gap with a PPO agent trained to trade MES/MNQ/MCL futures.

**Inspiration**: RL trading bot research (50k episodes, $2k→$68k, 72.4% WR):
- Agent learned to **HOLD 62%** of the time (started at 30%)
- **Trade frequency dropped**: 40/day → 9/day
- Higher conviction = better outcomes

This directly validates jarvis-trader's paper trading approach — the RL agent independently discovers that fewer, higher-quality trades beat frequent trading.

---

## Objective

Build a complete RL trading agent that:
1. Uses existing `engine/backtest/signals.py` features as state space
2. Learns from historical OHLCV data in `engine/database/`
3. Outputs BUY / SELL / HOLD / CLOSE decisions
4. Passes ALL actions through `engine/risk/safety_layer.py` (SACRED)
5. Is evaluated against jarvis-trader validation targets before paper trading

---

## Files to Create

```
engine/strategies/
├── __init__.py              ← Already exists (empty stub)
├── rl_config.py             ← Hyperparameters + state/action space definitions
├── rl_environment.py        ← Gymnasium TradingEnvironment
├── rl_agent.py              ← Stable-baselines3 PPO wrapper + SafetyLayer integration
├── rl_trainer.py            ← Walk-forward training loop + SQLite logging
└── rl_evaluator.py          ← OOS evaluation + metric reporting
```

**New API endpoints** (add to `engine/main.py`):
```
POST /strategies/rl/train        — Start training for a symbol
GET  /strategies/rl/status       — Training status + latest metrics
GET  /strategies/rl/results/{id} — Walk-forward results for a run
POST /strategies/rl/evaluate     — Evaluate saved model on date range
```

**New dashboard page** (create `dashboard/app/strategies/page.tsx`):
- Training progress (loss curve)
- Walk-forward performance table
- Action distribution (BUY/SELL/HOLD/CLOSE breakdown)
- Comparison: RL agent vs current STC signal

---

## State Space (19 features)

Derived from existing `engine/backtest/signals.py` INSTRUMENT_PARAMS:

| Feature | Source |
|---------|--------|
| `close_normalized` | OHLCV |
| `high_low_range` | OHLCV / ATR |
| `close_vs_vwap` | OHLCV |
| `stc_value` | signals.py STC |
| `stc_slope` | signals.py STC |
| `stc_above_os` | signals.py (OS=15 for MES/MNQ/MCL) |
| `stc_below_ob` | signals.py (OB=83 for MES/MCL, 92 for MNQ) |
| `atr_14` | signals.py |
| `atr_normalized` | signals.py |
| `atr_vs_20d_avg` | computed |
| `regime_score` | signals.py 5-layer filter |
| `trend_direction` | signals.py |
| `structure_level` | signals.py |
| `volume_vs_avg` | OHLCV |
| `volume_stack_signal` | signals.py |
| `current_position` | environment state |
| `unrealized_pnl_atr` | environment state |
| `bars_in_trade` | environment state |

## Action Space

```python
ACTIONS = {
    0: "HOLD",   # Do nothing (default — agent must learn to use this)
    1: "BUY",    # Open long position
    2: "SELL",   # Open short position
    3: "CLOSE",  # Close current position
}
```

## Reward Function

```
R = (realized_pnl / atr_14)           # Primary: P&L in ATR units
  + (-0.01 * bars_in_trade)           # Holding cost
  + (-0.05 if new_entry else 0)       # Overtrading penalty
```

Target win per trade: T1 ATR multiple (MES=2.0, MNQ=1.0, MCL=1.5)

---

## Training Configuration

### PPO Hyperparameters

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
    "ent_coef": 0.01,      # Entropy encourages HOLD exploration
    "total_timesteps": 500_000,
}
```

### Data Split

```
Train:    2020-01-01 → 2023-12-31  (4 years — in-sample)
Validate: 2024-01-01 → 2024-06-30  (6 months — hyperparameter tuning)
Test:     2024-07-01 → present      (out-of-sample — final evaluation)

Walk-forward: 6-month rolling windows, 8 windows total
```

---

## Safety Integration (MANDATORY)

**Every RL action MUST pass through `engine/risk/safety_layer.py` before execution:**

```python
# In rl_agent.py
from engine.risk.safety_layer import SafetyLayer

safety = SafetyLayer()

def get_safe_action(self, obs: np.ndarray, symbol: str) -> int:
    raw_action = self.model.predict(obs, deterministic=True)[0]

    # Safety check — SACRED, no override
    check = safety.pre_trade_check(
        symbol=symbol,
        action=ACTION_NAMES[raw_action],
        size=self.position_size,
    )

    if not check.approved:
        log.warning(f"RL action blocked: {check.reason}")
        return ACTION_HOLD  # Default to HOLD on any safety failure

    return raw_action
```

**Kill switch integration** (from `engine/config.py`):
- Daily loss > 2% → halt RL trading (same as pipeline)
- Drawdown > 10% → halt RL trading
- ConsecutiveLossTracker: 3=0.5x, 5=0.25x, 7=24h halt (same thresholds as `engine/risk/loss_tracker.py`)

---

## Validation Gates

The RL agent must pass ALL of these before paper trading (same targets as existing pipeline):

| Metric | Target | Source |
|--------|--------|--------|
| Profit Factor | ≥ 2.0 | jarvis-trader validation spec |
| Sharpe Ratio | ≥ 1.5 | jarvis-trader validation spec |
| Win Rate | ≥ 55% | jarvis-trader validation spec |
| Min Trades | ≥ 60 | jarvis-trader validation spec |
| Min Days | ≥ 30 | jarvis-trader validation spec |
| Max Drawdown | ≤ 15% | jarvis-trader validation spec |
| HOLD Rate | ≥ 50% | Quality filter — prevents overtrading |
| OOS Sharpe ≥ IS Sharpe × 0.7 | No overfitting | Walk-forward requirement |

---

## Implementation Phases

### Phase 1 — Environment (est. 1 week)
- [ ] Create `engine/strategies/rl_config.py` — state/action definitions, reward config
- [ ] Create `engine/strategies/rl_environment.py` — Gymnasium env
  - Load OHLCV from SQLite `ohlcv_cache`
  - Compute state features using signals.py functions
  - Implement reward function
  - Test with `gym.utils.env_checker.check_env()`

### Phase 2 — Agent (est. 1 week)
- [ ] Create `engine/strategies/rl_agent.py` — PPO wrapper
  - SafetyLayer integration (MANDATORY before any action)
  - Model save/load (checkpoint every 50k steps)
  - Inference mode (deterministic=True)
- [ ] Basic training loop test — 10k steps, verify reward is non-trivial

### Phase 3 — Walk-Forward Trainer (est. 1 week)
- [ ] Create `engine/strategies/rl_trainer.py`
  - Walk-forward window generator
  - Full training loop (500k steps per window)
  - SQLite logging (`strategy_runs` table)
  - Validation metrics per window
- [ ] Create `engine/strategies/rl_evaluator.py`
  - OOS evaluation
  - Full metrics report (Sharpe, PF, WR, DD, HOLD rate)

### Phase 4 — API + Dashboard (est. 1 week)
- [ ] Add 4 endpoints to `engine/main.py`
- [ ] Create `dashboard/app/strategies/page.tsx`
  - Training progress component
  - Walk-forward results table
  - Action distribution chart
  - RL vs STC comparison

---

## Dependencies to Add

```bash
pip install stable-baselines3[extra] gymnasium torch
```

Add to `requirements.txt`:
```
stable-baselines3>=2.0.0
gymnasium>=0.29.0
torch>=2.0.0
```

---

## Success Criteria

1. `pytest engine/strategies/` — all tests pass
2. 8-window walk-forward on MES 1h — all windows meet validation targets
3. OOS Sharpe ≥ 1.5 on test set (2024-07-01 → present)
4. HOLD rate ≥ 50% in trained agent
5. SafetyLayer correctly blocks 100% of unsafe RL actions
6. Dashboard `/strategies` page renders training progress correctly

---

## Notes

- **Do NOT run RL agent in live mode** until paper trading validation is complete (minimum 30 trading days)
- `live_enabled=False` in `engine/config.py` blocks live trading globally — this is the final gate
- RL agent runs in parallel with existing STC pipeline — they do NOT interfere
- Discovered RL strategies feed into the existing paper trading validation queue

---

*Created: 2026-04-01 | Skill: rl-strategy-discovery*

---

## Session 2026-04-02 — Bug Fixes & Max Episode Bars

### Root Cause Analysis: Why n_trades Was Always 14

Three training runs (Runs 4, 5, 6) with different entry_cost values (-0.30, -0.20, -0.10) all produced n_trades=14 — despite the action distribution showing BUY=16%+. Investigation revealed:

**Bug: Insufficient training episodes due to full-dataset episode length**

Without `max_episode_bars`, each episode = entire training dataset (~12,000-20,000 bars). With 500k timesteps and ~12,000 bars/episode, training produced only **~24 complete episodes**. This is critically insufficient for PPO to converge on a trading policy.

The agent discovered that HOLD-when-flat earns `flat_hold_reward × episode_bars = 0.003 × 12,000 = +36 reward per episode` safely, while each trade costs `-0.10 entry` + uncertain PnL. With only 24 data points (episodes), the policy gradient couldn't overcome the HOLD bias.

Action distribution "BUY=16%" referred to **training-time** actions — most were redundant BUY-when-already-long (-0.10 penalty) which the agent absorbed rather than risk new entries.

### Fix Applied: max_episode_bars=500 (Random Window Sampling)

```
engine/strategies/rl_environment.py
engine/strategies/rl_config.py      → MAX_EPISODE_BARS = 500
engine/strategies/rl_trainer.py
```

- Training env: `max_episode_bars=500` → random 500-bar window per episode
- Evaluation env: `max_episode_bars=len(df_test)` → full test set, deterministic
- Result: **~1,000 diverse training episodes** per 500k-step run (42× more than before)
- Each episode: max flat_hold_reward = 500 × 0.003 = **+1.5** (vs +36 before)

### Key Metrics Progress

| Run | entry_cost | max_episode_bars | Episodes | n_trades | pf   | Status   |
|-----|------------|-----------------|----------|----------|------|----------|
| 4   | -0.20      | full (~12k)     | ~24      | 14       | 0.30 | FAIL     |
| 5   | -0.10      | full (~12k)     | ~24      | 14       | 0.30 | FAIL     |
| 6   | -0.10      | 500 (random)    | ~1,000   | TBD      | TBD  | ACTIVE   |

### All Bugs Fixed (Session Total: 25)

Full list in `docs/session-logs/RL_SESSION_2026-04-02.md`.
Notable fixes: hold_rate gate in passes_validation, MAX_EPISODE_BARS import, seed=i in evaluate(), pipeline_runs schema verified, rl_executor.py 5 bugs, walk-forward cache + gate key bugs.

### Test Coverage: 69 tests passing

New test classes added:
- `TestMaxEpisodeBars` (6 tests): validates random window sampling
- `TestEvaluateEpisodes` (3 tests): validates multi-episode averaging
- `TestWalkForward` (5 tests): validates walk-forward training
