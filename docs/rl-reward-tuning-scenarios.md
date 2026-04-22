# RL Reward Tuning — Scenario Decision Tree

Run 5: entry_cost=-0.10, flat_hold_reward=0.003 (IN PROGRESS)
Prediction: 35-55 trades, hold_rate 65-75%

## Scenario A: BUY-spam returns (n_trades > 150, hold_rate < 40%)
Change entry_cost: -0.10 → -0.15
Break-even: 50 bars
Expected trades: 25-35

REWARD_CONFIG change:
"entry_cost": -0.15,

## Scenario B: Still over-HOLDing (n_trades < 60, hold_rate > 50%) ← MOST LIKELY
Change flat_hold_reward: 0.003 → 0.005 (keep entry_cost=-0.10)
Break-even: 20 bars (was 33)
Expected trades: 55-70

REWARD_CONFIG change:
"flat_hold_reward": 0.005,

## Scenario C: Good trade count but poor PF (n_trades 60-100, PF < 1.0)
Signal quality problem — adjust PPO params:
"learning_rate": 1e-4  (was 3e-4)
"ent_coef": 0.10  (was 0.05)

## Scenario D: PASS — all gates met!
Deploy model → POST /strategies/rl/deploy
Then walk-forward: POST /strategies/rl/train-walkforward

## After Run 5 completes — IMMEDIATE ACTIONS:
1. Note n_trades value
2. If n_trades < 60: Apply Scenario B (change flat_hold_reward to 0.005)
3. Restart engine (kill python processes, restart with .venv/Scripts/python.exe)
4. Submit Run 6: POST /strategies/rl/train {"symbol":"MES","timesteps":500000}
5. If n_trades > 150: Apply Scenario A instead
