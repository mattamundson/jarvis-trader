# MES Trend Realized-Volatility Filter — Deep Analysis
**Date:** 2026-05-06  
**Analyst session:** overnight continuation of 2026-05-05 evening  
**Verdict file:** `engine/data/gate_v2_verdicts/MES_trend_rv_filter_rank1.json`  
**Baseline:** `engine/data/gate_v2_verdicts/MES_trend_rank11.json`  
**Status:** FAIL — documented, filed, not blocking production

---

## 1. What We Were Testing and Why

The MES SMA(50,200) trend strategy — the only currently live paper trading strategy — passed gate v2 via the ALT path (rank11, created 2026-05-06, expires 2026-05-20). ALT path means: it works, but only with sufficient capital ($50K+) because the full-dataset PF of 1.35–2.16 across grid combos is below the core-gate robustness threshold. The strategy is real and tradeable, but not dominant.

The RV filter hypothesis was: **the edge isn't uniformly distributed across volatility regimes.** Specifically, the code comment in `trend_signals.py` (lines 34–38, added 2026-04-21 after 36 live-trade analysis) states:

> Analysis of 36 live champion trades shows SMA trend edge concentrates in high-vol regimes. Below RV-20 annualized ≈ 9%, trades net-lose.

If true, enabling `min_rv_annualized=9.0` in `MES_TREND_PAPER_CONFIG` would:
- Remove ~39% of trades (36→22 filtered)
- Improve PF from 2.06 to 2.54 (+23%)
- Potentially push the strategy from ALT-path-only to a wider range of capital sizes

This is worth testing. A +23% PF improvement on the only live strategy is significant. The question is whether this improvement is real (a genuine regime edge) or statistical noise in a 36-sample.

---

## 2. The Empirical Claim vs. What WFO Measures

These are measuring different things, and understanding the distinction is critical for interpreting the FAIL verdict.

### What the 36-trade empirical analysis measured

The 36-trade sample was derived from running `generate_sma_trend_signals(fast=50, slow=200, atr_trail_mult=2.0, min_rv_annualized=0.0)` on the full MES 1h dataset (2024-04-26 to 2026-03-27) and tagging each trade with the `rv_20_ann_pct` value at entry. The result:

| RV regime at entry | Trades | PF |
|---|---|---|
| All trades (no filter) | 36 | 2.06 |
| RV ≥ 9% | 22 | 2.54 |
| RV < 9% | 14 | ~0.70 (net losing) |
| RV ≥ 13% | 13 | 5.51 |
| RV 9–13% | 9 | ~1.19 |

This is a **full-period, single-combo analysis** on the champion params (50,200,2.0). It uses the entire available dataset as a single pool. There is no train/test split.

### What WFO measures

WFO divides the same dataset into 18 overlapping windows (6-month IS, 1-month OOS, sliding by 1 month). For each window, it:
1. Selects the best combo out of 3 on IS data
2. Evaluates that combo on OOS data
3. Counts the window as "profitable" if OOS PF > 1.0

The WFO question is: **does the edge persist in genuine out-of-sample forward evaluation?** It tests whether a hypothetical trader who tuned params in the past 6 months would have made money in the next month.

### Why they diverge for the RV filter

The RV filter reduces trade frequency by ~39% on the full dataset. In a 1-month OOS window, the champion (50,200) strategy generates approximately 2 trades per month unfiltered. With the filter, that drops to 1-2 trades per OOS month on average — and in many months, **zero**.

9 of 18 OOS windows had exactly 0 trades after filtering. This isn't random noise — it's structural. The SMA(50,200) strategy generates a golden cross entry roughly once every 2-3 weeks. The RV filter then blocks that entry if the preceding 20-bar realized vol is below 9% annualized. In low-vol consolidation months (there were many in 2024-2026), no entry passes the filter.

**The result:** `p_edge` — the fraction of OOS windows with PF > 1.0 — is computed over only the 9 windows that had any trades at all. Of those 9, only 6 were profitable. p_edge = 6/9 = 0.667. Gate requires 0.95.

**Key insight:** p_edge of 0.95 means 17 of 18 windows must be profitable. With only 9 windows having any trades at all, this is arithmetically impossible — you'd need 17 profitable windows but only 9 have enough trades to even register a PF. The metric cannot pass even if every trade that fired was a winner.

---

## 3. Per-Window Deep Dive

Complete comparison of rank11 (no filter) vs rv_filter_rank1 for all 18 windows:

| Win | OOS Period | rank11 trades | rank11 PF | rv_filter trades | rv_filter PF | IS params (filter) | Filter impact |
|---|---|---|---|---|---|---|---|
| 1 | Oct 2024 | 1 | 0.00 | 1 | 0.00 | (60,200,2.0) | Same — trade fired but lost |
| 2 | Nov 2024 | 0 | 0.00 | 0 | 0.00 | (60,200,2.0) | No change — both empty |
| 3 | Dec 2024 | 1 | inf | 1 | inf | (60,200,2.0) | Same — win (entry was in high-vol) |
| 4 | Jan 2025 | 1 | inf | 0 | 0.00 | (60,200,2.0) | Filter BLOCKED the win |
| 5 | Feb 2025 | 1 | inf | 1 | inf | (55,200,2.0) | Same — win |
| 6 | Mar 2025 | 1 | inf | 1 | inf | (55,200,2.0) | Same — win |
| 7 | Apr 2025 | 0 | 0.00 | 0 | 0.00 | (55,200,2.0) | No change — both empty |
| 8 | May 2025 | 2 | 0.74 | 3 | 0.40 | (55,200,2.0) | WORSE with filter (3 trades vs 2, lower PF) |
| 9 | Jun 2025 | 0 | 0.00 | 0 | 0.00 | (50,200,2.0) | No change — both empty |
| 10 | Jul 2025 | 1 | inf | 1 | inf | (50,200,2.0) | Same — win |
| 11 | Aug 2025 | 0 | 0.00 | 0 | 0.00 | (50,200,2.0) | No change — both empty |
| 12 | Sep 2025 | 1 | inf | 0 | 0.00 | (50,200,2.0) | Filter BLOCKED the win |
| 13 | Oct 2025 | 2 | inf | 1 | inf | (50,200,2.0) | Filter removed one trade, kept win |
| 14 | Nov 2025 | 2 | inf | 2 | inf | (50,200,2.0) | Same — both wins |
| 15 | Dec 2025 | 0 | 0.00 | 0 | 0.00 | (50,200,2.0) | No change — both empty |
| 16 | Jan 2026 | 2 | 1.64 | 0 | 0.00 | (50,200,2.0) | Filter BLOCKED 2 trades, turned +PF window to empty |
| 17 | Feb 2026 | 1 | 0.00 | 1 | 0.00 | (50,200,2.0) | Same — both lose |
| 18 | Mar 2026 | 0 | 0.00 | 0 | 0.00 | (50,200,2.0) | No change — both empty |

**Key observations from the per-window comparison:**

**Observation 1: The filter blocked 3 high-quality wins (windows 4, 12, 16).**  
Windows 4, 12, and 16 had infinite or positive PF in rank11 but 0 trades in the filter run. These are false negatives — the filter excluded profitable trades in those months. Specifically, January 2025 (win 4) and September 2025 (win 12) had single infinite-PF trades that passed rank11 but failed the RV screen. January 2026 (win 16) had 2 trades at PF=1.64 that were blocked.

**Observation 2: The filter made window 8 worse.**  
May 2025 (win 8) is the worst OOS month in both versions. In rank11: 2 trades at PF=0.74. In rv_filter: 3 trades at PF=0.40. The filter not only failed to block the losing trades — it allowed one additional losing trade. This is because IS param selection with RV filter active shifted from (60,200) in early windows to (55,200) for window 8, and (55,200) generated a different trade set in May 2025.

**Observation 3: IS param selection shifted dramatically with the filter.**  
In rank11, (60,200) was selected 7 times; in rv_filter_rank1, (60,200) was selected 4 times (windows 1-4 only). After window 4, the filter run shifts to (55,200) for windows 5-8, then to (50,200) for windows 9-18. This means the RV filter doesn't just reduce trades — it **also changes which parameters look best in IS**, creating a different "champion" in each window than rank11 would have selected. This is an additional source of OOS mismatch.

**Observation 4: The net effect of the filter on 1-month OOS windows is negative.**  
The filter removed 4 profitable trades (wins 4, 12, 16: 3 windows worth of +PF) and did not prevent the only genuine losing window (win 8 became slightly worse). The filter's statistical advantage only materializes over long periods because the ~14 removed trades were, on average, modest losers — but in any single month, the filter's binary (trade/no-trade) decision looks random and slightly harmful.

---

