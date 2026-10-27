# Morning Alpha Validation L6-L14 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Implement the post-L5 validation stack needed to make false discovery, overfitting, regime dependence, execution drift, and vendor-specific artifacts progressively harder to mistake for persistent edge.

**Architecture:** Add focused research modules under `engine/morning_alpha/research/` and preserve the existing canonical Gate-v2 adapter. Each level emits immutable evidence objects bound to strategy/data/population/trial identities. Later levels consume prior evidence but never rewrite it.

**Tech Stack:** Python 3.12+, Pydantic v2, stdlib statistics/random/hashlib/itertools, NumPy where already available, pytest.

**Spec:** `docs/superpowers/specs/2026-09-15-morning-alpha-validation-l6-l14-design.md`

## Global Constraints

- No strategy rule changes in this plan.
- No live-order capability.
- Final OOS cannot be used by tuning interfaces.
- WFO must purge/embargo overlapping labels.
- Monte Carlo primary paths resample date clusters/blocks, not IID trades.
- Gate-v2 remains `backtest.wfo_lifecycle.compute_gate_v2`; do not duplicate formulas.
- Paper signals are immutable before outcomes.
- Multiple-testing analyses consume the full trial ledger and preserve failures.
- Replication must record independent provider/data lineage.
- Edge-decay monitoring can halt paper strategies but cannot auto-promote them.

---

### Task 1 — L6 Locked Chronological OOS
**Files:** create `research/oos.py`; test `test_oos_lock.py`.
- Write RED tests for non-overlap, immutable parameter/data/population/trial hashes, one-way seal, and rejection of mismatched evaluation identity.
- Implement `OOSLockSpec`, `OOSLock`, `LockedOOSEvaluator`.
- Verify focused tests; run Morning Alpha regressions; commit.

### Task 2 — L7 Purged Rolling WFO
**Files:** create `research/walk_forward.py`; test `test_purged_wfo.py`.
- RED tests proving selector receives train only, evaluator receives test only, purge/embargo exclude boundary observations, and overlapping test observations are not double counted.
- Implement `WalkForwardSpec`, `WalkForwardFold`, `WalkForwardRunner`, `WalkForwardSummary`.
- Persist fold hashes and parameter identity; verify; commit.

### Task 3 — L8 Regime / Structural Robustness
**Files:** create `research/regime_robustness.py`; test `test_regime_robustness.py`.
- RED tests for minimum bucket N, worst/strongest bucket, leave-one-bucket-out expectancy, strongest-regime removal, and concentration flags.
- Implement generic dimension evaluator for regime/sector/year/symbol/vol bucket.
- Verify; commit.

### Task 4 — L9 Cluster-Aware Monte Carlo
**Files:** create `research/monte_carlo.py`; test `test_cluster_monte_carlo.py`.
- RED tests for deterministic seeds, date-cluster resampling, drawdown/loss-streak calculations, negative-terminal probability, and preservation of within-date correlation.
- Implement `MonteCarloSpec`, `MonteCarloSummary`, `run_cluster_monte_carlo`.
- Verify; commit.

### Task 5 — L10 Gate-v2 Evidence Gate
**Files:** modify `research/gate_v2_adapter.py`; test `test_gate_v2_evidence_gate.py`.
- RED tests preventing invocation unless L6-L9 evidence states are complete and identities match.
- Preserve canonical `compute_gate_v2` call exactly.
- Verify with injected gate function locally; repository canonical integration remains separate integrity check; commit.

### Task 6 — L11 Immutable Paper-Forward
**Files:** create `research/paper_forward.py`; test `test_paper_forward.py`.
- RED tests for pre-outcome immutable signal hash, separate outcome event, no retroactive entry/stop/target mutation, historical-vs-forward metric comparison, and paper sample minimums.
- Implement registry/evidence models; verify; commit.

### Task 7 — L12 Multiple-Testing / Data-Snooping Defenses
**Files:** create `research/multiple_testing.py`; test `test_multiple_testing.py`.
- RED tests for CSCV/PBO partitioning, OOS-rank/logit calculation, PBO bounds, block-bootstrap Reality-Check-style maximum statistic, SPA-style poor-model filtering, and multiplicity-adjusted family evidence.
- Implement deterministic pre-registered methods with explicit insufficient-data states; no production selection.
- Verify; commit.

### Task 8 — L13 Independent Replication / Shadow Comparison
**Files:** create `research/replication.py`; test `test_replication.py`.
- RED tests for candidate overlap, feature delta tolerances, provider-lineage independence, metric deltas, missingness, and shadow-signal divergence journal.
- Implement replay comparison and fail-closed independence checks; verify; commit.

### Task 9 — L14 Edge-Decay Monitor
**Files:** create `research/edge_decay.py`; test `test_edge_decay.py`; modify research protocol.
- RED tests for NORMAL/WATCH/DEGRADED/HALTED transitions, minimum sample size, cooldown, no single-loss transition, and explicit revalidation required after HALTED.
- Implement rolling evidence monitor with versioned thresholds and immutable transition events.
- Add golden cases: healthy, gradual decay, execution drift, abrupt deterioration.
- Run all L6-L14 focused tests, full `tests/morning_alpha`, compile check; commit.

## Definition of Done

- Locked final OOS is structurally unavailable to tuning.
- WFO uses purged/embargoed folds and prevents test leakage.
- Regime/structural fragility and leave-one-bucket-out sensitivity are explicit.
- Monte Carlo preserves cluster dependence.
- Gate-v2 cannot be invoked before prerequisite evidence.
- Paper-forward evidence is immutable and pre-outcome.
- PBO/CSCV plus bootstrap data-snooping defenses are available with insufficient-data safeguards.
- Independent-provider replication/shadow comparison is supported.
- Edge-decay monitoring can halt degraded paper strategies.
- Full Morning Alpha regression and compile checks pass.
