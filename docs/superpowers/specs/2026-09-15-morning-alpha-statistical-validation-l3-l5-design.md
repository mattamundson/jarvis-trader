# JARVIS Morning Alpha — Statistical Validation Levels 3–5 Design

**Date:** 2026-09-15  
**Status:** Approved design  
**Scope:** Statistical Validation Levels 3–5 for Morning Alpha edge research.  
**Applies first to:** `relative_strength_breakout@1.0.0`, then reusable across later strategy families.

## 1. Objective

Move Morning Alpha from **correct historical reconstruction** to **credible statistical evidence** without turning statistical tooling into a strategy optimizer or promotion shortcut.

The system must answer three different questions separately:

1. **L3 — Statistical uncertainty:** Is the observed matched edge distinguishable from noise after respecting temporal/sector clustering?
2. **L4 — Concentration robustness:** Does the apparent edge survive removal of dominant trades, symbols, sectors, years, and regimes?
3. **L5 — Execution survivability:** How much spread/slippage/cost/delay degradation can the strategy absorb before net expectancy reaches zero?

`EVIDENCE_COMPLETE` means all required analyses ran on structurally sufficient data. It does **not** mean a strategy is promoted, approved, or proven.

## 2. Non-Negotiable Rules

- Statistical analysis consumes only candidate/control observations derived from certified PIT data.
- Every analysis is deterministic under an explicit seed where randomness is used.
- All matched-control tests preserve candidate/control pairing.
- Date clustering is the primary dependence correction because same-day signals share market shocks.
- Sector clustering is a sensitivity analysis, not a substitute for date clustering.
- Statistical methods may report negative, zero, or inconclusive evidence without coercion.
- No p-value, confidence interval, or robustness score may directly authorize paper/live promotion.
- Trial identities from the immutable research ledger remain part of the evidence bundle.
- No automatic "best threshold" or "best strategy" selector is introduced.
- Missing structural evidence fails closed as `INSUFFICIENT_DATA` or `INVALID`, never as a zero-valued metric.

## 3. Existing Components to Reuse

The existing research layer already contains:

- `MatchedEdgeObservation`
- IID/date/sector bootstrap support
- paired sign-flip permutation testing
- date-label placebo construction
- basic concentration analysis
- linear transaction-cost break-even analysis
- `StatisticalValidationBundle`
- non-promotional statistical report rendering

This milestone hardens and extends those modules instead of creating parallel implementations.

## 4. L3 — Statistical Inference

### 4.1 Primary estimand

For each matched observation:

```text
edge_i = strategy_return_i - control_return_i
```

The primary population estimand is the observation-weighted mean matched edge.

### 4.2 Bootstrap confidence intervals

Support:

- IID bootstrap — diagnostic only;
- trading-date cluster bootstrap — primary interval;
- sector cluster bootstrap — sensitivity interval.

Each bootstrap result must preserve:

- point estimate;
- lower/upper confidence bounds;
- confidence level;
- seed;
- resample count;
- observation count;
- cluster count;
- fraction of bootstrap means `<= 0`.

### 4.3 Minimum evidence structure

Introduce `StatisticalValidationSpec` with default structural floors:

```text
min_observations      = 200
min_date_clusters      = 30
min_sector_clusters    = 3
confidence             = 0.95
bootstrap_resamples    = 10_000
permutation_resamples  = 10_000
```

These are evidence-completeness requirements, not trading thresholds.

A bundle with fewer observations/date clusters is `INSUFFICIENT_DATA` even if the point estimate is favorable.

### 4.4 Date-cluster sign-flip permutation

The existing observation-level sign-flip test assumes observation-level exchangeability. Add a cluster-aware variant that flips **all observations from a trading date together**.

This becomes the primary randomization test for clustered signal populations.

Report:

- observed mean edge;
- one-sided p-value;
- two-sided p-value;
- permutation mode;
- number of clusters;
- seed;
- permutation count.

### 4.5 Placebo / negative-control diagnostic

Use deterministic label-shuffling to break candidate/control pairing while preserving the marginal control-return distribution.

Compute a placebo mean edge and record it separately. The placebo test is diagnostic; it must not be silently substituted for the main matched test.

### 4.6 Bootstrap method scope

Sprint v1 uses deterministic percentile bootstrap intervals. BCa/studentized intervals are explicitly deferred until real-data diagnostics show materially skewed or biased bootstrap distributions.

## 5. L4 — Concentration Robustness

### 5.1 Trade-level concentration

Retain:

- top-1 positive contribution share;
- top-5 positive contribution share;
- top-10%-of-trades positive contribution share;
- mean edge after removing top 1, top 5, top 10% positive trades.

### 5.2 Group-level concentration

Add recomputation after removing the strongest contributors by:

- symbol;
- sector;
- calendar year;
- market regime.

For each grouping report:

- strongest group key;
- strongest group total edge;
- strongest group positive-contribution share;
- mean edge after removing strongest group;
- sample count after removal.

### 5.3 Symbol concentration stress

Add:

- mean edge after removing strongest symbol;
- mean edge after removing top 5 symbols by aggregate positive contribution;
- mean edge after removing top 10% of symbols by aggregate positive contribution.

### 5.4 Concentration indices

For positive contributions compute Herfindahl-Hirschman-style concentration indices for:

