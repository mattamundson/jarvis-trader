# JARVIS Morning Alpha — Historical Candidate Population & Validation Design

**Date:** 2026-09-15  
**Status:** Approved design  
**Scope:** Historical candidate population builder and validation Levels 0–2 for `relative_strength_breakout@1.0.0`, with interfaces that preserve later Levels 3–11 evidence.

## 1. Objective

Build a deterministic historical candidate-population pipeline that reconstructs what Morning Alpha could have known at the historical morning decision timestamp, generates Relative Strength candidates through the exact live detector, preserves every rejection and feature lineage record, and fails closed on temporal, universe, benchmark, duplicate, split, or manifest inconsistencies.

The milestone does **not** prove trading edge. It creates the population that later edge research is allowed to trust.

## 2. Canonical Decision Clock

For Sprint 1 the canonical historical decision timestamp is **09:00 America/New_York** on each trading session, matching the 08:00 America/Chicago Morning Trade Setups workflow.

At decision time `T`, allowed information includes:

- completed daily bars strictly before the current regular session;
- point-in-time listing/universe state effective at or before `T`;
- sector/classification records effective at or before `T`;
- corporate-action records available at or before `T`;
- premarket observations with timestamp `<= T`;
- earnings/catalyst information published at or before `T`;
- macro/event context known at or before `T`.

Forbidden information includes:

- regular-session bars from the current trading day after the decision boundary;
- current-day close/high/low/volume not known at `T`;
- future sector membership or symbol mapping;
- future corporate-action revisions;
- future earnings/news/catalyst timestamps;
- benchmark observations with endpoints later than the stock feature endpoint.

A detected violation is an error, not a silently discarded row.

## 3. Module Boundaries

Create focused modules under `engine/morning_alpha/research/`:

### `population.py`

Defines:

- `CandidateDecisionState` — `QUALIFIED` or `REJECTED`;
- `CandidateObservation` — immutable per-symbol/per-decision record;
- `PopulationBuildResult` — immutable session/campaign population result;
- `HistoricalCandidatePopulationBuilder` — orchestrates universe -> features -> existing detector -> observation.

The builder never re-implements Relative Strength rules.

### `feature_builder.py`

Defines:

- `FeatureInputLineage` — source timestamps and identities used by a feature;
- `HistoricalFeatureSnapshot` — values needed to create `InstrumentSnapshot` + `SetupContext`;
- `HistoricalFeatureBuilder` — calculates 20-session returns, SMA20/SMA50, ATR14, prior high/low, 252-session high, liquidity statistics, benchmark returns, and sector benchmark return using completed observations only.

### `validation.py`

Defines:

- `ValidationCode`;
- `ValidationIssue`;
- `PopulationValidationReport`;
- `PopulationValidator`.

The validator performs temporal, uniqueness, manifest, benchmark-alignment, accounting, and determinism checks.

### `splits.py`

Defines:

- `SplitKind` — DEVELOPMENT, VALIDATION, OOS, FORWARD;
- `TemporalSplit`;
- `PurgedTemporalSplit`;
- `SplitRegistry`.

Splits are immutable and mutually exclusive. Maximum research horizon is 20 trading sessions, therefore a 20-session purge/embargo discipline is the default around evaluation boundaries.

### `candidate_store.py`

Defines:

- `CandidatePopulationManifest`;
- `CandidatePopulationWriter`;
- deterministic content hashing for candidate population artifacts.

## 4. Candidate Identity and Record

Candidate identity is derived from:

```text
strategy canonical version
+ stable security ID
+ decision timestamp
```

Duplicate identity is a hard error.

Every observation preserves:

- candidate ID;
- campaign ID;
- strategy ID/version;
- decision timestamp and trading date;
- symbol and stable security ID;
- historical sector and sector ETF;
- price and prior completed close;
- 20-session stock/SPY/sector returns;
- RS vs SPY and RS vs sector;
- SMA20/SMA50;
- ATR14;
- prior high/low;
- 252-session high;
- 20-session average shares and dollar volume;
- detector proposed entry/stop when qualified;
- market-regime/sector context when supplied;
- detector state and rejection reason;
- universe snapshot hash;
- research data manifest identity;
- feature-set hash;
- source-lineage hash.

Rejected observations are first-class research records.

## 5. Validation Level 0 — Dataset / Manifest Integrity

Before population construction:

- certified research readiness must be true;
- candidate build must bind to a specific research-data manifest identity;
- all required artifacts must remain hash-valid under the existing research certification rules;
- malformed schemas/timestamps/duplicate rows are stop conditions when the artifact-quality layer is present.

Failure stops population construction.

## 6. Validation Level 1 — Temporal / PIT Correctness

Every feature lineage records the latest source timestamp used.

Require:

```text
latest_source_timestamp <= decision_timestamp
```

For completed daily features, require the latest daily bar to be strictly before the current regular session.

The validator emits hard errors such as:

