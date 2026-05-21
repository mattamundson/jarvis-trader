# RL Strategy Discovery Runbook

## What it is

The RL strategy discovery pipeline uses Proximal Policy Optimization (PPO) to
autonomously discover trading policies from historical OHLCV data.  It is the
**orthogonal path** to the LLM-driven ResearchAgent — both paths produce
`StrategyHypothesis` objects that feed gate v2 for validation.

**This is a training-time tool only.** It does not route live orders, does not
call `engine/risk/`, and does not modify `engine/config.py`.  Policies are
saved to `engine/data/rl_policies/` and hypotheses to
`engine/data/research_hypotheses/<date>/`.  The live pipeline is not aware of
this module unless a hypothesis passes gate v2 and is promoted by the human
operator.

Key modules:

| File | Purpose |
|---|---|
| `engine/strategies/rl_env.py` | `TradingEnvMES` alias + `make_trading_env()` factory |
| `engine/strategies/rl_train.py` | `train_ppo()` + `policy_to_hypothesis()` |
| `engine/strategies/rl_environment.py` | Core `TradingEnvironment` (23-feature gymnasium env) |
| `engine/strategies/rl_agent.py` | `RLTradingAgent` PPO wrapper (safety contract on predict()) |
| `engine/strategies/rl_trainer.py` | `RLTrainer` async orchestrator + walk-forward |
| `engine/strategies/rl_config.py` | All constants, hyperparams, action space, reward config |
| `scripts/run_rl_strategy_discovery.py` | CLI entry point |

Cross-links:
- `[[KRONOS_AND_RESEARCH_AGENT_RUNBOOK]]` — LLM hypothesis path (parallel to this)
- `[[STARK_MODE_OPERATING_PHILOSOPHY]]` — how candidates are routed to paper trading

---

## Default state: OFF

The feature is gated behind `ENABLE_RL_STRATEGY_DISCOVERY=0` in `engine/.env`.
This flag is checked at call time inside `train_ppo()` and `policy_to_hypothesis()`.
The engine boots clean even if `stable-baselines3` is not installed because all
SB3 imports are lazy (inside function bodies, never at module level).

---

## How to enable and run

### 1. Install prerequisites

```powershell
cd C:\Users\mattm\ThinkorSwim\jarvis-trader
engine\.venv\Scripts\pip install stable-baselines3 gymnasium
```

Verify:
```powershell
engine\.venv\Scripts\python -c "from stable_baselines3 import PPO; print('SB3 OK')"
```

### 2. Set the feature flag

Add to `engine/.env`:
```
ENABLE_RL_STRATEGY_DISCOVERY=1
```

### 3. Run smoke test (CPU-friendly, ~10 seconds)

```powershell
cd C:\Users\mattm\ThinkorSwim\jarvis-trader
engine\.venv\Scripts\python scripts\run_rl_strategy_discovery.py --quick-smoke
```

This runs 100 training steps on **synthetic data** (no Polygon API, no DB) and:
- Writes a policy zip to `engine/data/rl_policies/MES-<timestamp>.zip`
- Converts it to a `StrategyHypothesis` JSON in `engine/data/research_hypotheses/<date>/`
- Prints training metrics to stdout

Expected output (abridged):
```
10:00:00 [INFO] rl_discovery — Starting | symbol=MES n_steps=10000 quick_smoke=True
10:00:02 [INFO] rl_discovery — Training complete | steps=100 mean_reward=... time=1.4s
10:00:02 [INFO] rl_discovery — Policy saved: .../MES-20260520_100000.zip
10:00:03 [INFO] rl_discovery — Hypothesis generated | name=rl-mes-... confidence=0.00
```

### 4. Run full training (real data, GPU recommended)

```powershell
engine\.venv\Scripts\python scripts\run_rl_strategy_discovery.py `
    --symbol MES `
    --n-steps 500000 `
    --force-enable
```

`--force-enable` sets the env var in-process without editing `.env` — useful
for one-off runs.  `--symbol` supports any symbol in `rl_config.RL_INSTRUMENT_PARAMS`.

---

## GPU considerations

This machine has no dedicated GPU.  CPU training is supported but is
approximately **10-20x slower** than on a CUDA-capable GPU:

| Mode | Estimated time (500k steps, MES 1h) |
|---|---|
| CPU (this machine) | 45-120 minutes |
| GPU (CUDA, RTX 3080) | 5-10 minutes |

Practical recommendation: use 10,000-50,000 steps for exploratory runs on CPU;
reserve 500,000+ steps for GPU-enabled machines or cloud instances.

The walk-forward trainer (`RLTrainer.train_walkforward`) runs multiple windows
sequentially — multiply the per-run estimate by the number of windows.

---

## Cron suggestion

Run weekly on a single instrument.  Example Windows Scheduled Task:

```powershell
schtasks.exe /Create /SC WEEKLY /D SUN /TN "Jarvis-RLDiscovery-MES" `
  /TR "\"engine\.venv\Scripts\python\" \"scripts\run_rl_strategy_discovery.py\" --symbol MES --n-steps 50000 --force-enable" `
  /ST 06:00 /RL LIMITED
