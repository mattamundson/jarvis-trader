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
surgery and had a fragile dsr), this looked like the setup where sizing-to-budget could yield
a real pass. Band test (`donchian_dd_lo`/`donchian_dd`/`donchian_dd_hi` @ 0.004/0.005/0.006).

### Band result — REFUTED (no point passes; same breaker coupling as trend)

| spec | risk | mc_95th_dd | dsr | fixed_min_pf | pf_lo | wfo | trades | champion | verdict |
|---|---|---|---|---|---|---|---|---|---|
| baseline | 0.010 | 5.55% ✗ | 1.000 ✓ | 2.379 | 1.533 | MOD | 243 | le40/lx10/atr2.5 | FAIL (DD) |
| `dd_lo` | 0.004 | 2.60% ✓ | **0.000 ✗** | 1.674 | 1.381 | STRONG | 211 | le40/lx10/atr2.5 | FAIL (dsr) |
| `dd` | 0.005 | 4.05% ✗ | **0.000 ✗** | 1.756 | 1.350 | MOD | 247 | le20/lx10/atr2.5 | FAIL (dsr+DD) |
| `dd_hi` | 0.006 | 4.17% ✗ | 0.9999 ✓ | 1.892 | 1.459 | MOD | 282 | le40/lx10/atr2.0 | FAIL (DD) |

**No band point passes**, and the metrics are chaotic — the opposite of a robust edge:
- **dsr is non-monotonic in size: 1.0 → 0.0 → 0.0 → 1.0** across 0.010/0.004/0.005/0.006.
- **mc_95th_dd is also non-monotonic: 2.60% → 4.05% → 4.17%** across 0.004/0.005/0.006 —
  sizing *up* from 0.004 to 0.005 jumped DD by 1.45pp because the champion flipped
  (le40→le20); the drawdown number does not even move smoothly with size.
- The closest point (0.006: dsr 0.9999 ✓, fixed_min_pf 1.89 ✓, wfo ✓, pf_lo 1.46) still
  misses DD by 0.17pp (4.17% vs 4.00%). Threading a risk between 0.005 and 0.006 to land
  DD≤4% with dsr≥0.30 would be exactly the knife-edge gate-threading condemned for trend.

### The general finding (both non-blocked intraday near-misses, same mechanism)

At full size the `max_drawdown=0.05` Backtester breaker is the **binding constraint that does
double duty**: it caps per-window drawdown near 5% *and* it culls the param combos that blow
through −5%, fixing which champion survives. Sizing down **releases** the breaker (smaller
positions rarely hit −5%), which simultaneously (a) lowers drawdown and (b) lets the
previously-culled combos compete, reshuffling the champion and the realized Sharpe. You
cannot get the lower drawdown without the champion reshuffle — so **dsr and mc_95th_dd are
both non-monotonic and chaotic in `risk_per_trade`, and "size down to fit the ALT drawdown
budget" is NOT a valid lever.** Any pass it produces (e.g. trend `dd_mid`) is a knife-edge
artifact of tuning risk to thread a razor-thin margin, not evidence of edge.

**Both intraday simple-family non-blocked near-misses are thereby exhausted as gate-passing
candidates via sizing:** `MGC_sma_trend_5m` and `MGC_donchian_15m`. The ~5% drawdown wall is
structural (the RV-filter refutation already ruled out a low-vol entry-filter rescue, and the
sizing lever is now ruled out too).

### Remaining levers (NOT sizing; Amo-gated judgment calls)

1. **Decouple the breaker from sizing** — e.g. set `max_drawdown` per-spec proportional to
   `risk_per_trade`, or disable the in-window breaker for the discovery sweep so dsr becomes
   genuinely scale-invariant and sizing-to-budget can be evaluated cleanly. This is a
   **semantic change to the validated backtester/gate** and could be read as loosening the
   gate to manufacture a pass — needs Amo's call, not an autonomous edit.
2. **Position-level drawdown control that is NOT a global size cut** — a hard per-trade dollar
   stop, or volatility-scaled (not flat-fractional) sizing, which reduces tail drawdown
   without uniformly shrinking every position. Different mechanism than `risk_per_trade`.
3. **Deeper / different data** — higher-frequency or additional symbols where the edge clears
   the floor at a lower structural drawdown. (IB micro-1h history is capped ~26mo — Amo-gated
   backfill.)

_Safety: the factory writes `data/discovery_factory/`, never `gate_v2_verdicts/`. No
candidate can self-authorize trading; promotion to live is a human decision._
