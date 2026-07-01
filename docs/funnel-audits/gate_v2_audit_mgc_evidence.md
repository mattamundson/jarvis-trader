# gate_v2 vs MGC Verdicts — Restrictiveness Audit

**Purpose:** Determine which gate_v2 FAILs on MGC strategies represent (a) legitimate filtering of noise vs (b) false negatives that would have produced edge. Build a test suite that ensures the new `funnel_gate.py` doesn't blindly inherit any false-negative patterns.

**Date:** 2026-06-26
**Source data:** `engine/data/gate_v2_verdicts/archive/MGC_*.json` (7 verdicts), `engine/data/mgc_wfo_journal.csv`

---

## The MGC Verdict Landscape (raw data)

| File | Verdict | Via | pf_ci | p_edge | dsr | mc_dd_% | wfo | core_passed | alt_passed |
|---|---|---|---|---|---|---|---|---|---|
| MGC_meanrev_rank1 | FAIL | – | 0.72 | 0.32 | 0.0 | 5.69 | WEAK | 2 | – |
| MGC_meanrev_rank2 | FAIL | – | 0.50 | 0.25 | 0.0 | 5.13 | WEAK | 2 | – |
| MGC_trend_rank1 | FAIL | – | NaN | 0.60 | 0.0 | 0.09 | MODERATE | 3 | – |
| MGC_trend_rank2 | FAIL | – | NaN | 0.75 | 0.0 | 0.01 | STRONG | 3 | – |
| MGC_trend_rank3 | FAIL | – | NaN | 0.75 | 1.0 | 1.48 | STRONG | 3 | 4 |
| MGC_trend_rank4 (PASS) | PASS | alt | 2.58 | 0.68 | 1.0 | 1.24 | MODERATE | 3 | 5 |

