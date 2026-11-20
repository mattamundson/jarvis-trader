# Morning Alpha Statistical Validation L3-L5 Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden Morning Alpha Statistical Validation Levels 3-5 so uncertainty, concentration, and execution-survivability evidence are cluster-aware, reproducible, fail-closed, and explicitly non-promotional.

**Architecture:** Extend the existing `bootstrap.py`, `permutation.py`, `concentration.py`, `cost_break_even.py`, `statistical_validation.py`, and `statistical_report.py` modules rather than creating parallel implementations. All tests use immutable `MatchedEdgeObservation` inputs and deterministic seeds. `EVIDENCE_COMPLETE` means the requested analyses executed with sufficient sample structure; it never means strategy promotion or proven edge.

**Tech Stack:** Python 3.12+, Pydantic v2, stdlib statistics/random/hashlib, pytest.

**Spec:** `docs/superpowers/specs/2026-09-15-morning-alpha-statistical-validation-l3-l5-design.md`

## Global Constraints

- No strategy-rule or threshold changes in this milestone.
- No live-order capability.
- Preserve deterministic seeded output.
- Date-cluster inference is the primary inference surface; IID results are sensitivity-only.
- Preserve unfavorable/placebo outcomes.
- No optimizer or promotion verdict is added.
- All result bundles remain bound to candidate-population identity, data-manifest identity, control version, sample window, trial IDs, and spec.
- Missing execution evidence is invalid when execution analysis is declared.
- Existing 0/2/5/10/20 bps stress remains mandatory.

---

### Task 1: Strengthen cluster-aware inference and placebo nulls

**Files:**
- Modify: `engine/morning_alpha/research/permutation.py`
- Test: `engine/tests/morning_alpha/test_edge_cluster_permutation_v3.py`

**Interfaces:**
- Consumes: `MatchedEdgeObservation`
- Produces: cluster-aware sign-flip inference, cluster-aware placebo diagnostics, deterministic result identity.

- [ ] Write a failing test proving date clusters are sign-flipped as whole units and that a same-day correlated fixture produces a more conservative p-value than IID inference.
- [ ] Write a failing test proving the cluster-placebo operation preserves control marginal values and date-cluster membership counts while breaking candidate/control pairing.
- [ ] Run focused tests and confirm RED due to missing cluster-placebo/result fields.
- [ ] Implement minimal cluster-placebo result and cluster diagnostics.
- [ ] Re-run focused tests and confirm GREEN.
- [ ] Run existing permutation tests to confirm no regression.
- [ ] Commit.

### Task 2: Strengthen bootstrap evidence thresholds

**Files:**
- Modify: `engine/morning_alpha/research/bootstrap.py`
- Test: `engine/tests/morning_alpha/test_edge_bootstrap_v3.py`

**Interfaces:**
- Consumes: matched observations and cluster unit.
- Produces: confidence interval plus cluster diagnostics and stability metadata.

- [ ] Add failing tests for minimum distinct-cluster enforcement, deterministic date-cluster CI, and sector-cluster sensitivity.
- [ ] Add failing test proving duplicated same-day observations do not artificially create additional clusters.
- [ ] Implement explicit `cluster_sizes`, `effective_cluster_count`, and minimum-cluster validation.
- [ ] Verify focused tests.
- [ ] Verify prior bootstrap tests.
- [ ] Commit.

### Task 3: Expand concentration removal robustness

**Files:**
- Modify: `engine/morning_alpha/research/concentration.py`
- Test: `engine/tests/morning_alpha/test_edge_concentration_v3.py`

**Interfaces:**
- Consumes: matched observations.
- Produces: post-removal expectancy for top trades, symbols, sector, year, and regime plus contribution concentration.

- [ ] Add failing test for removal of strongest sector, strongest year, and strongest regime.
- [ ] Add failing test for top-1/top-5/top-10%-symbol removal when the removed groups contain both winners and losers.
- [ ] Add failing test that reports the fraction of original mean edge retained after each removal.
- [ ] Implement minimal retention metrics and removal diagnostics.
- [ ] Verify focused and existing concentration tests.
- [ ] Commit.

### Task 4: Harden execution break-even and realistic combined stress

