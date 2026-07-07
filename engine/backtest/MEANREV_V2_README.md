# Mean-Reversion v2 — Structural Rewrite

**Status:** New candidate strategy family (not a replacement for v1 while both are being tested).
**Companion audit:** `docs/audits/meanrev_audit.md`

## Why v2 exists

v1 mean-reversion strategies (MES/MGC/MCL) all failed gate_v2 with a shared pattern:
- p_edge below 0.50 (worse than coin-flip on direction)
- DSR = 0 (Sharpe deflates to zero)
- Losses systemic across parameter grid (mean_pf ~0.83 across all combos)

v2 addresses three structural failures identified in the audit:

| Failure (v1) | Fix (v2) |
|---|---|
| Static 2σ Bollinger trigger assumes stationary vol | Rolling 95th-percentile dislocation trigger — auto-recalibrates to vol regime |
| Fixed 1.5×ATR(14) stop too tight in vol expansion | `max(short-window ATR, 75th-pct of long-window ATR)` + time stop + trail-to-BE |
| No cluster-loss circuit breaker | Rolling-5 P&L breaker + 3-consecutive-stops + daily loss cap |
| OU module exists but unused | OU half-life filter or OU z-score trigger (pure OU mode) |

## Files

- `meanrev_v2_signals.py` — signal generator (23kb, 594 lines). Uses existing meanrev_ou.py module.
- `run_mes_meanrev_v2_rank1.py` — MES runner shell, 12-combo grid
- `run_mgc_meanrev_v2_rank1.py` — MGC runner shell, 8-combo grid (focuses on OU mode)
- `../tests/test_meanrev_v2_signals.py` — 15 tests, 14 pass + 1 skip (regime-detection needs more synthetic data)

## Integration status

Runners are **shells** — the WFO orchestration lives in the v1 runners.
To run end-to-end, either:

1. Refactor v1's WFO mechanics into `wfo_primitives.run_wfo(signal_fn, grid, ...)` and use it in both, OR
2. Copy the v1 WFO loop into each v2 runner and swap `generate_bollinger_rsi_signals()` for the v2 factory.

Recommended: option 1. It's a one-time refactor that makes v1/v2 comparisons apples-to-apples going forward.

## Contract

Signal generator output columns match v1 exactly (see `meanrev_signals.py`).
Additional v2 diagnostic columns:
- `dislocation_percentile` — trailing rank of current dislocation
- `stop_vol_regime` — "high" or "normal" (which ATR window drove stop sizing)
- `time_stop_bars_remaining` — countdown for time-stop exit
- `circuit_breaker_active` — bool, entries blocked when true
- `ou_theta`, `ou_mu`, `ou_half_life`, `ou_z` — OU diagnostics
