# RL Run 7 — Post-Training Decision Tree

## Context
Run 7 started: 2026-04-02 09:56:23 UTC
Config: Scenario C (entry_cost=-0.05, flat_hold_reward=0.000)
ETA complete: ~10:40-10:45 UTC

## Decision Logic

### If n_trades >= 60 AND all gates pass (PF>=2.0, Sharpe>=1.5, WR>=55%, DD<=15%, HOLD>=50%):
-> **DEPLOY** — Run walk-forward, then deploy to paper trading
Steps:
1. Restart engine (kill uvicorn, restart with `start_jarvis.bat`)
2. Wait for engine to start on port 8010
3. `POST /strategies/rl/train-walkforward {"symbol":"MES","timesteps_per_window":100000}`
4. Wait for 8 windows to complete
5. If 6+/8 windows pass -> `POST /strategies/rl/deploy {"symbol":"MES","model_path":"<best_model>"}`
6. Start multi-symbol: `nohup /tmp/train_symbols_run7.sh > /tmp/run7_training.log 2>&1 &`

### If 30 <= n_trades < 60 (improved but not enough):
-> **Scenario B** — Reintroduce flat_hold_reward but keep lower entry_cost
Changes to rl_config.py REWARD_CONFIG:
  - entry_cost: -0.05 -> -0.05 (keep)
  - flat_hold_reward: 0.000 -> 0.003

### If n_trades < 30 (still stuck):
-> **Two-lever fix** — Increase hold_cost AND reduce entry_cost further
Changes to rl_config.py REWARD_CONFIG:
  - entry_cost: -0.05 -> -0.02
  - hold_cost_per_bar: -0.001 -> -0.002 (stronger hold pressure while in position)
  - flat_hold_reward: 0.000 (keep)

### If n_trades >= 60 but gates fail (PF < 2.0 or WR < 0.55):
-> **Quality training** — Agent trades enough but chooses wrong direction
Changes:
  - Increase timesteps to 750,000 (TIMESTEPS_FULL path)
  - Optionally: Increase ent_coef from 0.05 to 0.07 in PPO_CONFIG to explore more

## After Run 7 Decision — Multi-Symbol Plan
Once MES passes validation:
1. Run `/tmp/train_symbols_run7.sh` to sequentially train MNQ, MCL, MGC
2. Each symbol uses same Scenario C config (already in rl_config.py)
3. Monitor with `tail -f /tmp/run7_training.log`
4. Each symbol needs separate walk-forward + deploy steps

## Validation Gates Reference
| Gate | Threshold | Key |
|------|-----------|-----|
| Profit Factor | >= 2.0 | profit_factor |
| Sharpe Ratio | >= 1.5 | sharpe |
| Win Rate | >= 55% | win_rate |
| Min Trades | >= 60 | n_trades |
| Hold Rate | >= 50% | hold_rate |
| Max Drawdown | <= 15% | max_drawdown |

---

## Run 7 Actual Results (Completed ~10:13 UTC 2026-04-02)

### Config Used
- Scenario C: `entry_cost=-0.05`, `flat_hold_reward=0.000`, `hold_cost_per_bar=-0.001`
- 500k timesteps, max_episode_bars=500, MES 1h data

### Outcomes vs Predictions

| Metric | Predicted (Scenario C) | Actual |
|--------|----------------------|--------|
| n_trades | 60-120 | **3** |
| hold_rate | 40-55% | **98.8%** |
| profit_factor | unknown | 0.0547 |
| sharpe | unknown | -10.327 |
| win_rate | unknown | 66.7% |
| max_drawdown | unknown | 2.56% |

### Root Cause Analysis

The decision tree Scenario C prediction of 60-120 trades was wrong. The agent over-corrected to nearly-zero trading despite the entry_cost being halved.

**Key insight**: The problem was not just `flat_hold_reward` but the **HOLD attractor**. Even without a passive flat reward, the agent discovered that holding one position for the entire episode is the optimal strategy when:
1. `entry_cost=-0.05` (50-bar break-even) makes re-entry expensive
2. `hold_cost_per_bar=-0.001` is cheap enough to sit in a good position indefinitely
3. The P&L signal rewards precision over frequency

Training showed positive episode rewards (6-8 mean), meaning the agent WAS profitable per episode — it just learned to achieve that profit with 1-3 high-conviction trades rather than frequent cycling.

### Decision Taken

**Branch activated**: n_trades < 30 → Two-Lever Fix

### Run 8 Config Applied
- `entry_cost`: -0.05 → **-0.02** (break-even: 50 bars → **10 bars**)
- `hold_cost_per_bar`: -0.001 → **-0.002** (forces faster position cycling)
- `flat_hold_reward`: 0.000 (unchanged — pure P&L signal)

### Run 8 Predictions
- Expected n_trades: 30-80
- Expected hold_rate: 50-75%
- Break-even hold = 10 bars → agent should cycle every 10-30 bars
- Risk: churning (entering/exiting too quickly without reaching T1)

### If Run 8 Fails
- n_trades < 30 again → entry_cost=-0.01, hold_cost=-0.003 (most aggressive)
- n_trades > 120 (churning) → entry_cost=-0.03, t1_bonus=0.15
- Quality gates fail but n_trades OK → 750k timesteps, ent_coef=0.07
