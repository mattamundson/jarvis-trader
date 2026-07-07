# Gate v2 vs Funnel Gate — Expanded Comparison Findings

**Date:** 2026-06-26
**Sample:** N = 38 strategy records (27 with gate_v2 verdicts to compare against), drawn from 5 distinct data sources in the jarvis-trader repo
**Spreadsheet:** `gate_comparison_v1.xlsx` (4 sheets)

---

## Headline Numbers (with 95% bootstrap CIs)

| Metric | Point | 95% CI | Read |
|---|---|---|---|
| gate_v2 rejection rate | 92.6% | [81.5%, 100%] | Kills 25/27 strategies with verdicts |
| funnel_gate rejection rate | 92.1% | [81.6%, 100%] | Kills 35/38 records |
| Agreement rate | 96.3% | [88.9%, 100%] | Gates agree on 26/27 |

**Translation:** The two gates produce statistically indistinguishable rejection rates on this dataset. **The funnel_gate is not capturing materially more alpha than gate_v2** on records where both can be evaluated — but it's also not introducing measurably more p-hacked noise. They're behaving as near-equivalents under the current methodology.

---

## Disagreement Detail (the actual signal)

| Direction | Count | What it means |
|---|---|---|
| gate_v2 PASS / funnel REJECT | **0** | funnel_gate is NOT over-strict relative to gate_v2 |
| gate_v2 FAIL / funnel A or B | **1** | funnel_gate "rescues" one strategy that gate_v2 killed |

The single rescue is the MGC_trend_rank3 case we identified previously — funnel_gate gives it Tier B with documented improvement hypotheses; gate_v2 hard-killed it on `fixed_params_min_pf`. This validates that the test-suite work was on real signal.

---

## What This Data Honestly Does NOT Show

I want to be direct about this before you make budget decisions on it:

### 1. The CIs are too wide to commit on
The agreement-rate CI floor (88.9%) and ceiling (100%) overlap with both "near-perfect agreement" and "meaningful disagreement." We literally cannot tell from N=27 whether the gates are 96% aligned or 90% aligned. The point estimate is favorable but the uncertainty band is large.

### 2. Effective N is lower than nominal N
Many records refer to the same underlying hypothesis seen from different angles (verdict file + WFO journal row + validation report). After dedup we have 42 unique (symbol, family, rank) tuples — and even those aren't fully independent (e.g., MGC trend rank1-4 are sequential variants of the same idea). True i.i.d. count is closer to **20-25**, not 38.

### 3. funnel_gate inputs are RECONSTRUCTED, not measured
The historical data has DSR, pf_ci_lower, and WFO consistency. It does NOT have:
- Per-regime DSR (Gate 6)
- Permutation test p-values (Gate 9)
- Slippage stress results (Gate 8)
- Bar contamination check (Gate 10)

For this comparison I proxied them from what IS measured (e.g., WFO=STRONG → perm_p=0.01). **Real Phase 3 runs will produce these natively** and Gate 6/8/9/10 will become discriminating in ways they aren't here. The "agreement rate" is artificially high because half my gates are running on default-pass proxies.

### 4. No outcome data
There are 488 paper trades but **all have `pnl=null`** (open positions). We cannot ground-truth either gate against realized P&L. Without that, "rejection rate" is just "how often the gate says no" — it cannot tell you which gate captures more alpha.

### 5. Single regime, single instrument cluster
All verdicts cluster in 5 weeks (2026-04-23 to 2026-05-24). Heavy concentration on MNQ/MGC/MES; **no SPY or ES** data. The instrument you actually want to validate against (ES) isn't represented.

---

## Family-Level Variance (Sheet 2 of spreadsheet)

Where does disagreement live? In short: **almost nowhere yet, because the data is too thin.** Here's what I CAN say:

| Family pair | N | Disagreements | Notable |
|---|---|---|---|
| MGC/trend | 8 | 1 | The MGC rank3 rescue case |
| MNQ/breakout | 7 | 0 | All 7 are gate_v2 FAIL + funnel C — strong agreement on noise rejection |
| MES/trend | 6 | 0 | Includes the 3 PASS verdicts (rank7, rank11×2) — both gates accept |
| MGC/mean_reversion | 4 | 0 | Both kill all 4 — consensus on weak edge |
| Everything else | <4 each | 0 | N too small to claim anything |

**Systemic biases I can spot from this slice:**

1. **Both gates are extremely strict on mean reversion** — across MGC/MES/MCL/MNQ mean_reversion families, every single record is a FAIL. Either the strategies in your library are genuinely weak, OR both gates share a methodology that systematically under-credits mean-reversion edges. Worth investigating.

2. **Both gates pass MES trend at higher rates** (3/6 PASS) than any other family. **[Inference]** this is the family with the most refined parameters and longest research history — not necessarily a gate bias.

3. **Funnel Tier B is empty in this sample.** Zero strategies got Tier B. That's either because (a) historical data lacks the per-regime metrics that would let strategies qualify for Tier B's "specialist" path, OR (b) Tier B thresholds are tuned too close to Tier A — strategies either clear them all or fail them all. Likely the former; will know more after a real Phase 3 run.

---

## Recommendation

**Do NOT proceed to the full 84-strategy LLM-powered Phase 1 run based on this analysis alone.** Here's why and what to do instead:

### Why not yet
- The 96.3% agreement rate is reassuring, but the CI is too wide and half the funnel's gates are running on proxies. The comparison can't credibly tell you the funnel is "safer" or "more accurate" — only that the two gates *broadly cluster together* on a small, regime-limited sample.
- Spending Anthropic credits on 84 LLM atom extractions before the funnel itself has been validated on natively-measured metrics is premature optimization.

### Better sequence
1. **Run a Phase 1 with `JARVIS_FUNNEL_LLM_PROVIDER=heuristic`** (no LLM cost). This produces strategies_v1.jsonl from the repo (as the dry-run already did, 73 cards).
2. **Run Phase 2 (smoke test) on ~5 hand-picked Tier-candidate strategies** — including the 3 MES_trend PASS strategies, MGC_trend_rank3 (the rescue case), and 2 MGC mean_reversions (the consensus-kill cases). This is ~5 backtests on your machine, no LLM, costs you compute time only.
3. **Run Phase 3 on whichever survive Phase 2** — this generates real per-regime DSR, real permutation tests, real slippage stress numbers.
4. **NOW the gate comparison is meaningful.** Re-run this spreadsheet's logic with native metrics instead of proxies. Agreement rate will likely DROP (Gate 6/8/9/10 finally have teeth) — that's the data you actually need.
5. **Only then** commit LLM budget to the full inventory pipeline.

### What "ready to commit to the full inventory" looks like
- Phase 3 has been run on ≥ 10 strategies with native metrics
- Re-computed agreement rate sits with a CI tighter than ±10%
- The MGC_trend_rank3-style false-negative correction is observable in real data, not synthetic
- You have at least one paper trade with `pnl != null` to ground-truth at least one verdict

Estimated additional work to get there: ~1 evening of local Phase 2/3 runs on 5-10 strategies, zero LLM cost, and one more conversation with me to re-run this comparison on the resulting native-metric data.

---

## Files

- `gate_comparison_v1.xlsx` — full audit spreadsheet (Summary, Family Breakdown, All Comparisons, Methodology)
- `gate_comparison_findings.md` — this document
- `gate_v2_audit_mgc_evidence.md` — the original MGC-only deep dive (from earlier turn)
- `test_funnel_gate_vs_gatev2.py` — 15-test suite that locks in the documented gate behaviour
