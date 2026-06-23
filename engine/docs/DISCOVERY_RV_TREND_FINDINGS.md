# Discovery findings — MGC 1h RV regime-filtered trend (2026-06-23)

**Verdict: do NOT promote. The gate-v2 rejection is correct, not a threshold-tuning
problem.** MGC 1h trend has a real directional edge (PF 1.6–1.8 walk-forward, ~1%
drawdown) but is not robust enough to certify on the ~26 months of 1h micro history
that exists. Three independent levers were tested; each is refuted below. The binding
constraint is **data/sample size**, not strategy parameters.

This note exists so future discovery work does not re-chase this dead end. It also
records a **meta-finding** about which gate path trend families can realistically target.

## Context

Base MGC 1h `sma_trend` FAILs gate-v2 ONLY on `p_edge` (0.53 — barely half of OOS
windows profitable) and WEAK consistency; PF-CI (1.45), DSR (1.0), drawdown (1.98%)
all pass. That failure mode (inconsistent edge across regimes) is exactly what a
realized-vol regime filter targets, so the `sma_trend_rv` family was added
(`min_rv_annualized` gate — the mechanism behind the live MGC `trend_rv_filter`).

The RV filter **improved every robustness metric** vs base (pf_ci 1.45→1.84,
p_edge 0.53→0.67, drawdown 1.98%→0.92%, consistency WEAK→MODERATE,
fixed_params_min_pf 0.08→0.83) on 33 OOS trades — the closest-to-PASS candidate of
the whole discovery effort, but still FAIL. This note investigates whether any honest
refinement closes the gap.

## Three levers, all refuted

### 1. Higher RV floor — does NOT lift `fixed_params_min_pf` ≥ 1.20

Per-combo full-data PF across the fast/slow grid (realistic cost), by RV floor:

| RV floor | minPF | meanPF | maxPF | trades |
|---|---|---|---|---|
| 0 / 6 (no-op*) | 0.09 | 1.53 | 2.55 | 327 |
| 9 | 0.97 | 1.67 | 2.66 | 313 |
| 12 | 0.83 | 1.88 | 3.98 | 224 |
| 15 | **1.04** | 1.79 | 3.03 | 173 |
| 18 | 0.31 | 1.98 | 3.40 | 114 |

`minPF` (the ALT-gate input) peaks at rv=15 (1.04) then collapses at rv=18 (sample
starvation) and **never reaches the 1.20 ALT threshold**. *rv=0 and rv=6 are identical
→ MGC 1h realized-vol is essentially never below 6% annualized, so a 6% floor is a no-op.

### 2. Grid narrowing to the medium-trend corner — fixes minPF but breaks DSR

The worst combos are always `fast=40` (whipsaw) and `slow=200` (laggiest MA). Restricting
to `fast∈{50,60}, slow∈{120,150}` clears minPF ≥ 1.20 at every RV level (even no-filter:
minPF 1.79). But running that focused grid through the real gate:

```
VERDICT: FAIL
  fixed_params_min_pf  0.83 -> 1.70   ✓ (narrowing fixed it)
  dsr                  1.0  -> 0.0    ✗ (narrowing BROKE it)
```

This is overfitting whack-a-mole: narrowing to fix one robustness metric shifts the
champion (to rv=15/slow=120) and breaks another — DSR's trial-deflation penalizes a
12-combo search over a noisy 38-trade sample. The narrowing is also **post-hoc** (pruning
combos *after* seeing them fail), which is precisely what `fixed_params_min_pf` deters.

### 3. Longer test windows — raises trades/window but p_edge plateaus, minPF invariant

Wide grid, varying only `test_months` (a legitimate a-priori knob, not grid pruning):

| test_mo | verdict | pf_ci | p_edge | dsr | minPF | OOS trades |
|---|---|---|---|---|---|---|
| 2 | FAIL | 1.84 | 0.67 | 1.0 | 0.83 | 33 |
| 3 | FAIL | 1.68 | **0.72** | 1.0 | 0.83 | 53 |
| 4 | FAIL | 1.61 | 0.63 | **0.0** | 0.83 | 70 |

More trades/window (33→70) nudges p_edge but it **plateaus ~0.72, far below the 0.95
core floor**; `fixed_params_min_pf` is **invariant at 0.83** (a full-data metric —
windowing cannot touch it); DSR collapses at test=4 (fewer windows).

## Root cause and why the gate is correct

The two gate paths are blocked by structurally different, non-co-satisfiable deficits:

- **Core path** needs `p_edge ≥ 0.95`. A trend-following strategy's per-window win rate
  caps around 65–72% — a STRUCTURAL property of trend (frequent small drawdown periods),
  not a sample artifact. **Core p_edge ≥ 0.95 is unreachable in principle for trend
  families.**
- **ALT path** needs `fixed_params_min_pf ≥ 1.20` (worst-combo robustness) AND `dsr ≥ 0.30`
  simultaneously. The wide grid fails minPF (0.83); narrowing fixes minPF but breaks DSR.
  They cannot both hold because the edge is **corner-concentrated** AND the sample is
  **thin** (~1.9–3.5 OOS trades/window).

A genuinely robust edge satisfies all gate metrics at once; an overfit-prone edge can
only satisfy them one at a time as the grid is twisted. The gate is working as designed.

## Meta-finding (applies to all future discovery)

**Trend families must target the ALT path; the core path's `p_edge ≥ 0.95` is structurally
unreachable for trend-following.** Families that win small-and-often (mean-reversion,
some breakout) are the candidates with a shot at core `p_edge`. Route discovery accordingly.

## Recommendations

1. **Do not promote MGC 1h RV-trend.** No threshold is "almost there" — the failures are
   structural and migrate when pushed.
2. **The RV filter is validated** as a robustness *improver* (why the live MGC strategy
   uses it) — but it improves quality, not certifiability on this sample.
3. **The only real fixes add data/trades, not parameters:**
   - **(a) Time** — 1h micro history grows ~1 month per calendar month (capped at ~26mo of
     free IB depth today). Revisit in ~12–18 months when ~40mo yields ~30 windows.
   - **(b) Cross-symbol pooling — most promising NEW direction.** Test "high-RV trend" as a
     factor across MES+MGC+MNQ pooled: ~3× the trades and more windows could stabilize
     DSR/consistency while preserving the corner robustness. Single-symbol fits are
     starved; a pooled factor may not be.
   - **(c) Discretionary overlay** — the directional edge is real; trade it human-supervised
     in high-RV regimes rather than as a gated auto-strategy.

## Reproduce

- Wide-grid spec: `MGC sma_trend_rv 1h` in `default_registry()`
  (`fast=[50,60], slow=[120,200], atr_trail_mult=[2.0], min_rv_annualized=[6,9,12]`).
- Per-combo + focused-corner + longer-window probes were run via the factory machinery
  (`run_spec` on ad-hoc `StrategySpec`s) against the main repo's 1h cache. Research only;
  no writes to `gate_v2_verdicts/`.
