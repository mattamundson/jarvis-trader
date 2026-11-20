# JARVIS Morning Alpha — Historical Candidate Population & Validation Design

**Date:** 2026-09-15
**Status:** Approved design
**Scope:** Historical Candidate Population Builder and validation Levels 0–2 for the Relative Strength Sprint. Statistical inference, OOS/WFO, Monte Carlo, placebo/permutation, and Gate-v2 remain downstream.

## 1. Objective

Produce a deterministic, point-in-time-safe historical candidate population that can be trusted as the factual substrate for all later edge research.

The builder must reconstruct each historical morning exactly from information available by the canonical decision clock and must preserve both qualifying and rejected observations with immutable lineage.

Canonical decision clock:

- 09:00 America/New_York for each trading session.
- Inputs with `available_at > decision_timestamp` are forbidden.
- Same-day regular-session high/low/close/volume are forbidden at the morning decision.
- Prior completed daily bars, historical membership/classification, known corporate actions, and premarket data through 09:00 ET are allowed.

## 2. Non-Negotiable Rules

- Use certified research data only.
- Bind every candidate population to `data_manifest_hash`.
- Never reconstruct historical universes from current survivors.
- Never silently forward-fill missing benchmark sessions.
- Never drop duplicate candidates silently.
- Never duplicate strategy qualification logic in the builder; call the canonical detector.
- Historical feature computation must be invariant to appending future rows.
- All timestamps must be timezone-aware.
- Rejections are first-class research records.
- Exact candidate identity is `(strategy_version, stable_security_id, decision_timestamp)`.
- Same inputs must produce identical candidate IDs and population hash.

## 3. Components

### 3.1 `population.py`

Defines:

- `PopulationDecisionClock`
- `HistoricalSecurityRecord`
- `CandidateObservation`
- `CandidateRejection`
- `PopulationBuildResult`
- `HistoricalCandidatePopulationBuilder`

Responsibilities:

1. validate research readiness;
2. reconstruct the PIT universe at `decision_timestamp`;
3. apply historical security eligibility;
4. apply liquidity eligibility;
5. request feature snapshots;
6. call the canonical detector;
7. persist candidate/rejection lineage;
8. reject duplicates;
9. calculate a deterministic population hash.

### 3.2 `feature_builder.py`

Defines:

- `FeatureLineage`
- `HistoricalFeatureSnapshot`
- `HistoricalFeatureBuilder`

Required Relative Strength features:

- stock 20-session return;
- SPY 20-session return;
- sector ETF 20-session return;
- SMA20;
- SMA50;
- ATR14;
- prior session high;
- prior session low;
- prior close;
- 252-session high;
- 20-session average volume;
- 20-session average dollar volume.

Feature lineage must record:

- source symbol;
- start timestamp;
- end timestamp;
- latest available timestamp;
- data-manifest identity;
- deterministic feature hash.

The feature builder may not read any bar after the decision timestamp.

### 3.3 `validation.py`

Defines:

- `ValidationSeverity`
- `ValidationCode`
- `ValidationIssue`
- `PopulationValidationReport`
- `PopulationValidator`

Validation Levels 0–2:

#### Level 0 — dataset and run identity

Require:

- readiness report is READY;
- manifest hash exists;
- decision timestamp is timezone-aware;
- population records use one campaign/strategy version;
- source lineage hashes are present.

#### Level 1 — temporal and PIT integrity

Require:

- every lineage timestamp <= decision timestamp;
- listing date <= decision timestamp;
- delisting date null or > decision timestamp;
- historical sector effective at decision timestamp;
- benchmark endpoints match feature endpoints;
- no future-data leakage.

Any violation is fatal.

#### Level 2 — population integrity

Require:

- candidate IDs unique;
- rejected and qualified counts reconcile to processed eligible observations;
- deterministic population hash;
- no duplicated stable-security/date pair;
- no invalid benchmark alignment;
- no silently missing mandatory features.

### 3.4 `splits.py`

Defines:

- `SplitLabel`
- `TemporalSplit`
- `PurgedSplitAssignment`
- `PurgedTemporalSplitter`

Initial split API supports:

- development;
- validation;
- OOS;
- forward.

The splitter must:

- assign each candidate to at most one split;
- enforce non-overlapping date intervals;
- purge observations whose forward evaluation window crosses into the next split;
- apply an embargo measured in trading sessions.

Default maximum forward horizon for the current research program is 20 trading sessions, so split purging defaults to 20 sessions unless explicitly increased.

