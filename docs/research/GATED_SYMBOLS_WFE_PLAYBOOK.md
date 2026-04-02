# Gated symbols & walk-forward playbook (P4)

**Scope:** Research and validation only. **No** promotion to approved instruments in [CLAUDE.md](../../CLAUDE.md) without WFE evidence and Tier 3. **Do not** edit [`engine/backtest/signals.py`](../../engine/backtest/signals.py) in the same change set as routine features.

## Instruments (status snapshot)

| Symbol | TF | Notes |
|--------|-----|--------|
| **MES** | research | Low WFE in prior runs — use for methodology / stress tests only until new WFE passes threshold. |
| **MGC** | 1d | Halted / overfit — metrics for documentation only unless re-validated. |
| **MCL / MNQ** | 1h | Approved for paper attention per CLAUDE.md. |

## Playbook: new symbol or timeframe

1. **Data** — Ensure bars available in the backtest data pipeline for the symbol/TF.
2. **Walk-forward** — Run [`engine/backtest/run_walk_forward.py`](../../engine/backtest/run_walk_forward.py) (or documented wrapper) and save results under `engine/backtest/results/` as `WF_<SYMBOL>_<tf>_walk_forward.json`.
3. **Evidence** — Record WFE, sample size, and regime breakdown in the session log or a short report.
4. **Promotion** — Update the validated-instruments table in `CLAUDE.md` only after Tier 3 sign-off.
5. **Dashboard** — Optional copy updates in dashboard only after table approval.

## Tier 3 gate

Any canonical signal or risk-parameter change in `signals.py` or production `TradingConfig` tuning requires explicit approval and regression checks on approved symbols (e.g. MCL, MNQ).