```

The best policy from each Sunday run feeds the hypothesis backlog.  Operators
review hypotheses weekly; those passing gate v2 are promoted to the paper-trading
candidate list via the standard instrument onboarding flow
(`docs/runbooks/INSTRUMENT_ONBOARDING.md`).

---

## How policies become live candidates

```
PPO training
    |
    v
train_ppo() saves <symbol>-<ts>.zip
    |
    v
policy_to_hypothesis() converts to StrategyHypothesis
    |
    v
Hypothesis JSON saved to engine/data/research_hypotheses/<date>/
    |
    v
(Operator reviews) gate v2 backtest via strategy_tuner.py
    |
    v  [pf_ci_lower >= 1.10, p_edge >= 0.95, mc_95th_dd <= 5%, dsr >= 0.10]
    v  [all gates PASS]
    |
    v
Paper-trading candidate queue
```

Gate v2 thresholds are unchanged from the ResearchAgent path — the RL origin
of the hypothesis is transparent to the gate.

---

## Validation gates (RL-specific, in `rl_config.VALIDATION_GATES`)

Before a walk-forward window is marked PASS:

| Gate | Threshold |
|---|---|
| Profit factor | >= 2.0 |
| Sharpe ratio | >= 1.5 |
| Win rate | >= 55% |
| Minimum trades | >= 60 |
| Hold rate | >= 50% |
| Max drawdown | <= 15% |

These are **in-sample / OOS gates at the RL training level** — they must pass
before a hypothesis is even generated.  Gate v2 thresholds are then applied on
top.

---

## Known limitations

### Overfitting to a specific regime

PPO maximizes expected reward in the training distribution.  If training data
covers only a bull market (e.g. 2023-2024 MES), the policy will overfit to
long-biased setups.  The walk-forward trainer (`RLTrainer.train_walkforward`)
mitigates this by training on rolling windows, but does not eliminate regime
overfitting.

Mitigation: always check `wfe` (Walk-Forward Efficiency = OOS_PF / IS_PF) in
the walk-forward result.  A WFE < 0.5 indicates strong overfitting.

### Lack of out-of-sample validation in the environment

`TradingEnvironment` uses random window sampling during training
(`max_episode_bars=500`), which creates diverse episodes — but all windows come
from the same historical period.  A policy trained on 2022-2025 MES data has no
guarantee of generalizing to 2026.

Mitigation: use `RLTrainer.train_symbol()` with a proper train/test split
(`TEST_LOOKBACK_DAYS = 180` in `rl_config.py`).  The OOS test period must be
sealed before training starts.  Evaluating the policy on data it never saw
(even indirectly via reward) is the only real out-of-sample guard.

### Action-distribution bias

`policy_to_hypothesis()` derives `signal_weights` from the policy's action
distribution over a 100-step rollout on **synthetic data**.  This is an
approximation — the rollout environment does not match the training environment.
The resulting hypothesis rules are heuristic descriptions, not precise encodings
of the learned policy.

Mitigation: treat the hypothesis text as a starting point for human review, not
as an exact strategy specification.  Gate v2 evaluates the backtested metrics,
not the text.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `RuntimeError: RL strategy discovery is disabled` | Feature flag not set | Add `ENABLE_RL_STRATEGY_DISCOVERY=1` to `engine/.env` or use `--force-enable` |
| `ImportError: stable-baselines3 is required` | SB3 not installed | `engine\.venv\Scripts\pip install stable-baselines3` |
| `ValueError: DataFrame too small for training` | Fewer than 60 bars | Increase lookback or use `--quick-smoke` which uses synthetic data |
| Training completes but policy never saves | Permissions on `engine/data/rl_policies/` | `mkdir engine\data\rl_policies` manually |
| `hypothesis.confidence` always 0.0 | Expected — gate v2 sets confidence post-backtest | Normal behaviour |
| Walk-forward all windows FAIL | Training timesteps too low, or data too noisy | Increase `--n-steps` to 200k+; check WFE |

---

## Related files

- `engine/strategies/rl_config.py` — run history (Runs 1-11), hyperparameter rationale
- `engine/strategies/rl_environment.py` — 23-feature observation space definition
- `engine/.env.example` — feature flag documentation
- `engine/tests/test_rl_strategy.py` — smoke tests for rl_env + rl_train
- `engine/tests/test_rl_module.py` — deeper environment + agent tests
- `docs/runbooks/KRONOS_AND_RESEARCH_AGENT_RUNBOOK.md` — LLM hypothesis path
- `docs/runbooks/STARK_MODE_OPERATING_PHILOSOPHY.md` — routing philosophy
