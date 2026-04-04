---
paths:
  - "engine/backtest/signals.py"
  - "engine/backtest/composite_signals.py"
  - "engine/strategies/rl_agent.py"
  - "engine/strategies/rl_environment.py"
  - "engine/strategies/rl_trainer.py"
---

# Backtest & Signals Rules

## Signal Parameters — TIER 3 TO CHANGE

These are CANONICAL values. Never change without explicit Tier 3 confirmation AND a backtest re-run:

| Parameter | Value |
|-----------|-------|
| STC Oversold (OS) | 15 |
| STC Overbought (OB) | 83 |
| ATR Stop multiplier | 0.70x |
| ATR Target (T1) multiplier | 1.50x |
| Regime Filter | ON |

**Daily timeframe**: OS=23, OB=83, Stop=0.70x, T1=2.00x (different from 1h)

## WFE Requirements

Any parameter change requires a new walk-forward evaluation:
- WFE ≥ 0.5 → can approve for paper trading
- WFE < 0.2 → HALT — do not trade

Current approvals: MCL (0.82), MNQ (0.57). DO NOT TRADE: MES (0.09), MGC (0.14).

## RL Agent Rules

- RL is EXPERIMENTAL — MES only, never route RL signals to real orders
- `rl_config.py` contains experiment history (Run 1–11) — preserve comments as research log
- Max episode bars = 500 (engine constraint)
- 19 features from signals.py (never add features without updating rl_environment.py)

## Backtest Conventions

- Results JSON must be saved to `engine/backtest/results/`
- Always record: symbol, TF, period, trades, win_rate, PF, Sharpe, return, max_DD, WFE
- Never delete historical results — append new runs
- Run optimizer only on OOS data (2025 is held-out test set)