- symbols;
- sectors;
- years;
- regimes.

These are descriptive diagnostics only.

### 5.5 Fail-closed semantics

If a requested removal would eliminate all observations, return `None` for the post-removal mean and preserve the reason in the report rather than manufacturing zero.

## 6. L5 — Execution Survivability

### 6.1 Cost break-even

Retain the exact linear solution for observation-specific cost coefficients:

```text
mean(gross_r_i - cost_r_per_bps_i * bps) = 0
```

which implies:

```text
break_even_bps = mean(gross_r) / mean(cost_r_per_bps)
```

when all coefficients are positive.

Report:

- gross mean R;
- mean R cost per bps;
- break-even bps;
- realistic cost assumption;
- safety margin in bps;
- net expectancy at realistic cost.

### 6.2 Fixed cost curve

Always compute the frozen cost curve:

```text
0 / 2 / 5 / 10 / 20 bps
```

using observation-specific cost conversion.

### 6.3 ATR-slippage stress

Extend execution evidence with optional `slippage_r_per_atr_fraction` per observation.

Pre-register stress fractions:

```text
0.00 / 0.02 / 0.05 / 0.10 ATR
```

Compute:

- expectancy R at each fraction;
- ATR-fraction break-even if coefficients are complete/positive;
- realistic ATR slippage margin.

### 6.4 Entry-delay stress

Allow optional per-observation delay penalties for:

```text
5s / 30s / 1m / 5m
```

Delay penalties must come from actual historical execution-path analysis, not guessed constants in production research.

The statistical engine only aggregates supplied penalties.

### 6.5 Combined realistic stress

Compute net expectancy under a declared combination:

```text
realistic_cost_bps
+ realistic_atr_slippage_fraction
+ selected delay scenario
```

If required coefficients are missing, combined stress is unavailable and the evidence bundle records the missing component.

### 6.6 Gap-through diagnostics

Add optional fields for entry/stop gap penalties. These remain descriptive in L5 and do not alter historical price paths. If missing, the report marks gap stress unavailable.

## 7. Statistical Evidence Bundle v2

Extend `StatisticalValidationBundle` to include:

- `StatisticalValidationSpec` identity;
- IID bootstrap;
- date-cluster bootstrap;
- sector-cluster bootstrap;
- IID paired permutation (diagnostic);
- date-cluster permutation (primary);
- placebo result;
- concentration report v2;
- execution stress report;
- evidence thresholds and structural counts;
- immutable candidate-population identity;
- data-manifest hash;
- control version;
- trial IDs;
- deterministic bundle hash.

### Status semantics

`EVIDENCE_COMPLETE` requires:

- `n >= min_observations`;
- date clusters `>= min_date_clusters`;
- date-cluster bootstrap available;
- date-cluster permutation available;
- concentration analysis available;
- execution analysis available when triggered-R execution inputs are declared present.

`INSUFFICIENT_DATA` covers structurally small samples/clusters.

`INVALID` covers inconsistent or malformed execution/statistical inputs.

No status means "strategy pass".

## 8. Reporting

Update the report sections to:

```text
STATISTICAL EVIDENCE IDENTITY
SAMPLE STRUCTURE
DATE-CLUSTER INFERENCE
IID / SECTOR SENSITIVITY
PLACEBO DIAGNOSTIC
CONCENTRATION ROBUSTNESS
EXECUTION SURVIVABILITY
TRIAL / DATA IDENTITY
RESEARCH STATUS
```

Explicitly print:

> This statistical evidence package is not a strategy promotion verdict.

## 9. Validation Tests

Required TDD cases:

### L3

- date-cluster permutation flips entire dates together;
- clustered significance differs from IID on a highly clustered fixture;
- deterministic seeds reproduce identical output;
- insufficient observations/date clusters block evidence completeness;
- placebo breaks pairing but preserves control-return marginals;
- negative edge remains negative and receives no favorable coercion.

### L4

- one large winner is exposed;
- one dominant symbol is exposed;
- one dominant sector/year/regime is exposed;
- removing dominant groups recomputes expectancy correctly;
- HHI-style concentration rises when contribution is concentrated;
- removal that empties sample returns unavailable rather than zero.

### L5

- fixed cost curve matches observation-level arithmetic;
- bps break-even solves mean net expectancy exactly;
- ATR break-even solves the corresponding linear system;
- delay stress uses supplied per-observation penalties;
- combined stress equals component penalties applied observation-by-observation;
- missing cost/slippage/delay evidence fails closed.

## 10. Non-Goals

This milestone does not:

- tune strategy thresholds;
- select a winning trigger;
- replace Gate-v2;
- run live/paper orders;
- claim a real historical edge without the certified corpus;
- implement PBO/CSCV or SPA/Reality Check yet;
- alter `relative_strength_breakout@1.0.0`.

## 11. Definition of Done

Levels 3–5 are complete when:

- cluster-aware inference is the primary uncertainty layer;
- placebo evidence is preserved separately;
- concentration robustness includes trade and group removals;
- execution survivability includes cost, ATR slippage, delay, and combined stress;
- structural evidence floors are enforced;
- bundle/report output remains explicitly non-promotional;
- focused tests and the complete Morning Alpha regression suite pass;
- no strategy-selection or live-order behavior is introduced.