- `TEMPORAL_LEAKAGE`;
- `FUTURE_UNIVERSE_RECORD`;
- `FUTURE_SECTOR_RECORD`;
- `FUTURE_CORPORATE_ACTION`;
- `FUTURE_CATALYST`.

Anti-lookahead invariant: adding data after decision timestamp `T` must not alter the serialized feature snapshot, candidate ID, detector result, or feature hash for `T`.

## 7. Validation Level 2 — Population / Feature Integrity

### 7.1 PIT universe

For every observation:

```text
listing_date <= decision timestamp
AND
(delisting_date is null OR delisting_date > decision timestamp)
```

Universe membership is keyed by stable security IDs rather than today's symbols.

Every session records a deterministic universe snapshot hash over sorted active stable IDs.

### 7.2 Feature lineage

Feature endpoints are explicit. For a decision on session D, stock/SPY/sector 20-session returns use matching completed-session endpoints; no current-day close may enter the feature.

### 7.3 Benchmark alignment

Stock, SPY, and sector return endpoints must match exactly. Misaligned endpoints produce `BENCHMARK_ALIGNMENT_FAILED`.

No invisible forward-fill is permitted.

### 7.4 Corporate actions

Raw bars remain separate from corporate-action evidence. Research adjustment policy must be deterministic and bound to the data-manifest/version identity. Future revisions cannot silently alter an earlier population without changing the research-data identity.

### 7.5 Detector parity

The builder creates `InstrumentSnapshot` and `SetupContext`, then calls the existing `RelativeStrengthBreakout.evaluate()` implementation. The historical builder contains no duplicate Relative Strength decision logic.

For identical snapshot/context input, serialized detector output must match direct live-style detector invocation.

### 7.6 Candidate uniqueness

Duplicate `(strategy version, stable security ID, decision timestamp)` is a hard `DUPLICATE_CANDIDATE` error. Never silently deduplicate.

### 7.7 Rejection accounting

For each decision session the result reconciles exact counts across:

- PIT universe;
- eligibility/liquidity rejection;
- insufficient-history rejection;
- feature/benchmark rejection;
- detector rejection;
- qualified candidates.

The arithmetic must reconcile to the input universe count.

## 8. Distribution Diagnostics

Before returns are inspected, population health summaries report candidate/rejection counts by:

- year/month;
- sector;
- symbol;
- regime when available;
- volatility/liquidity bucket when available.

These are descriptive diagnostics, not promotion metrics.

## 9. Temporal Splits and Purging

Split objects, not ad hoc date strings, define DEVELOPMENT, VALIDATION, OOS and FORWARD samples.

Required invariants:

- no date/candidate can belong to multiple splits;
- chronological ordering is strict;
- final OOS data is not exposed to parameter-selection interfaces;
- 20-session purge/embargo is the default for studies using the maximum 20-session forward horizon.

## 10. Research Repeatability

A population build records:

- code/strategy version;
- research data manifest identity;
- split registry identity;
- universe hashes;
- population hash;
- candidate count;
- rejection counts.

Unchanged inputs must reproduce the same candidate IDs, feature hashes, universe hashes and population hash. Mismatch yields `NON_DETERMINISTIC_RESEARCH`.

## 11. Negative Controls / Later Validation Interfaces

This milestone preserves interfaces for later validation Levels 3–11, including:

- label/date permutation placebo studies;
- bootstrap confidence intervals;
- cluster-aware inference by trading date/sector;
- concentration stress by symbol/sector/year/regime;
- cost break-even analysis;
- trigger/exit research;
- chronological OOS;
- purged rolling WFO;
- Monte Carlo;
- canonical Gate-v2;
- paper-forward confirmation.

Those later layers are not used to change the frozen v1 detector in this milestone.

## 12. Testing Requirements

Synthetic fixtures must prove at minimum:

1. future rows do not change prior features/candidates;
2. future universe membership cannot leak backward;
3. delisted securities are eligible before delisting and absent after;
4. historical sector membership is respected;
5. benchmark endpoints must align;
6. duplicate candidates fail closed;
7. rejection accounting reconciles exactly;
8. live/direct detector output equals builder detector output;
9. candidate IDs/hashes are deterministic;
10. split sets are disjoint;
11. purge/embargo removes overlap around boundaries;
12. manifest identity changes population identity;
13. malformed or uncertified research readiness blocks the build.

## 13. Definition of Done

This milestone is complete when:

- the historical population builder produces immutable qualified/rejected observations from certified point-in-time inputs;
- the exact existing Relative Strength detector is used;
- validation Levels 0–2 fail closed on all defined violations;
- split/purge interfaces exist and are tested;
- deterministic candidate/population hashes exist;
- candidate population artifacts can be persisted with a manifest;
- the complete Morning Alpha regression suite remains green locally;
- no claim of historical edge is made until the certified real data population is actually built and evaluated by the already-created edge-research framework;
- no live-order capability is introduced.
