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

Current status — authoritative source is `engine/CLAUDE.md` "Active Instruments"
(update that table, not this line):

- APPROVED, paper active: **MES** (Tier-3 auth 2026-05-24, p_edge 0.75); **MGC**
  (reauthorized 2026-08-10, PR #598, fresh honest gate-v2 CORE PASS, DSR 0.9952 —
  NOT the invalidated 2026-05-24 p_edge=0.68 figure, which no longer applies)
- HALTED, in `DO_NOT_TRADE_SYMBOLS`: **MCL**, **MNQ**, **M2K**
- REJECTED (separately from the blocklist above): **SPY** — see `engine/CLAUDE.md`
  "Active Instruments" for why it (and QQQ/AAPL/TSLA) trade anyway as equities

Note: MES/MGC were validated via the gate-v2 rolling walk-forward (p_edge / DSR),
which superseded the older single-number WFE figures once quoted here (the prior
"MCL 0.82 / MNQ 0.57 approved, MES/MGC do-not-trade" line was stale and inverted).

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
