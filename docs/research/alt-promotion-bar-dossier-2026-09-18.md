# ALT / promotion bar — decision dossier (2026-09-18)

Round 3, task 2. **Decision document, not a measurement.** Evidence here was produced by the audit
tool (`engine/backtest/audit_verdict_artifacts.py`, PR #867), the deflation work (PRs #872/#873) and
the ledger fix (PR #879). Nothing in this file changes a gate; the change it recommends is yours to
approve.

## The decision

Should the ALT promotion path require the **campaign-count** DSR (`dsr_campaign ≥ 0.30`), rather than
the runner's own grid-count DSR it uses today?

Why it is live: the ALT conjunction is
`dsr ≥ GATE_DSR_ALT(0.30) ∧ wfo ∈ {MODERATE,STRONG} ∧ fixed_params_min_pf ≥ 1.20 ∧ cost_passes ∧
mc_95th_dd ≤ 0.04` — it references `dsr`, and `dsr` is deflated against the **runner's own grid
size**, not the campaign count. Every verdict therefore satisfies that term more easily than its
evidence supports.

## Measured fact that forces the question

For the one candidate with a runnable analysis (`MES_trend_vix_pctile_rank1`, the only *live*
verdict), on the repaired ledger:

| deflation basis | trials | DSR | vs 0.30 floor |
|---|---|---|---|
| runner grid count (archived verdict, pre-ledger-fix) | 4 | 0.9752 | passes |
| runner grid count (replayed on the repaired ledger) | 4 | 0.9705 | passes |
| campaign count (derived, deduped) | 214 | **0.1815** | **fails** |

And the cliff is steep, measured on the same return series **post-ledger-fix**:

`0.9705 @4 → 0.933 @9 → 0.8135 @25 → 0.676 @50 → 0.454 @100 → 0.210 @200 → 0.0225 @500`

(pre-fix the same sweep read `0.977 @4 → 0.9475 @9 → … → 0.210 @200`; the ledger correction lowered
it slightly throughout, and at the campaign count it fell further, 0.2642 → 0.1815.)

So the ALT path is currently granting PASS on a number that collapses by ~0.75 when deflated
honestly. That is not a bug in the gate — it is the gate measuring the wrong quantity.

## The case FOR requiring `dsr_campaign ≥ 0.30`

1. **It measures what the program claims to measure.** The promotion question is "would this survive
   the search that produced it?" — a campaign-level question, not a per-runner-grid one. Deflating
   against the search that a single runner happened to perform systematically overstates evidence.
2. **Precedent: this exact defect already destroyed a promotion.** MGC's 2026-05-24 gate-v2 PASS was
   invalidated on 2026-08-01 when DSR was recomputed at the true combined-campaign trial count and
   collapsed to ~0 (PR #529), leading to halt (PR #691). The program has already paid for this once.
3. **The honest number is cheap to compute now.** `campaign_trial_count()` derives it from the
   artifact store, deduped by content hash (PR #872), and every verdict already records both bases
   (PR #873). The cost of compliance is one permutation run, not new infrastructure.
4. **It is the conservative direction.** The derived count is a **lower bound** — unlogged
   experiments can only raise it, making deflation stricter. A method whose error is one-sided
   toward caution is the right shape for a promotion gate.

## The case AGAINST

1. **Nine of ten recorded PASSes cannot be evaluated.** They store `dsr` but not the return series
   needed to recompute it at the campaign count. Enforcing the bar retroactively would reclassify
   verdicts on a number nobody can produce without re-running each candidate — i.e. classifying by
   assumption, which is the very failure this program spent a day removing.
2. **The derived count is a proxy, not a truth.** It sums grid-combo counts across distinct
   artifacts. A grid combo is not an independent hypothesis, so the count may overstate the
   effective search (multiple combos of one idea are correlated). Overstating trials deflates harder
   than warranted — an error in the conservative direction, but still an error.
3. **It would fail-close the only live strategy on a metric with a known proxy error.** MES paper
   routing fail-closes on `INSUFFICIENT_SAMPLE`, and `dsr_campaign` is currently report-only. Making
   it binding changes live behaviour on a number whose derivation is documented but approximate.
4. **Sequencing.** The ledger fix moved these numbers once already (0.2642 → 0.1815 on this
   candidate). Changing the bar before the remaining candidates are re-measured risks a second
   reclassification wave.

## FLIP LIST — what changes under each option

From the audit (10 recorded PASSes, 9 ALT-path):

| artifact | via | p_edge | recorded dsr | trials deflated at | campaign DSR | flips to FAIL? |
|---|---|---|---|---|---|---|
| `MES_trend_vix_pctile_rank1` *(live)* | alt | 0.5926 | 0.9752 | 4 | **0.1815** | **YES** |
| `MES_trend_rank11_deep-2026-08-17-refresh` | **core** | 0.9968 | 0.9861 | 3 | not evaluable | unknown |
| `MES_trend_rank11_pre-refresh-2026-05-06` | alt | 0.75 | 1.0 | 3 | not evaluable | unknown |
| `MES_trend_rank11_pre-refresh-2026-05-20` | alt | 0.75 | 1.0 | 3 | not evaluable | unknown |
| `MGC_trend_rank4_pre-refresh-2026-05-06` | alt | 0.75 | 1.0 | 8 | not evaluable | unknown |
| `MGC_trend_rank4_pre-refresh-2026-05-20` | alt | 0.6842 | 1.0 | 8 | not evaluable | unknown |
| `MGC_trend_rv_filter_rank1` ×3 *(identical bytes)* | alt | 0.625 | 0.8868 | 3 | not evaluable | unknown |
| `MES_trend_rank7` | alt | *(absent)* | *(absent)* | — | not evaluable | unknown |

"Not evaluable" means the artifact stores `dsr` but not the trade-level return series, so the
campaign-count value **cannot be produced without re-running the candidate**. Enforcing retroactively
would mean asserting nine classifications from data that does not exist.

Context for the unknowns: every one of them was deflated at **3–8 trials**, and the one candidate
measured at both ends of that range collapsed from ~0.98 to ~0.21. None of the nine is *known* to
survive; none can be *shown* to fail from the artifact.

## Recommendation

**Apply the campaign-count requirement prospectively now; defer any retroactive reclassification
until each legacy PASS has been re-run.**

Concretely:
1. **Immediately**: require `dsr_campaign ≥ 0.30` for any **new** verdict. This costs nothing
   retroactively — new verdicts already record the number (PR #873) — and stops the defect
   compounding.
2. **Do not** retroactively reclassify the nine unevaluable PASSes. They are not evidence of edge
   either; label them `unverifiable-at-campaign-count` in the trust register (round-3 task 3) so
   nobody quotes them as certified.
3. **Re-run** `MES_trend_rank11` and the MGC candidates on the repaired ruler (tasks 4 and 6). Each
   re-run either produces a campaign DSR that passes, or converts an "unknown" into a measured FAIL.
   Only then is retroactive enforcement a measurement rather than an assumption.
4. **Keep the derived count's limits visible**: report `basis` and `caveat` with the number (already
   the case), and revisit the proxy if a true trial ledger is built.

This keeps the one-sided-conservative direction, avoids reclassifying on non-existent data, and
converts nine assumptions into nine measurements over time. The alternative — wiring the bar
retroactively today — would fail-close the live strategy *and* silently reclassify nine verdicts on a
number none of them contains.

## What would change this recommendation

- A true campaign trial ledger (content-addressed, append-only) making `n_trials` a fact rather than
  a deduped proxy → then retroactive enforcement becomes legitimate for candidates recorded after the
  ledger exists, but still not for the legacy nine.
- Evidence that grid combos in the derived count are strongly correlated within a candidate → the
  proxy overstates trials, and the bar should perhaps be enforced at a count derived per-candidate
  rather than symbol-wide.
