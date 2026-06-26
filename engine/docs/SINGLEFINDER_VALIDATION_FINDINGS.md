# Singlefinder validation findings — `MGC_singlefinder_fill_rank1` (2026-06-23)

**Status: the one live edge-validation candidate. Survives all three cheap falsifiers
(window-independence, parameter-sensitivity, cost/leakage) — but is NOT yet certified for
live capital.** It passes gate-v2 only via the ALT path; the core path FAILs on
`pf_ci_lower = 1.05 < 1.10`. The edge is real but *marginal*, and the gap to robustness is
**data depth** (more independent OOS windows), not strategy quality.

This note is the evidence package for the eventual live-capital promotion decision
(top-10 Tasks 8/10). Companion: the trend-family dead-end is documented in
`DISCOVERY_RV_TREND_FINDINGS.md`.

## What it is

Corey "single-print magnet" intraday strategy on MGC 5m (RTH, EOD exit, one entry/session).
Unfilled single-print zones from the **prior** session act as magnets; price tends to fill
them. Champion params: `min_single_ticks=2, mode=fill`. Signal source
`backtest/studies/singlefinder_signals.py`; verdict `data/gate_v2_verdicts/MGC_singlefinder_fill_rank1.json`.

Gate-v2 (ALT PASS): pf_ci_lower 1.05, p_edge 0.714, mc_95th_dd 3.59%, dsr 1.0, wfo_consistency
MODERATE, fixed_params_min_pf 1.415, cost_survives_through pessimistic. 381 OOS trades over 7
non-overlapping windows (56–64/window, last 19).

## Task 1 — window independence  ✓ (the path is viable for THIS candidate)

7 sequential WFO windows, step=test=3mo → **0% OOS overlap**. Lag-1 autocorrelation of the
per-window OOS PF series = **0.108** (near-zero → effectively independent). N_eff(ar1) ≈ 5.6
vs nominal 7 — a modest haircut, not a collapse. **Zero thin windows** (all ≥19 trades). This
is the only one of the 4 gate-v2 "PASS" candidates whose window count is honest — the trend
variants (N=19) are 50%-overlapping and degenerate (see `DISCOVERY_RV_TREND_FINDINGS.md` /
the window-independence audit). → deepening via more windows (Task 9) is worth doing here.

Tool: `engine/backtest/window_independence_audit.py`.

## Task 2 — parameter sensitivity  ✓ ROBUST

Sweep the one knob `min_single_ticks` ∈ {1..6} on the full dataset (realistic cost):

| ticks | PF | trades | WR% | vs champion |
|---|---|---|---|---|
| 1 | 1.462 | 512 | 22.3 | −1.3% |
| **2** | **1.481** | **511** | **21.9** | **champion** |
| 3 | 1.415 | 511 | 20.9 | −4.5% |
| 4 | 1.395 | 507 | 20.9 | −5.8% |
| 5 | 1.398 | 502 | 20.5 | −5.6% |
| 6 | 1.385 | 489 | 19.8 | −6.5% |

Stability **97.6/100 → ROBUST**. The edge is smooth and positive across the whole neighborhood
— it does not depend on the exact threshold. The champion run reproduces the gate's
`pf=1.481 / 511 trades` exactly (harness is faithful).

Sub-period stability (7 OOS windows): PF `[1.374, 0.766, 1.184, 1.383, 2.065, 1.757, 0.738]`,
p_edge 5/7 = 0.714, stability **66/100 (ACCEPTABLE)** — broad across time, two losing windows,
not concentrated in one spike.

Tool: `engine/backtest/singlefinder_sensitivity.py` (reuses the generalized
`sweep_param_sensitivity` core in `sensitivity.py`).

## Task 3 — cost realism + look-ahead / leakage  ✓ SURVIVES

**Leakage: CLEAN.** Three independent guards:
1. Zones come from session **D-1** (`singlefinder_signals.py:64` `.shift(1)`) — no within-session
   look-ahead on the levels (the raw same-session columns are never used for entry).
2. Entry signal fires on bar *i*'s close but is stored as `pending_entry` and filled at
   **bar i+1's open** (`backtester.py:182`, the "Bug 3" fix); stop/targets recomputed off the
   actual fill price. No same-bar fill leak.
3. ATR used for the stop is the signal-bar value (known at decision time).

**Cost: ROBUST (not cost-killed).** Erosion curve for the champion, full dataset:

| comm× | slip ticks | PF | trades |
|---|---|---|---|
| 1× ($0.85) | 0 | 1.512 | 511 |
| 1× | 1 (modeled) | 1.481 | 511 |
| 1× | 2 | 1.360 | 511 |
| 1× | 3 | 1.298 | 511 |
| 1× | 4 | 1.247 | 511 |
| 1× | 5 | 1.232 | 511 |
| 1× | 6 | 0.625 | 259† |
| 2× ($1.70) | 2 | 1.360 | 511 |
| 2× | 3 | 0.690 | 255† |

†The collapse is the **−5% max-drawdown kill switch** truncating the sample, not a clean
PF→1.0 crossing. Below that threshold the edge degrades gracefully and holds PF>1.2 out to ~5
ticks of slippage at realistic commission — a 4–5× buffer over the modeled 1 tick on a liquid
micro (MGC tick = $1; realistic fills ≤1 tick). A randomized per-fill MC adds little given that
margin.

## What's left before this is live-capital eligible

1. **Cross the core gate or strengthen the ALT case via more independent windows** (Task 9).
   pf_ci_lower 1.05 → ≥1.10 needs either deeper MGC 5m history (IB backfill, Amo-gated) or
   cross-symbol pooling of the same family. Task 1 confirmed the windows are independent, so more
   windows genuinely tighten the CI rather than double-counting.
2. **Per-window adequacy enforcement** (Tasks 5/8) — fine here (no thin windows), but the gate
   should make that explicit so this candidate's honesty is machine-checked, not eyeballed.
3. **Forward paper shadow dry-run** (Task 10) — run live-data paper vs backtest expectation before
   any capital. WR ~21% (low-win / high-R / tail-dependent) means live slippage discipline and the
   kill switch matter more than for a high-WR strategy.

**Bottom line:** singlefinder is the only candidate that has earned the downstream
infrastructure. It is a *marginal but real and honest* edge — keep it alive, deepen its sample,
and forward-validate before risking capital.
