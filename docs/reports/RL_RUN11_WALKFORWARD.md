# RL Run 11 and walk-forward (experimental)

## Purpose

Track **Run 11** PPO training and **8-window walk-forward** gate evaluation without wiring RL into the live LLM pipeline.

## Commands (from `engine/`)

```bash
# Train (adjust symbol / timesteps in body or use defaults)
.venv\Scripts\python -c "import asyncio; ..."   # prefer POST /strategies/rl/train via dashboard or curl

# Walk-forward batch
# POST /strategies/rl/train-walkforward  JSON: symbol, timesteps_per_window, n_windows (see strategies_router)
```

## Gate

- Use existing validation gates in `rl_config` / evaluator output (`passes_validation`, window pass rate). Do not promote to production pipeline until gates pass in repeated runs.

## Artifacts

- Store metrics summaries under `docs/reports/` or locally; large binaries should stay out of git unless policy changes.
