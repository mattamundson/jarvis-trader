# Gated symbols & walk-forward playbook (P4)

**Scope:** Research and validation only. **No** promotion to approved instruments in [CLAUDE.md](../../CLAUDE.md) without WFE evidence and Tier 3. **Do not** edit [`engine/backtest/signals.py`](../../engine/backtest/signals.py) in the same change set as routine features.

## Instruments (status snapshot)

| Symbol | TF | Notes |
|--------|-----|--------|
| **MES** | 1h | **APPROVED** — active paper since Tier-3 flip 2026-05-24 (gate v2 ALT, p_edge 0.75). Supersedes prior low-WFE status. |
| **MGC** | 1h | **APPROVED** — active paper since Tier-3 flip 2026-05-24 (gate v2 ALT, p_edge 0.6842). Supersedes prior 1d halt. |
| **MCL / MNQ** | 1h | **HALTED** (`DO_NOT_TRADE`) — strategy hypotheses exhausted / fail gate v2. |
| **M2K** | 1h | **REJECTED** — SMA/ORB/Donchian rank-1 all FAIL 2026-05-24. |

## Playbook: new symbol or timeframe

1. **Data** — Ensure bars available in the backtest data pipeline for the symbol/TF.
2. **Walk-forward** — Run [`engine/backtest/run_walk_forward.py`](../../engine/backtest/run_walk_forward.py) (or documented wrapper) and save results under `engine/backtest/results/` as `WF_<SYMBOL>_<tf>_walk_forward.json`.
3. **Evidence** — Record WFE, sample size, and regime breakdown in the session log or a short report.
4. **Promotion** — Update the validated-instruments table in `CLAUDE.md` only after Tier 3 sign-off.
5. **Dashboard** — Optional copy updates in dashboard only after table approval.

## Tier 3 gate

Any canonical signal or risk-parameter change in `signals.py` or production `TradingConfig` tuning requires explicit approval and regression checks on approved symbols (e.g. MCL, MNQ).