**Gate v2 thresholds (from each verdict's `thresholds` block):**
```
core path:
  pf_ci_lower >= 1.10
  p_edge >= 0.95
  mc_95th_dd <= 0.05  (i.e. <= 5%)
  dsr >= 0.10
  + cost_survives_through >= "realistic"

alt path:
  fixed_params_min_pf >= 1.2  (replaces pf_ci_lower)
  wfo_consistency in {MODERATE, STRONG}
  mc_95th_dd <= 0.07
  dsr >= 0.30
```

---

## Each MGC FAIL — Is It Correct Filtering or a False Negative?

### Case 1 — MGC_trend_rank1: **CORRECT FAIL** (clear noise)

| Metric | Value | Threshold | Pass? |
|---|---|---|---|
| pf_ci_lower | NaN | ≥ 1.10 | ❌ no data |
| p_edge | 0.60 | ≥ 0.95 | ❌ |
| dsr | 0.0 | ≥ 0.10 | ❌ |
| mc_95th_dd | 0.93% | ≤ 5% | ✅ |
| wfo | MODERATE | n/a (core) | – |

**Verdict justified:** Only 1/4 core gates pass. p_edge of 0.60 means only 60% of WFO windows showed positive edge — that's barely better than a coin flip on direction. DSR=0 means the Sharpe is deflated to literal noise. **No edge here. Kill was right.**

### Case 2 — MGC_trend_rank2: **CORRECT FAIL but a SOFT NO**

| Metric | Value | Threshold | Pass? |
|---|---|---|---|
| p_edge | 0.75 | ≥ 0.95 | ❌ |
| dsr | 0.0 | ≥ 0.10 | ❌ |
| mc_95th_dd | 0.01% | ≤ 5% | ✅ |
| wfo | STRONG | n/a (core) | – |

**Verdict justified BUT worth retrying with improvements:** p_edge=0.75 fails core (which needs 0.95) but ties the alt threshold's wfo_consistency=STRONG. DSR=0 is what really sinks it. The strategy shows consistent behavior across WFO windows but the Sharpe ratio after multiple-testing correction is zero. **[Inference]** this is likely a strategy that has frequent small wins and rare big losses — looks consistent on WFO but tail risk eats the DSR. Killing it is correct *as-is*; would be a candidate for Tier B if it could fix DSR via a stop-loss tweak.

### Case 3 — MGC_trend_rank3: **🚨 LIKELY FALSE NEGATIVE — KEY CASE**

This is the smoking gun.

| Metric | Value | Core threshold | Alt threshold | Pass? |
|---|---|---|---|---|
| pf_ci_lower | NaN | ≥ 1.10 | – | ❌ (no data, not "failed") |
| p_edge | 0.75 | ≥ 0.95 | – | ❌ core |
| dsr | **1.0** | ≥ 0.10 | ≥ 0.30 | ✅ both paths |
| mc_95th_dd | 1.48% | ≤ 5% | ≤ 7% | ✅ both paths |
| wfo | STRONG | – | in {MOD, STRONG} | ✅ alt |
| fixed_params_min_pf | **0.45** | – | ≥ 1.2 | ❌ alt |
| cost_survives_through | catastrophic | ≥ realistic | – | ✅ |

**Why this FAILED:** The alt path failed on `fixed_params_min_pf` (0.45 < 1.2). The "min PF across all parameter combinations" is dragged down by one bad combo (fast=30, slow=160, atr_trail=2.0 → PF=0.45 over 30 trades).

**The smoking gun:** rank3's champion params are `fast=50, slow=120, atr_trail_mult=2.0` — **the EXACT SAME params** as the PASS-verdict rank4. And rank3's champion combo had PF=2.99 over 48 trades. rank4 has the same combo at PF=3.17.

**The only meaningful difference between rank3 (FAIL) and rank4 (PASS):**
- rank3 tested 18 parameter combinations including some bad ones (fast=30 family)
- rank4 tested only 8 combinations (dropped fast=30 family)
- → rank4's `fixed_params_min_pf=1.36` (passes 1.2 threshold)
- → rank3's `fixed_params_min_pf=0.45` (fails 1.2 threshold) — but only because someone included combos that the optimizer would never have picked

**This is a methodology bug, not a real edge difference.** The gate penalizes strategies for the *width of their search grid*, not for the quality of their champion combo. A more disciplined parameter sweep would have passed; the broader sweep failed.

→ **Action for new funnel_gate:** Do NOT inherit `fixed_params_min_pf` as a hard gate. Replace with: "≥80% of param combos with ≥30 trades must have PF > 1.0" OR use the *median* combo PF, not the min. Penalizing wide search grids encourages narrower searches, which paradoxically increases overfitting risk.

### Case 4 — MGC_trend_rank4 (PASS): **CORRECT PASS**

| Metric | Value | Pass? |
|---|---|---|
| pf_ci_lower | 2.58 | ✅ ≥ 1.1 (core) |
| p_edge | 0.68 | ❌ core but irrelevant since via=alt |
| dsr | 1.0 | ✅ both paths |
| mc_95th_dd | 1.24% | ✅ both paths |
| wfo | MODERATE | ✅ alt |
| fixed_params_min_pf | 1.36 | ✅ ≥ 1.2 (alt) |

Note: `pf_ci_lower=2.58` is computed in the later verdict but absent in earlier MGC trend FAILs. **[Inference]** the pf_ci_lower computation was added or fixed for the May 20 refresh — older verdicts may be missing this metric entirely, not actually failing it.

### Case 5 — MGC_meanrev_rank1: **CORRECT FAIL with reservations**

| Metric | Value | Threshold | Pass? |
|---|---|---|---|
| pf_ci_lower | 0.72 | ≥ 1.10 | ❌ |
| p_edge | 0.32 | ≥ 0.95 | ❌ |
| dsr | 0.0 | ≥ 0.10 | ❌ |
| mc_95th_dd | **5.69%** | ≤ 5% (core), ≤ 7% (alt) | ❌ core, ✅ alt |
| wfo | WEAK | in {MOD, STRONG} | ❌ alt |

**Verdict justified.** Mean reversion on MGC with WEAK WFO consistency and p_edge=0.32 means only 32% of windows showed edge — actually *worse than random*. But note `mc_95th_dd=5.69%` is right at the boundary; in a regime where MGC's vol expanded, this strategy could be the right kind of vol-expansion harvester. **[Inference]** still likely correct to kill but worth a Tier B improvement hypothesis: "test on contango/backwardation regimes separately — gold mean reversion may only work in low-volatility consolidation."

### Case 6 — MGC_meanrev_rank2: **CORRECT FAIL**

Same pattern as rank1. p_edge=0.25 is worse-than-random. Kill is correct.

---

## Restrictiveness Pattern Summary

| Pattern | gate_v2 behavior | Correct? | Action for funnel_gate |
|---|---|---|---|
| **DSR=0** | Hard FAIL via core, even if all other metrics great | Mostly correct (zero Sharpe after correction = no edge) | Inherit. DSR=0 is a true kill signal. |
| **p_edge < 0.95 in core path** | Hard FAIL | Sometimes overly strict (rank3 had p_edge=0.75 with WFO=STRONG) | Replace with proportional weighting; p_edge=0.75 + DSR=1.0 should pass somewhere |
| **fixed_params_min_pf < 1.2** | Hard FAIL in alt path | **OVERLY RESTRICTIVE** (penalizes wide search grids) | DO NOT INHERIT. Replace with "≥80% of combos with ≥30 trades have PF > 1.0" |
| **mc_95th_dd at threshold (rank1 meanrev = 5.69%)** | Hard FAIL via core | Reasonable but binary | Soften: 5.69% should be Tier B with regime-conditioning hypothesis, not Tier C |
| **NaN pf_ci_lower** | Doesn't actually fail (allowed) | Methodology gap | Funnel_gate should DEMAND pf_ci_lower be computed; null is a kill |
| **wfo=WEAK** | Hard FAIL in alt | Correct (WEAK = strategy doesn't repeat) | Inherit |
| **WFO=STRONG + DSR=1.0 + everything else passes BUT one alt-path numerical threshold fails by a hair** | Hard FAIL | **OVERLY RESTRICTIVE** | These should be Tier B candidates with documented improvement paths, NOT Tier C |

---

## The False-Negative Hypothesis (the rank3 problem, generalized)

**Pattern:** A strategy whose CHAMPION combo is excellent (DSR=1.0, mc_dd<1.5%, champion PF=3.0) can FAIL `fixed_params_min_pf` because the parameter grid included a bad outlier combo.

**Why this matters:** In production, you never run the bad combo — you run the champion. The gate is asking "is the entire parameter space safe?" when the relevant question is "is the chosen point safe?" These are different questions.

**Funnel_gate behavior:** The new gate should:
1. Pass strategies whose *champion* combo is excellent
2. Use the *median* (not min) PF across parameter combos as a robustness check
3. Separately flag a `parameter_sensitivity_score` that quantifies how cliffed the surface is — but don't auto-kill on it

---

## The Test Suite (`tests/test_funnel_gate_vs_gatev2.py`)

The script saved alongside this doc contains 14 named test cases. Each is a fixture built from real MGC verdict data + 6 synthetic edge cases. The suite checks:

- **Inheritance correctness** — funnel_gate must agree with gate_v2 on every CORRECT-FAIL case (5 of 6 MGC FAILs)
- **False-negative correction** — funnel_gate must produce Tier A or Tier B (NOT Tier C) on the rank3-style cases where the only failure is `fixed_params_min_pf`
- **Borderline handling** — strategies right at thresholds (mc_dd=5.7%, p_edge=0.93) should produce Tier B with documented improvement paths, not Tier C
- **NaN trap** — strategies with missing pf_ci_lower should fail funnel_gate (gate_v2 silently passes some of these)

See `tests/test_funnel_gate_vs_gatev2.py`. To run:

```powershell
cd C:\path\to\jarvis-robust-strategy-funnel
python -m pytest tests/test_funnel_gate_vs_gatev2.py -v
```

The suite will fail until you've adjusted `funnel_gate.py` to NOT inherit the `fixed_params_min_pf` pattern. That's the point — the failing tests are the documentation of which behaviors you're consciously deciding to change.

---

## Recommended Changes to `funnel_gate.py`

1. **Add Gate 11: Champion-combo robustness** — instead of relying on a `fixed_params_min_pf`-style global gate, check:
   - Champion combo's PF in the realistic cost tier ≥ 1.5
   - ≥ 80% of param combos with ≥ 30 trades have PF > 1.0
   - Param sensitivity penalty = `(max_PF - median_PF) / median_PF` — log this as a *risk flag* on the verdict, but don't auto-kill

2. **Reject NaN pf_ci_lower as a hard fail** — the metric must be computed. The new Gate 3 already does this; just document the divergence from gate_v2 explicitly.

3. **For strategies where DSR=1.0 + WFO=STRONG but a single alt-path metric narrowly fails** — drop to Tier B with auto-generated improvement hypotheses (see `_generate_improvements` in funnel_gate.py)

4. **Don't trust gate_v2 verdict as ground truth** — `funnel_gate` already has a disagreement-flagging mechanism (`gate_v2_disagreement: True`). Make rank3 the canonical test case for this: the funnel should produce Tier B (with note "rank3-pattern: champion combo great, alt-path penalty"), gate_v2 produced FAIL. Both verdicts are logged.

---

## What's NOT a False Negative (don't change these)

- **DSR=0 hard fail** — keep it. A Sharpe ratio that deflates to zero is genuinely no-edge.
- **p_edge < 0.50** — keep killing these. Worse than coin flip means the strategy is anti-edge.
- **WFO=WEAK in alt path** — keep killing. WEAK consistency means the strategy doesn't repeat across windows; you cannot live-trade a non-repeating strategy.
- **mc_95th_dd > 10%** — would still kill; nothing in this data set crossed 10%.