**Files:**
- Modify: `engine/morning_alpha/research/cost_break_even.py`
- Test: `engine/tests/morning_alpha/test_edge_execution_survivability_v3.py`

**Interfaces:**
- Consumes: observations carrying gross R, cost-R-per-bps, ATR-slippage sensitivity, delay penalties and optional gap penalties.
- Produces: bps break-even, ATR-slippage break-even, fixed cost curve, delay curve and combined realistic-stress expectancy.

- [ ] Add failing test for exact cost break-even when per-trade bps conversion differs across trades.
- [ ] Add failing test for exact ATR-slippage break-even.
- [ ] Add failing test for combined realistic stress = cost + slippage + selected delay + gap penalties.
- [ ] Add failing test that missing declared evidence returns explicit invalid reasons instead of substituting zero.
- [ ] Implement minimal changes.
- [ ] Verify focused and existing execution tests.
- [ ] Commit.

### Task 5: Tighten statistical-validation bundle semantics

**Files:**
- Modify: `engine/morning_alpha/research/statistical_validation.py`
- Modify: `engine/morning_alpha/research/statistical_report.py`
- Test: `engine/tests/morning_alpha/test_statistical_validation_bundle_v3.py`
- Test: `engine/tests/morning_alpha/test_statistical_report_v3.py`

**Interfaces:**
- Consumes: all L3-L5 evidence.
- Produces: immutable validation bundle and non-promotional report.

- [ ] Add failing test that `EVIDENCE_COMPLETE` requires date-cluster bootstrap, date-cluster permutation, placebo, concentration, and declared execution evidence when execution inputs are supplied.
- [ ] Add failing test that insufficient cluster structure yields `INSUFFICIENT_DATA`, not `EVIDENCE_COMPLETE`.
- [ ] Add failing test that invalid execution evidence yields `INVALID`.
- [ ] Add failing test proving bundle ID changes when any evidence identity or validation spec changes.
- [ ] Add report tests for CI, cluster p-value, concentration retention, break-even cost/slippage, realistic combined R, sample/trial/data identity and the exact disclaimer `NOT A STRATEGY PROMOTION VERDICT`.
- [ ] Implement minimal bundle/report changes.
- [ ] Verify focused and existing bundle/report tests.
- [ ] Commit.

### Task 6: Golden L3-L5 validation and complete regression

**Files:**
- Create: `engine/tests/morning_alpha/test_statistical_validation_l3_l5_golden.py`
- Modify: `engine/docs/MORNING_ALPHA_RESEARCH_PROTOCOL.md`

**Interfaces:**
- Consumes: public L3-L5 interfaces.
- Produces: synthetic positive-evidence, null/placebo, concentrated-edge and execution-fragility golden scenarios.

- [ ] Add a positive synthetic fixture where date-cluster CI remains positive, cluster permutation is small, concentration survives removals and realistic execution remains positive.
- [ ] Add a null fixture where placebo/permutation does not support unusual edge.
- [ ] Add a concentration-fragile fixture where removing the strongest symbol or sector destroys expectancy.
- [ ] Add an execution-fragile fixture where raw edge is positive but realistic combined execution turns non-positive.
- [ ] Update protocol with L3/L4/L5 evidence hierarchy and explicit distinction between `EVIDENCE_COMPLETE`, Gate-v2 PASS and paper eligibility.
- [ ] Run focused L3-L5 verification.
- [ ] Run full Morning Alpha regression: `PYTHONPATH=. pytest tests/morning_alpha -q`.
- [ ] Run compile check: `python -m compileall -q morning_alpha`.
- [ ] Commit final protocol/golden test only after all verification passes.

## Definition of Done

- Primary uncertainty estimates are date-cluster aware.
- Placebo/permutation logic preserves cluster structure.
- Concentration analysis reports expectancy after removing dominant trades/groups and retention ratios.
- Execution analysis reports bps and ATR-slippage break-even plus combined realistic-stress expectancy.
- Validation bundle is deterministic and fail-closed on insufficient/invalid evidence.
- Reporting is explicitly non-promotional.
- Golden tests include positive, null, concentration-fragile, and execution-fragile cases.
- Full Morning Alpha regression and compile checks pass.