### 3.5 `candidate_store.py`

Defines:

- `CandidatePopulationManifest`
- `CandidatePopulationWriter`

The writer persists immutable research artifacts and a manifest including:

- campaign ID;
- strategy version;
- code commit;
- data manifest hash;
- candidate count;
- rejection count;
- candidate population hash;
- build start/end timestamps;
- decision-clock definition;
- output artifact SHA-256.

## 4. Candidate Identity

Candidate ID must be deterministic from:

```text
strategy canonical key
stable_security_id
decision timestamp UTC
```

Changing feature values does not create a second candidate identity for the same strategy/security/time; it creates a reproducibility failure if the same certified inputs yield different features.

## 5. Universe Reconstruction

A `HistoricalSecurityRecord` contains at least:

- stable security ID;
- symbol;
- listing timestamp;
- optional delisting timestamp;
- security type;
- primary exchange;
- historical sector;
- sector effective-from timestamp;
- optional sector effective-to timestamp;
- market-data timestamp;
- liquidity fields.

Eligibility requires:

- active at decision timestamp;
- historically eligible common stock or explicitly allowed ETF;
- historical sector valid at decision timestamp;
- no future market-data timestamp;
- existing Morning Alpha price/ADV/dollar-volume policy.

## 6. Benchmark Alignment

Relative Strength feature windows must use aligned endpoints.

For each candidate:

```text
stock_end == SPY_end == sector_end
```

If an endpoint is missing or misaligned, reject feature construction with `BENCHMARK_ALIGNMENT_FAILED`.

No automatic forward-fill is permitted.

## 7. Anti-Lookahead Invariance

For every feature family:

1. compute at historical `T`;
2. append absurd future rows after `T`;
3. recompute;
4. require exactly identical feature values and feature hash.

Mandatory coverage:

- returns;
- moving averages;
- ATR;
- 252-session high;
- volume averages;
- benchmark returns.

## 8. Rejection Accounting

Every processed security ends in exactly one terminal state:

- universe ineligible;
- liquidity rejected;
- insufficient history;
- benchmark alignment failed;
- mandatory feature missing;
- detector rejected;
- qualified candidate.

Counts must reconcile exactly.

The system may not discard unclassified records.

## 9. Repeatability

For identical:

- code commit;
- research manifest hash;
- campaign specification;
- decision-clock sequence;

two population builds must produce:

- identical candidate IDs;
- identical rejection identities;
- identical feature hashes;
- identical candidate count;
- identical rejection count;
- identical population hash.

A mismatch raises `NON_DETERMINISTIC_RESEARCH`.

## 10. Temporal Split Purity

Split boundaries are immutable research metadata.

Default example:

- Development: 2012-01-01 through 2018-12-31
- Validation: 2019-01-01 through 2021-12-31
- OOS: 2022-01-01 through 2025-12-31
- Forward: 2026-01-01 onward

Exact campaign dates may be updated before the real campaign begins, but once final OOS is viewed they must be frozen.

The API must support purging/embargo so long-horizon outcomes do not overlap split boundaries.

## 11. Validation Output

A population build emits a validation report with:

- level;
- fatal/nonfatal issue counts;
- issue codes;
- records examined;
- candidate count;
- rejection count;
- universe count;
- population hash;
- pass/fail.

No edge statistics are calculated at this layer.

## 12. Required Tests

Test-first implementation must cover:

1. timezone-aware decision clock;
2. active/inactive historical membership;
3. sector effective-date correctness;
4. future market-data rejection;
5. exact 20-session feature windows;
6. benchmark endpoint mismatch;
7. anti-lookahead feature invariance;
8. canonical detector parity;
9. deterministic candidate IDs;
10. duplicate candidate hard failure;
11. rejection accounting reconciliation;
12. deterministic population hash;
13. non-overlapping temporal splits;
14. purging of outcomes crossing split boundaries;
15. embargo behavior;
16. manifest/hash binding in output artifacts;
17. repeat-run identity;
18. negative fixtures that intentionally trigger temporal leakage.

## 13. Definition of Done

This milestone is complete when:

- a certified synthetic research dataset can produce a deterministic Relative Strength historical population;
- the same canonical detector used live is invoked;
- all Levels 0–2 validation tests pass;
- future rows cannot alter historical features/candidates;
- duplicates and accounting mismatches fail closed;
- purged temporal splits are deterministic;
- population artifacts are manifest/hash bound;
- no statistical edge inference is introduced;
- the complete existing Morning Alpha regression suite remains green.
