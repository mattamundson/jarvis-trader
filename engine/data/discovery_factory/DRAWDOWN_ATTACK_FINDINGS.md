# Drawdown-Attack Findings — converting the intraday trend near-miss

**Branch:** `feat/discovery-factory` (worktree `jt-config-authority`, local/unpushed;
merge to live `feat/family-fdr-campaign` is Amo's call).
**Question:** can the prime non-blocked near-miss `MGC_sma_trend_5m` be converted to a
gate-v2 ALT PASS by (a) restricting to the robust profitable sub-grid and (b) sizing down
to a drawdown budget — without destroying the edge?
**Answer:** **No robust PASS.** One size threads the gate (`dd_mid` @0.0035), but it is a
**knife-edge artifact**, not a deployable edge. Honest negative on trend. The clean lead is
now donchian (separate band test, below).

## Baseline (the near-miss being attacked)

`MGC_sma_trend_5m` @ risk 0.01, full intraday grid (fast{8,12,16}×slow{24,48}×atr{2,2.5}):

| metric | value | ALT need | clears? |
|---|---|---|---|
| verdict | **FAIL** | | |
| pf_ci_lower | 1.2545 | — | |
| p_edge | 0.8333 | (CORE only, ≥0.95) | ✗ → CORE impossible, ALT is the only path |
| dsr | 0.7916 | ≥0.30 | ✓ |
| **fixed_params_min_pf** | **0.000** | ≥1.20 | ✗ |
| **mc_95th_dd** | **5.77%** | ≤4% | ✗ |
| wfo_consistency | STRONG | MODERATE/STRONG | ✓ |
| total_oos_trades | 388 | ≥30 | ✓ |

Two ALT failures: `fixed_params_min_pf=0` (some grid combo is unprofitable on the full
dataset) and `mc_95th_dd=5.77%`.

## Lever 1 — robust sub-grid fixes `fixed_params_min_pf` (confirmed)

Diagnostic (2026-06-24, full-data PF per combo): every `slow=24` combo whipsaws on 5m
(PF 0.00–0.19); every `slow∈{48,72}` combo is profitable (PF 1.49–2.52). Restricting the
grid to `fast{12,16,20}×slow{48,72}×atr{1.5,2,2.5}` is a **genuine robustness improvement**
(drops the whipsaw region that also dragged baseline p_edge down), not cherry-picking a
single combo. Result: `fixed_params_min_pf` 0.000 → **1.51** at every size below. ✓ cleared.

## Lever 2 — sizing attacks `mc_95th_dd`, but the breaker couples size → dsr

`mc_95th_dd` (drawdown %) is sizing-dependent; pf/p_edge are scale-invariant ratios — so
sizing down *should* fit a drawdown budget without touching the edge. It half-works. The
`max_drawdown=0.05` Backtester breaker makes the **per-window champion selection** (and the
realized return path, hence **dsr**) discontinuous in size. So dsr is **NOT** scale-invariant
in practice. Robust-grid trend across the size sweep:

| spec | risk | mc_95th_dd | dsr | fixed_min_pf | pf_lo | wfo | trades | champion | verdict |
|---|---|---|---|---|---|---|---|---|---|
| `dd_5m` | 0.005 | 5.42% ✗ | 0.398 ✓ | 1.513 | 1.329 | MOD | 503 | atr1.5/f12/s48 | FAIL (DD) |
| **`dd_mid_5m`** | **0.0035** | **3.997% ✓** | **0.9999 ✓** | **1.525** | **1.385** | **STRONG** | **525** | **atr1.5/f12/s48** | **PASS (ALT)** |
| `dd_lo_5m` | 0.0025 | 2.23% ✓ | 0.000 ✗ | 1.362 | 1.245 | STRONG | 350 | atr2.5/f16/s72 | FAIL (dsr) |
| `dd_15m` | 0.005 | 2.14% ✓ | 0.000 ✗ | 1.252 | 1.007 | MOD | 140 | atr2.5/f12/s72 | FAIL (dsr) |

## Why the `dd_mid` PASS is a knife-edge artifact, not an edge

The PASS is real per the gate, but it must not be treated as a deployable candidate:

1. **Only the middle of three sizes passes.** Its neighbors (0.005 and 0.0025) both FAIL.
   A pass that exists at exactly one tuned risk value, bracketed by failures, is the gate
   being *threaded by parameter search*, not an edge that is present across reasonable
   sizing.
2. **dsr is wildly non-monotonic in size: 0.398 → 0.9999 → 0.000** across 0.005/0.0035/0.0025.
   Decisive detail: `dd_5m`@0.005 and `dd_mid`@0.0035 select the **identical champion**
   (atr1.5/fast12/slow48), yet dsr is 0.40 vs 1.0 — pure path-dependence through the breaker.
   At 0.0025 the champion *flips* (atr2.5/fast16/slow72) and dsr collapses to 0. The metric
   driving the PASS is hypersensitive to the one parameter that was tuned to produce it.
3. **The DD margin is razor-thin: 3.997% vs the 4.00% ceiling** — 0.003% of headroom. A
   coin-flip from failing; not a result you size a live account on.

**Verdict on trend:** the ~5% intraday-trend drawdown wall is structural (the RV-filter
refutation already showed it isn't a low-vol false-signal artifact). Sizing can move the
drawdown number under the ceiling, but doing so destabilizes dsr via the breaker, so no
size delivers a *robust* ALT pass. `dd_mid` is a fragile artifact. **Do not promote.**

## Methodology upshot (the real deliverable)

A near-miss that fails ONLY on `mc_95th_dd` is a **risk-budget** question, not an edge
question — drawdown% is just sizing. The honest test of whether sizing-to-budget yields a
*genuine* candidate is whether the ALT pass holds **across a band of sizes**, not at one
knife-edge point. A point-pass with non-monotonic dsr is gate-threading; a band-pass with a
stable champion and dsr is a real candidate (still human-promotion-gated). This standard is
what the donchian band test below applies.

## Donchian band — the cleaner lead (PENDING, sweep running)

`MGC_donchian_15m` is the cleanest non-blocked near-miss surfaced so far. At risk 0.01 it
fails ALT on **EXACTLY ONE** condition — `mc_95th_dd=5.55%` — while every edge metric clears
with margin:

| metric | value | ALT need | clears? |
|---|---|---|---|
| verdict | FAIL (DD only) | | |
| pf_ci_lower | 1.5334 | — | |
| dsr | **1.000** | ≥0.30 | ✓ (huge headroom) |
| fixed_params_min_pf | **2.379** | ≥1.20 | ✓ (every combo profitable; no grid surgery) |
| wfo_consistency | MODERATE | MOD/STRONG | ✓ |
| mc_95th_dd | 5.55% | ≤4% | ✗ (the only miss) |
| total_oos_trades | 243 | ≥30 | ✓ |

Because dsr=1.0 and fixed_min_pf=2.38 are *already* robust (unlike trend, which needed grid
surgery and had a fragile dsr), this is the setup where sizing-to-budget could yield a real
pass. Band test (`donchian_dd_lo`/`donchian_dd`/`donchian_dd_hi` @ 0.004/0.005/0.006 — all
put 5.55% baseline DD comfortably <4%): **does the ALT PASS hold across the whole band?**
Holds across the band → genuine candidate at reduced size. Holds at a point only → another
artifact. Results to be appended when the sweep completes.

_Safety: the factory writes `data/discovery_factory/`, never `gate_v2_verdicts/`. No
candidate can self-authorize trading; promotion to live is a human decision._
