# JARVIS Morning Alpha — Statistical Validation Levels 3–5 Design

**Date:** 2026-09-15  
**Status:** Approved under the previously approved 20-level validation architecture  
**Scope:** Statistical validation of matched incremental edge after a candidate population has passed Levels 0–2. This milestone does not change any strategy rule.

## 1. Objective

Determine whether observed Morning Alpha incremental performance is distinguishable from chance, quantify uncertainty under clustered trade observations, expose concentration fragility, and estimate execution-cost safety margin before OOS/WFO/Gate-v2 promotion work.

This milestone consumes already-validated candidate/control outcomes. It does **not** create or tune strategy signals.

## 2. Canonical Matched Observation

Define immutable `MatchedEdgeObservation` with:

- candidate ID;
- decision/trading date;
- symbol;
- sector;
- optional regime;
- strategy return;
- matched-control return;
- optional gross trade R;
- optional `cost_r_per_bps` linear friction coefficient.

The canonical incremental edge is:

```text
edge_i = strategy_return_i - control_return_i
```

Missing/non-finite returns are rejected before inference; they are never converted to zero.

## 3. Level 3 — Paired Permutation / Placebo Validation

Because strategy and control observations are matched at the same decision timestamp, the primary null test is a paired sign-flip permutation of `edge_i`.

### Exact mode

For `n <= 20`, enumerate all `2^n` sign assignments and compute the null distribution of mean paired edge exactly.

### Monte Carlo mode

For larger `n`, use deterministic seeded sign-flip permutations with a pre-registered default of 10,000 permutations.

Report:

- observed mean edge;
- observed median edge;
- sample size;
- null mean/std;
- one-sided p-value for positive edge;
- two-sided p-value;
- percentile rank of observed statistic;
- exact/Monte-Carlo mode;
- seed and permutation count.

The +1 correction is used for Monte Carlo p-values:

```text
p = (extreme_count + 1) / (permutations + 1)
```

A test result is evidence, not a promotion verdict.

## 4. Negative / Placebo Controls

Support placebo studies where strategy/control pairing is deliberately broken using deterministic date-label permutation. A healthy pipeline should not systematically produce strong positive edge under placebo assignments.

Persist placebo trial identity in the existing immutable trial ledger.

## 5. Level 4 — Bootstrap Confidence Intervals

Implement deterministic percentile bootstrap confidence intervals for mean incremental edge.

### IID bootstrap

Resample individual observations with replacement. This is descriptive only because signals can cluster.

### Trading-date cluster bootstrap — primary

Group all observations by trading date, sample whole date clusters with replacement, and include all observations belonging to sampled dates.

This preserves same-day cross-sectional dependence and is the primary uncertainty estimate for Morning Alpha selection edge.

### Sector cluster sensitivity

Optionally repeat using sector clusters as a sensitivity analysis when enough sectors exist.

Report:

- point estimate;
- lower/upper confidence bounds;
- confidence level (default 95%);
- resample count (default 10,000);
- seed;
- cluster unit;
- number of observations;
- number of clusters;
- fraction of bootstrap means <= 0.

A result with a confidence interval crossing zero remains uncertain; the code must not silently convert it to PASS/FAIL.

## 6. Determinism and Small-Sample Rules

- All Monte Carlo/bootstrap routines require explicit or default frozen seeds.
- Identical observations + seed + configuration produce byte-equivalent serialized results.
- Empty samples raise a validation error.
- Cluster bootstrap requires at least 2 distinct clusters.
- Sector sensitivity is unavailable rather than fabricated when fewer than 2 sectors exist.
- Extremely small samples are reported with explicit sample-size metadata; they are not promoted by this layer.

## 7. Level 5A — Concentration Stress

Measure whether apparent edge is dominated by a small subset.

For matched edge observations calculate:

- total/mean incremental edge;
- contribution by symbol;
- contribution by sector;
- contribution by calendar year;
- contribution by regime when present;
- top-1 contributor share of positive edge;
- top-5 contributor share where sample permits;
- top-10%-of-observations contribution share;
- recomputed mean edge after removing top 1 positive observation;
- recomputed mean edge after removing top 5 positive observations where available;
- recomputed mean edge after removing top 10% positive observations.

Do not use absolute-value contributions when measuring positive-edge concentration: the diagnostic asks how much of gross positive edge comes from the largest winners.

The report is descriptive and may show negative/zero results.

## 8. Level 5B — Cost Break-Even

For triggered trade research, model net trade R under a linear per-bps friction coefficient:

```text
net_r_i(bps) = gross_r_i - cost_r_per_bps_i * bps
```

Mean break-even friction is therefore the non-negative solution of:

```text
mean(net_r_i(bps)) = 0
```

which simplifies to:

```text
break_even_bps = mean(gross_r) / mean(cost_r_per_bps)
```

when the average coefficient is positive.

Report:

- gross mean R;
- mean friction coefficient;
- break-even bps;
- configured realistic bps;
- safety-margin bps (`break_even - realistic`);
- net expectancy at realistic bps.

If gross mean R <= 0, break-even is 0 and the system must not manufacture a positive safety margin.

If cost coefficients are missing/non-positive, break-even is unavailable and validation fails closed for execution-survival claims.

## 9. Statistical Evidence Bundle

Define immutable `StatisticalValidationBundle` containing:

- control identity/version;
- sample interval;
- matched observation count;
- paired permutation result;
- primary date-cluster bootstrap result;
- optional IID/sector sensitivity bootstrap results;
- concentration report;
- optional cost-break-even report;
- data-manifest hash;
- candidate-population identity;
- trial IDs.

The bundle may have status:

- `EVIDENCE_COMPLETE` — all required Level 3–5 evidence exists;
- `INSUFFICIENT_DATA` — sample/cluster requirements not met;
- `INVALID` — malformed/non-finite/mismatched evidence.

`EVIDENCE_COMPLETE` is **not** a strategy PASS.

## 10. Verification Requirements

Synthetic tests must prove:

1. paired sign-flip test detects a strong positive synthetic edge;
2. paired sign-flip test does not invent significance for symmetric/no-edge data;
3. exact mode enumerates the expected number of sign assignments;
4. seeded Monte Carlo results are deterministic;
5. future/unrelated observations are not read by the statistical layer;
6. date-cluster bootstrap resamples whole date clusters rather than individual rows;
7. IID and cluster intervals can differ on clustered fixtures;
8. confidence intervals crossing zero remain explicitly uncertain;
9. concentration stress exposes a one-winner strategy;
10. removing top contributors recomputes edge correctly;
11. break-even cost is mathematically correct on known fixtures;
12. non-positive gross expectancy yields zero break-even;
13. malformed NaN/inf returns are rejected;
14. evidence bundle identity changes when population/data/trial identity changes;
15. identical inputs/seed reproduce identical serialized output.

## 11. Definition of Done

This milestone is complete when paired permutation/placebo inference, cluster-aware bootstrap uncertainty, concentration stress, cost break-even and immutable evidence bundling are implemented/tested without changing any strategy rule, and the full Morning Alpha local regression suite remains green.

No historical edge claim is permitted until these methods are run on a real population that already passed validation Levels 0–2.