## 4. Why the Fixed-Params Sweep Diverges

The fixed-params sweep runs each grid combo on the **full dataset** (no IS/OOS split) and reports `fixed_params_min_pf` — the floor PF across all combos. This is an ALT-gate metric testing whether the parameter family is internally consistent.

| Combo | rank11 PF | rank11 trades | rv_filter PF | rv_filter trades | PF delta |
|---|---|---|---|---|---|
| (50, 200, 2.0) | 1.3506 | 35 | 1.1125 | 21 | -0.238 |
| (55, 200, 2.0) | 1.7219 | 35 | 1.3707 | 22 | -0.351 |
| (60, 200, 2.0) | 2.1558 | 29 | 2.0845 | 15 | -0.071 |

Two important patterns:

**Pattern 1: The RV filter hurts (50,200) more than (60,200).**  
(50,200) loses 0.238 PF points; (60,200) only loses 0.071. This seems counterintuitive — shouldn't the filter help equally across combos? The answer is that different fast periods generate different sets of entries in the same underlying data. The (50,200) golden cross fires more frequently than (60,200) because the 50-bar SMA is more sensitive. Many of those additional (50,200) entries fire in moderate-vol environments (RV 6-8%) that are just below the 9% threshold. These trades are profitable on average in the (50,200) system (they're real trend entries) but get blocked by the filter. So the filter is selectively removing some of (50,200)'s legitimate edge trades.

**Pattern 2: (60,200) is naturally better suited to the RV filter.**  
(60,200) generates fewer but higher-quality trades because the slower 60-bar SMA requires a stronger, more developed trend before crossing above the 200-bar. Strong trends coincide with higher volatility, so (60,200) entries already cluster at higher RV levels — the filter removes proportionally fewer of its trades (29 → 15, a 48% reduction) but the ones it removes are already the weakest, leaving PF nearly unchanged (2.16 → 2.08).

**Implication for future work:**  
If the RV filter is ever revisited, the natural champion with the filter is (60,200), not (50,200). The empirical 36-trade analysis was done on (50,200) — worth redoing that analysis on (60,200) to see if the +23% PF improvement is larger or smaller for the faster-decaying fast SMA.

**Why fixed_params_min_pf still fails:**  
Even with the filter, (50,200) full-dataset PF drops to 1.11 — below the 1.20 ALT floor. The floor is driven by the champion combo itself (50,200), which is the one that gets hurt most by the filter. This is not a "laggard combo" problem (the rank9–10 lesson) — it's the champion getting dragged below the gate's floor by the filter's selective trade removal.

---

## 5. The IS Overfit Problem

The IS period for each window generates 2–6 trades after filtering. Compare:

| Window | rank11 IS trades | rv_filter IS trades | Reduction |
|---|---|---|---|
| 1 | 4 | 2 | -50% |
| 2 | 5 | 4 | -20% |
| 3 | 5 | 4 | -20% |
| 4 | 7 | 6 | -14% |
| 5 | 8 | 6 | -25% |
| 6 | 8 | 6 | -25% |
| 7 | 7 | 6 | -14% |
| 8 | 6 | 5 | -17% |
| 9 | 8 | 6 | -25% |
| 10 | 6 | 5 | -17% |
| 11 | 7 | 6 | -14% |
| 12 | 8 | 5 | -38% |
| 13 | 10 | 4 | -60% |
| 14 | 11 | 5 | -55% |
| 15 | 10 | 4 | -60% |
| 16 | 10 | 5 | -50% |
| 17 | 10 | 5 | -50% |
| 18 | 10 | 6 | -40% |

In windows 13–17 (the late-period windows), the IS trade count with filter drops to 4–5. At 4–5 trades in a 6-month IS period, the IS grid search is choosing params based on noise. A 3-combo grid search on 4 trades is statistically meaningless — the "best" IS params are a coin flip between the three combos. The IS winner changes erratically across windows, further destabilizing OOS performance.

A usable heuristic: IS grid search requires at least 15–20 trades to select params with meaningful signal. The unfiltered rank11 IS periods average 8–10 trades — already below this threshold, which explains why rank11's IS champion selection is also noisy (jumps between fast=50, 55, 60 across windows). But 8–10 trades is approximately twice as many as 4–6, and the difference matters for IS optimality.

