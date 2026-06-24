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

> ⚠️ **CORRECTION (2026-06-24, lever 1 below):** the mechanism stated in this section —
> "the `max_drawdown=0.05` breaker couples size to champion selection" — is **WRONG**. The
> breaker-decouple A/B (lever 1) proved the breaker is *dormant* at these sized-down risk
> levels and is NOT the cause of the non-monotonic dsr. The conclusion (sizing is not a valid
> lever; dsr/DD are non-monotonic in size) **stands**, but the true mechanism is **integer
> contract quantization**, not the breaker. See "Levers round 2 → Lever 1" below. Kept the
> original text rather than rewriting history, with this correction inline.

---

## Levers round 2 — tested 2026-06-24 ("proceed with all of the above")

Three further levers run as offline factory experiments. **All three either refute or are
moot; no robust gate pass emerged.** The ~5.5% drawdown wall survives every one.

### Lever 1 — decouple the breaker (DIAGNOSTIC) → REFUTES the breaker hypothesis

Re-ran the donchian band (0.004/0.005/0.006) with the in-window `max_drawdown` breaker
effectively OFF (1.0), as a direct A/B vs the breaker-ON band. Result: **identical**.

| risk | mc_95th_dd ON→OFF | dsr ON→OFF |
|---|---|---|
| 0.004 | 2.60% → 2.60% | 0.000 → 0.000 |
| 0.005 | 4.05% → 4.05% | 0.000 → 0.000 |
| 0.006 | 4.17% → 4.17% | 1.000 → 0.743 |

Drawdown is unchanged and dsr is still non-monotonic with the breaker off. **The breaker was
dormant** — at sized-down risk the per-window equity never draws down to −5%, so halting at
−5% changes nothing. The real coupling between size and champion/dsr is **integer contract
quantization**: `contracts = int((capital·risk)/(stop_dist·mult))`. Because each param-combo
has a different `stop_dist` (via `atr_trail_mult`), the `int()` floor rounds combos
differently at each risk level, so the in-sample champion (and the realized OOS Sharpe →
dsr) flips with size even though Sharpe is nominally scale-invariant. This is **inherent to
real futures trading** (no fractional contracts), not a removable artifact — so the
decouple-the-breaker idea is **moot**, and sizing-to-budget stays non-viable for a deeper
reason than first documented.

### Lever 2 — tighter per-trade stop at FULL risk → REFUTED

Kept risk 0.01 (no global size cut, breaker untouched) and tightened the per-trade trailing
stop (`atr_trail_mult` into the <1.5 region) to cap each trade's loss directly.

| spec | champion | mc_95th_dd | dsr | pf_lo | trades | vs baseline |
|---|---|---|---|---|---|---|
| trend baseline | atr2.5 | 5.77% | 0.792 | 1.254 | 388 | — |
| **trend STOP** | **atr1.0** | 5.55% | **0.000** | 1.329 | 285 | DD ~flat, dsr destroyed |
| donch baseline | atr2.5 | 5.55% | 1.000 | 1.533 | 243 | — |
| **donch STOP** | **atr1.0** | **5.89%** | 1.000 | 1.520 | 212 | DD *rose*, no help |

Tightening the stop does **not** lower the wall. Trend: the tightest stop (atr 1.0) was
selected yet drawdown barely moved (5.77→5.55%) while dsr collapsed 0.79→0.00 — pure whipsaw.
Donchian: the tight stop *raised* drawdown (5.55→5.89%) via more re-entries. **Diagnosis of
the wall:** the ~5.5% drawdown is **not** sourced from per-trade tail losses (which a stop
caps) — it comes from **sequences of correlated losing trades (a losing-regime drawdown)**.
A tighter stop trades a few big losses for many small ones: same-or-worse aggregate drawdown,
wrecked risk-adjusted edge.

### Lever 3 — deeper data (no-Gateway: resample-what-we-have) → REFUTES persistence (the decisive result)

The freshest-end-date loader was judging both edges on ~15mo caches while a ~24mo MGC 5m cont
cache sat unused locally. Built `backtest.resample_intraday` to lift the deep 5m → deep 15m
(49,107 bars vs 20,607) and ran distinct-label `*_deep_*` specs on the deep caches: **22 WFO
windows vs 12**. The question was persistence — does the edge hold on ~24mo? **It does not.**

| edge | window | verdict | dsr | mc_95th_dd | pf_lo | p_edge | wfo | trades |
|---|---|---|---|---|---|---|---|---|
| trend 5m | ~15mo | FAIL | 0.792 | 5.77% | 1.254 | 0.833 | STRONG | 388 |
| **trend 5m** | **~24mo** | **FAIL** | **0.000** | 5.81% | **1.012** | **0.455** | **WEAK** | 647 |
| donchian 15m | ~15mo | FAIL | 1.000 | 5.55% | 1.533 | 0.667 | MODERATE | 243 |
| **donchian 15m** | **~24mo** | **FAIL** | **0.000** | 5.51% | **1.090** | 0.682 | MODERATE | 487 |

On the deeper window **both edges evaporate**: pf_ci_lower collapses to ~1.0–1.1 (no edge),
dsr to 0.000, trend consistency STRONG→WEAK. The drawdown is unchanged (~5.5–5.8%), so the
wall is genuinely structural — but the *edge itself* on the ~15-month window was a
**period-specific artifact**, not a durable signal. Judging on ~15mo materially overstated
both near-misses; the ~24mo history (which we already had locally) exposes the
non-stationarity. (Same lesson as the peer ES-NQ spread work: a short/pooled window passes
non-stationary edges — a longer chronological window is the honest test.)

**This is the decisive, campaign-level result.** The intraday simple-family near-misses
weren't "good edges blocked only by drawdown" — on the longest history available they aren't
durable edges at all. Every lever (sizing, RV filter, breaker-decouple, tighter stop) was
attacking the drawdown of an edge that doesn't survive a longer look-back.

The genuinely-blocked deeper-intraday (beyond the ~24mo IB free-data limit) needs a **paid
intraday source** (`export_ibkr_history` is 1h/1d-only; IB free micro-1h caps ~26mo) — an Amo
procurement decision, not a Gateway restart. But given persistence already fails at 24mo,
buying more of the *same* family's history is low-value; the signal says change the
**strategy class**, not extend the look-back.

_Safety: the factory writes `data/discovery_factory/`, never `gate_v2_verdicts/`. No
candidate can self-authorize trading; promotion to live is a human decision._
