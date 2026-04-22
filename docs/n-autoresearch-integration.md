# n-autoresearch Integration — Plumbing + Deferred Policy

**Status:** PLUMBING INSTALLED. DO NOT RUN SWEEPS YET.

## Summary

This doc tracks the minimal scaffolding that lets jarvis-trader use the n-autoresearch
skill's `run_full_cycle.py` orchestrator for RL hyperparameter search. As of 2026-04-10,
only the REST server + training adapter + search space are in place. **Sweeps are
deferred until paper trading validates the composite_score metric.**

## Why deferred

Three red flags (per plan review at 2026-04-10):

1. **No paper-trading outcomes yet.** Auto-tuning against in-sample backtest metrics
   will overfit the backtester, not the market. Wait until ~2 weeks of live paper
   trades provide ground-truth signal to validate that composite_score correlates
   with real edge.
2. **Metric gameability.** composite_score with Sharpe dominance rewards inactive
   agents. n-autoresearch's "combine" phase will find these exploits within ~5
   experiments. See `rl_search_space.json` guards (min_trades_per_year, max_drawdown_pct).
3. **discovery_loop already partly covers this.** If the goal is autonomous
   experimentation, extending `engine/strategies/discovery_loop.py` with git-commit +
   rollback + search-state patterns may be half the work of grafting n-autoresearch in.

## Architecture

```
   n-autoresearch run_full_cycle.py
               |
               v   HTTP (JSON)
     engine/autoresearch/iii_server.py  (port 3111, FastAPI)
               |
               v   subprocess
     engine/autoresearch/rl_train_adapter.py
               |
               v   (TODO: wire when ready)
     engine/strategies/rl_trainer.py    (existing, 31.9KB)
```

State persists to `engine/autoresearch/experiment_log.json`.

## Files

| File | Purpose |
|---|---|
| `engine/autoresearch/iii_server.py` | FastAPI sidecar on port 3111 — 7 endpoints matching n-autoresearch's API |
| `engine/autoresearch/rl_train_adapter.py` | Subprocess adapter — emits `val_bpb=...` line for run_full_cycle.py |
| `engine/autoresearch/rl_search_space.json` | Ranked hyperparam definitions (11 params) + gameability guards |
| `engine/autoresearch/experiment_log.json` | Persistent state (auto-created) |

## Activation procedure (WHEN READY)

1. Validate composite_score with 2+ weeks of paper trading outcomes.
2. Add min_trades_per_year and drawdown guards to the metric.
3. Start sidecar: `python engine/autoresearch/iii_server.py` (port 3111).
4. Use a git worktree: `git worktree add ../jarvis-autoresearch autoresearch/rl_mes_v1`.
5. Run a single baseline cycle first: `python engine/autoresearch/rl_train_adapter.py --baseline`.
6. Only THEN launch a real sweep via n-autoresearch's run_full_cycle.py.

## Do NOT

- Run `engine/autoresearch/iii_server.py` in production.
- Launch sweeps before paper trading validates the metric.
- Point the adapter at the main branch — always use a worktree.
- Skip the gameability guards.

#### `POST /api/experiment/register`
Register experiment metadata (instrument, epoch, etc.).

**Request:**
```json
{
  "experiment_id": "550e8400-e29b-41d4-a716-446655440000",
  "metadata": {
    "instrument": "MCL",
    "epoch": 42,
    "timeframe": "1h"
  }
}
```

**Response:**
```json
{
  "ok": true
}
```

#### `POST /api/experiment/complete`
Mark experiment complete with final metrics.

**Request:**
```json
{
  "experiment_id": "550e8400-e29b-41d4-a716-446655440000",
  "metrics": {
    "val_bpb": 5.27,
    "sharpe": 4.16,
    "wfe": 0.82,
    "peak_vram_gb": 2.4
  }
}
```

**Response:**
```json
{
  "ok": true
}
```

#### `POST /api/experiment/crash`
Record experiment crash with error trace.

**Request:**
```json
{
  "experiment_id": "550e8400-e29b-41d4-a716-446655440000",
  "error": "CUDA out of memory at step 5000"
}
```

**Response:**
```json
{
  "ok": true
}
```

### Search Coordination

#### `GET /api/search/suggest`
Return the next hyperparam suggestion from the search space.

**Response:**
```json
{
  "name": "learning_rate",
  "value": 0.0003,
  "type": "float",
  "min": 1e-5,
  "max": 1e-3
}
```

#### `POST /api/search/adapt`
Accept experiment result, update internal search state (Bayesian optimizer, etc.).

**Request:**
```json
{
  "experiment_id": "550e8400-e29b-41d4-a716-446655440000",
  "metrics": {
    "val_bpb": 5.27,
    "sharpe": 4.16
  },
  "result": {
    "improved": true
  }
}
```

**Response:**
```json
{
  "ok": true,
  "new_strategy": "bayesian"
}
```

#### `GET /api/search/strategy`
Return current search strategy name.

**Response:**
```json
{
  "strategy": "bayesian"
}
```

## RL Train Adapter Output Format

The `engine/autoresearch/rl_train_adapter.py` script emits a single line to stdout:

```
val_bpb=-0.5000 peak_vram_gb=0.0 mfu=0.0 total_tokens=100000 param_count=42000
```

Fields:
- `val_bpb`: composite validation metric (PF × Sharpe × WFE)
- `peak_vram_gb`: GPU memory usage (placeholder: 0.0)
- `mfu`: model FLOP utilization (placeholder: 0.0)
- `total_tokens`: timesteps from rl_overrides.json
- `param_count`: PPO model parameter count (placeholder)

## Getting Started

### 1. Start the sidecar

```bash
cd C:\Users\mattm\ThinkorSwim\jarvis-trader
uvicorn engine.autoresearch.iii_server:app --port 3111
```

### 2. Configure RL training

Create `engine/rl_overrides.json`:
```json
{
  "total_timesteps": 100000,
  "learning_rate": 0.0003,
  "n_steps": 512,
  "gamma": 0.99
}
```

### 3. Run RL training

```bash
python engine/autoresearch/rl_train_adapter.py
```

## State Persistence

All experiment lifecycle events are appended to `engine/autoresearch/experiment_log.json`:

```json
[
  {
    "experiment_id": "550e8400-e29b-41d4-a716-446655440000",
    "name": "ppo_lr_sweep_mch",
    "config": { ... },
    "metadata": { ... },
    "metrics": { ... },
    "status": "complete",
    "timestamp": "2026-04-10T15:30:00.123456"
  }
]
```

## Not Yet Wired

- **iii_server** integration into main engine (POST requests from RL training loop)
- **Bayesian optimizer** in SearchState (currently returns round-robin suggestions)
- **Dashboard widget** for experiment monitoring (real-time metrics feed)
- **Consensus with debate.py** for conflicting hyperparameter recommendations
- **Historical IC weighting** to adapt search strategy per instrument/timeframe

## Files

| File | Purpose |
|------|---------|
| `engine/autoresearch/__init__.py` | Package marker |
| `engine/autoresearch/iii_server.py` | FastAPI server (7 endpoints) |
| `engine/autoresearch/rl_train_adapter.py` | RL training harness |
| `engine/autoresearch/rl_search_space.json` | Ranked hyperparam definitions |
| `engine/autoresearch/experiment_log.json` | Append-only experiment journal (auto-created on first write) |