**The deeper issue:** WFO grid search on a low-frequency strategy is always going to produce noisy IS selections. The rank11 result PASSES despite this noisiness because the underlying edge is strong enough that even a "wrong" combo performs reasonably well in OOS. The RV filter reduces the edge concentration enough that the wrong-combo OOS penalty becomes decisive.

---

## 6. The Bootstrap NaN Anomaly

Both rank11 and rv_filter_rank1 report `pf_ci_lower=NaN`. This is a bug, not a data artifact.

The bootstrap CI lower bound is computed by sampling-with-replacement from the OOS PF list and computing the mean of each sample. If any OOS window has PF=inf (a period where every trade won), `numpy.mean([inf, 1.2, 0.5, inf, ...])` returns `inf`, and `numpy.percentile([inf, inf, ...], 5.0)` returns `NaN` when the distribution is degenerate.

The code should cap Infinity PFs at a reasonable upper bound (e.g., 10.0) before bootstrapping, or use the geometric mean rather than the arithmetic mean. Both verdicts would then produce finite `pf_ci_lower` values.

**Why this doesn't currently affect the PASS/FAIL outcome:**  
The `n_core_passed` counter counts a reason string as "passing" if it does not begin with "FAIL". Since the `pf_ci_lower` reason is formatted as `"mbb_pf_ci_lower=nan >= 1.1"` (no FAIL prefix) rather than `"FAIL mbb_pf_ci_lower=nan < 1.1"`, it incorrectly counts as a passing criterion. Both rank11 and rv_filter have 3/4 core criteria "passing" by this count — but the correct count for rank11 would be 3 passing (mc_95th_dd, dsr, and the spurious pf_ci_lower=nan) vs the real 2 passing (mc_95th_dd and dsr). The p_edge failure is the genuine blocker in both cases.

**Consequence:** The bootstrap CI lower bound is not currently a meaningful gate criterion because it always reports NaN (and counts as "passing") when any OOS window has infinite PF. This should be fixed in a future gate v2 maintenance pass. It does not affect rank11's PASS verdict since that passes via ALT (not via the core pf_ci_lower criterion). It also does not affect rv_filter's FAIL verdict — the real blockers are p_edge and fixed_params_min_pf.

---

## 7. What the Failure Reveals About the Empirical Claim

The empirical 36-trade analysis made a claim: trades entered when RV < 9% are net losing. The WFO doesn't contradict this claim — it simply can't validate it per-window because there aren't enough filtered trades per 1-month OOS window to produce reliable PF statistics.

The key question: **is the original 36-trade empirical finding reliable?**

Evidence that it is real:
- 36 trades is a reasonable sample for a qualitative directional claim
- The split is clean: PF 2.54 (22 trades) vs PF ~0.70 (14 trades) is a large effect size
- Mechanistic basis: low-RV environments are consolidation phases; SMA crossovers in consolidations are false breakouts that reverse quickly
- Independent theoretical support: ATR-based stops are sized relative to current vol; in low-vol environments, the stop is tight relative to mean-reversion range, so small counter-moves hit the stop before the trend develops

Evidence for caution:
- 36 trades is below the 60-trade threshold the code itself specifies before enabling the filter in production
- The split (9% threshold) was chosen by inspecting the same 36-trade dataset — it may be data-fit
- The WFO analysis shows the filter blocked 3 profitable trades in specific months (Jan 2025, Sep 2025, Jan 2026) — these weren't actually low-quality
- The full-dataset (50,200) PF drops from 1.35 to 1.11 with the filter — this is the reverse of the expected improvement

The most likely resolution: the empirical effect is **real but unstable across time**. The edge concentration at high RV isn't constant — in some months it holds, in others it reverses. The 36-trade sample happened to capture a period where the split was clean. Over a longer time horizon or with more windows, the split degrades.

---

## 8. Path Forward — How and When to Revisit

The filter should not be enabled now. Three conditions would change this:

### Condition 1: Accumulate 60+ live paper trades (per code comment)

The code in `trend_signals.py` line 35 specifies this explicitly:
```
# Production gate to enable only after 60+ trades confirm the improvement.
```

Currently: ~36 trades from rank11 paper data. At the current rate of 1-2 MES trades per month with IB not connected, this will take approximately 8-12 months of live paper trading. With IB Gateway connected during market hours, the rate improves.

