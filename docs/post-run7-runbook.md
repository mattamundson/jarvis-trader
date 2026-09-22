# Post-Run 7 Runbook — JARVIS Trader RL Pipeline

Reference for actions after Run 7 completes. Work through steps in order.

---

## Step 1: Evaluate Run 7 Results

```bash
python /tmp/eval_run7.py
```

The evaluator polls `GET /api/v1/strategies/rl/status` until `training_active=false`, then prints PASS/FAIL for each gate and the exact next action.

**Gates:**

| Gate | Threshold |
|------|-----------|
| `profit_factor` | ≥ 2.0 |
| `sharpe` | ≥ 1.5 |
| `win_rate` | ≥ 0.55 |
| `n_trades` | ≥ 60 |
| `hold_rate` | ≥ 0.50 |
| `max_drawdown` | ≤ 0.15 |

**Decision Tree:**

```
n_trades ≥ 60 AND all gates pass   → Proceed to Step 3 (walk-forward)
n_trades ≥ 60, quality gates fail  → Run 8: timesteps=750k, ent_coef=0.07
30 ≤ n_trades < 60                 → Scenario B: flat_hold_reward=0.003
n_trades < 30                      → Two-Lever: entry_cost=-0.02, hold_cost=-0.002
```

---

## Step 2: Restart Engine (required after ANY config change)

Use the existing restart script — it kills port 8010, starts uvicorn (no --reload), and verifies health:

```powershell
cd C:\Users\mattm\ThinkorSwim\jarvis-trader
.\restart_engine.ps1
```

If the script fails to kill (edge case), nuclear fallback:
```powershell
.\kill_python.ps1
# Then manually start uvicorn (see restart_engine.ps1 for exact command)
```

Verify up: `curl -H "X-API-Key: [REDACTED]" http://localhost:8010/health`

---

## Step 3: Walk-Forward Validation

Only run this if `n_trades ≥ 60` AND all quality gates pass.

```bash
curl -X POST http://localhost:8010/api/v1/strategies/rl/train-walkforward \
  -H "X-API-Key: [REDACTED]" \
  -H "Content-Type: application/json" \
  -d '{"symbol":"MES","timesteps":500000,"n_windows":8}'
```

Poll for completion:

```bash
curl -H "X-API-Key: [REDACTED]" \
  http://localhost:8010/api/v1/strategies/rl/status
# Wait until training_active=false
```

All 8 windows must individually pass all 6 gates for the model to be considered walk-forward validated. If any window fails, treat as quality failure (Run 8 path).

---

## Step 4: Deploy to Paper Trading

Only run after walk-forward passes all 8 windows.

```bash
# Get best model path from status
curl -H "X-API-Key: [REDACTED]" \
  http://localhost:8010/api/v1/strategies/rl/status
# Note the "best_model_path" value

# Deploy
curl -X POST http://localhost:8010/api/v1/strategies/rl/deploy \
  -H "X-API-Key: [REDACTED]" \
  -H "Content-Type: application/json" \
  -d '{"symbol":"MES","model_path":"data/rl_models/MES_<timestamp>","active":true}'

# Confirm executor is running
curl -H "X-API-Key: [REDACTED]" \
  http://localhost:8010/api/v1/strategies/rl/executor/status
```

---

## Step 5: Multi-Symbol Training

Start only after MES is deployed and executor confirmed running.

```bash
nohup /tmp/train_symbols_run7.sh > /tmp/run7_multi_symbol.log 2>&1 &

# Monitor progress
tail -f /tmp/run7_multi_symbol.log
```

Trains MNQ → MCL → MGC sequentially, 500k steps each. Each symbol runs through the same gate evaluation before proceeding to the next.

---

## Step 6: Verify All Systems

```bash
# Engine health
curl -H "X-API-Key: [REDACTED]" http://localhost:8010/health

# RL strategy health
curl -H "X-API-Key: [REDACTED]" \
  http://localhost:8010/api/v1/strategies/rl/health

# Executor status (confirm active=true after deploy)
curl -H "X-API-Key: [REDACTED]" \
  http://localhost:8010/api/v1/strategies/rl/executor/status
```

Dashboard: open `http://localhost:3010/strategies` and confirm the RL panel shows the executor as running with the deployed model name.

---

## Config Change Reference

File: `C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\strategies\rl_config.py`

Edit the `REWARD_CONFIG` dict, then restart the engine (Step 2) before launching the next run.

**Scenario A — Baseline (current Run 7 config, no change needed):**
```python
REWARD_CONFIG = {
    "profit_scale": 1.0,
    "flat_hold_reward": 0.001,
    "entry_cost": -0.01,
    "hold_cost": -0.001,
    "ent_coef": 0.05,
}
```

**Scenario B — Low trade count (30 ≤ n_trades < 60), increase hold incentive:**
```python
REWARD_CONFIG = {
    "profit_scale": 1.0,
    "flat_hold_reward": 0.003,   # raised from 0.001
    "entry_cost": -0.01,
    "hold_cost": -0.001,
    "ent_coef": 0.05,
}
```

**Scenario C — Quality fails, raise exploration (Run 8):**
```python
REWARD_CONFIG = {
    "profit_scale": 1.0,
    "flat_hold_reward": 0.001,
    "entry_cost": -0.01,
    "hold_cost": -0.001,
    "ent_coef": 0.07,            # raised from 0.05
}
# Also set: timesteps = 750_000 in the train call
```

**Two-Lever — Very low trade count (n_trades < 30), loosen entry + hold penalties:**
```python
REWARD_CONFIG = {
    "profit_scale": 1.0,
    "flat_hold_reward": 0.001,
    "entry_cost": -0.02,         # increased penalty to discourage overtrading
    "hold_cost": -0.002,         # increased hold cost to force selectivity
    "ent_coef": 0.05,
}
```

---

## Reference Documents
- `docs/run8-monitoring-checklist.md` — diagnosis table, t1_hit_rate thresholds, quality fixes
- `docs/rl-reward-tuning-theory.md` — break-even analysis, HOLD-attractor explanation
- `docs/rl-run7-decision-tree.md` — updated with Run 7 actual results

---

*Last updated: 2026-04-02 | Engine port: 8010 | Dashboard port: 3010*