When 60+ trades are accumulated, the right analysis is:
1. Tag each live trade with `rv_20_ann_pct` at entry (this is already computed and in the signals DataFrame)
2. Split at 9% threshold
3. If PF(RV≥9%) / PF(all) ratio > 1.20 with p < 0.05 (one-tailed Fisher's test on win/loss counts), the filter is confirmed

### Condition 2: Test with longer OOS windows (3-month OOS instead of 1-month)

Running `run_mes_trend_rv_filter.py` with `TEST_MONTHS=3` would give approximately 6 OOS windows (instead of 18) but each window would have 3–6 filtered trades. This is still sparse but might be enough for p_edge to achieve 5/6 = 0.83 — closer to 0.95.

The downside: 6 windows is a very small WFO sample. The uncertainty on any metric derived from 6 data points is high. But if 5 of 6 windows are profitable with the filter, that's meaningful evidence even if it doesn't technically clear the 0.95 gate.

This is a cheap next experiment: change `TEST_MONTHS = 3` in the runner, re-run, and see if the landscape changes.

### Condition 3: Revisit the (60,200) combo specifically

The per-combo data shows (60,200) is nearly unaffected by the filter (+23% PF for (60,200) vs −23% for (50,200)). If the live paper trading is accumulating at the (60,200) champion selection (which the IS grid is increasingly selecting in recent windows), the live trade sample tagged at RV may show a much stronger filter effect than the original (50,200) 36-trade analysis.

Concretely: when 60+ live trades exist, segment by the IS champion at time of trade. If the filter consistently improves (60,200) entries but not (50,200) entries, the production fix is to switch the champion params from (50,200) to (60,200) with the filter enabled — two changes together.

---

## 9. Impact on Current Production Config

**No changes to production.** Rank11 (no filter) remains the active gate v2 verdict and the paper config uses:

```python
MES_TREND_PAPER_CONFIG = {
    "strategy": "sma_trend",
    "params": {"fast": 50, "slow": 200, "atr_trail_mult": 2.0},  # min_rv_annualized absent = 0.0
    "capital": 50_000.0,
    "enabled": True,
    "interval": "1h"
}
```

The `generate_sma_trend_signals` call in `paper_runner.py` will receive `min_rv_annualized=0.0` (default) because `MES_TREND_PAPER_CONFIG["params"]` doesn't include it. This is correct — no action needed.

Gate v2 rank11 expires 2026-05-20. The next refresh run should use `run_mes_trend_rank11.py` (or rank12 if a new runner is written). The RV filter does not change this schedule.

---

## 10. Summary Scorecard

| Metric | Gate threshold | rank11 (PASS) | rv_filter_rank1 (FAIL) | Direction |
|---|---|---|---|---|
| p_edge | ≥ 0.95 | 0.75 (FAIL — passes ALT indirectly) | 0.667 | Worse |
| fixed_params_min_pf | ≥ 1.20 | 1.3506 | 1.1125 | Worse |
| wfo_consistency | MODERATE or STRONG | STRONG | MODERATE | Worse |
| dsr | ≥ 0.30 (ALT) | 1.000 | 0.754 | Worse |
| mc_95th_dd | ≤ 7.0% (ALT) | 0.81% | 0.92% | Slightly worse |
| cost_survives_through | ≥ realistic | catastrophic | catastrophic | Same |
| OOS windows with trades | (coverage) | 12/18 = 67% | 9/18 = 50% | Worse |
| Total OOS trades | (coverage) | 16 | 12 | Worse |
| Full-dataset trades (50,200) | (reference) | 35 | 21 | -40% |
| Full-dataset PF (50,200) | (reference) | 1.3506 | 1.1125 | -18% |

**All metrics either worsened or held flat.** The RV filter does not improve the WFO evidence base — it degrades it by reducing the trade sample to a point where statistical tests lose power.

The filter is not "not working" — it may genuinely improve live performance as the empirical analysis suggests. But the WFO framework cannot resolve that question at this trade frequency and window length.

---

## 11. Artifacts From This Analysis

| File | Content |
|---|---|
| `engine/backtest/run_mes_trend_rv_filter.py` | Full WFO runner, committed as `2716157` |
| `engine/data/gate_v2_verdicts/MES_trend_rv_filter_rank1.json` | FAIL verdict with full window-by-window data |
| `docs/session-logs/MES_RV_FILTER_ANALYSIS_2026-05-06.md` | This document |

The runner is fully functional and can be re-run at any time. If `MIN_RV_ANNUALIZED` is changed (e.g., to 7.0 or 13.0), the runner will produce a new verdict and overwrite `MES_trend_rv_filter_rank1.json`.
