# Morning Alpha Statistical Validation Levels 3–5 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic paired permutation/placebo tests, cluster-aware bootstrap confidence intervals, concentration stress, execution-cost break-even, and immutable statistical evidence bundles without changing strategy rules.

**Architecture:** Normalize candidate/control outcomes into immutable `MatchedEdgeObservation` records. Independent modules compute permutation, bootstrap, concentration and cost diagnostics, and a final evidence bundle records identities/results without converting statistical evidence into a strategy promotion verdict.

**Tech Stack:** Python 3.12 standard library (`random`, `statistics`, `math`, `hashlib`, `json`), Pydantic v2, pytest.

**Spec:** `docs/superpowers/specs/2026-09-15-morning-alpha-statistical-validation-design.md`

## Global Constraints

- Canonical incremental edge is `strategy_return - control_return`.
- NaN/inf/missing required returns are rejected; never coerced to zero.
- Exact paired sign-flip enumeration is used for `n <= 20`.
- Monte Carlo paired sign-flip default is 10,000 permutations with deterministic seed and +1 p-value correction.
- Primary confidence interval is trading-date cluster bootstrap; IID is descriptive and sector clustering is optional sensitivity.
- Bootstrap default is 10,000 resamples with deterministic seed and 95% percentile interval.
- Concentration uses positive-edge contribution, not absolute-value contribution.
- Cost break-even uses `net_r = gross_r - cost_r_per_bps * bps`.
- `EVIDENCE_COMPLETE` is not a strategy PASS.
- No strategy detector/filter/threshold is changed.

---

### Task 1: Canonical matched-edge observations

**Files:**
- Create: `engine/morning_alpha/research/statistical_models.py`
- Test: `engine/tests/morning_alpha/test_statistical_models.py`

**Interfaces:**
- Produces `MatchedEdgeObservation` with candidate/date/symbol/sector/regime/strategy/control returns and optional gross-R/cost coefficient.
- Produces `.edge` property and deterministic `observation_hash`.

- [ ] Write failing tests for edge calculation, finite-value enforcement, timezone/date identity, deterministic hash and identity-sensitive hash changes.
- [ ] Run focused test and confirm RED.
- [ ] Implement minimal immutable Pydantic model.
- [ ] Run focused + full Morning Alpha suite.
- [ ] Commit `feat(morning-alpha): add matched edge observations`.

---

### Task 2: Paired permutation and placebo validation

**Files:**
- Create: `engine/morning_alpha/research/permutation.py`
- Test: `engine/tests/morning_alpha/test_edge_permutation.py`

**Interfaces:**
- Produces `PermutationMode`, `PairedPermutationResult`, `paired_edge_permutation(...)`.
- Produces deterministic `date_label_placebo(...)` helper returning permuted matched observations.

- [ ] Write RED tests for exact `2^n` enumeration, strong-positive edge significance, symmetric/no-edge non-significance, deterministic Monte Carlo seed, and deterministic placebo pairing.
- [ ] Implement exact sign enumeration for `n<=20`; seeded sign-flip Monte Carlo otherwise.
- [ ] Apply +1 correction in Monte Carlo p-values and report one-/two-sided values.
- [ ] Run focused/full tests and commit.

---

### Task 3: IID and cluster-aware bootstrap uncertainty

**Files:**
- Create: `engine/morning_alpha/research/bootstrap.py`
- Test: `engine/tests/morning_alpha/test_edge_bootstrap.py`

**Interfaces:**
- Produces `BootstrapClusterUnit`, `BootstrapResult`, `bootstrap_edge_ci(...)`.

- [ ] Write RED tests proving deterministic seeded IID bootstrap, whole-date cluster resampling, IID/cluster interval divergence on clustered data, CI crossing zero stays explicit, and fewer than 2 clusters fails closed.
- [ ] Implement percentile interval with deterministic resampling and fraction of bootstrap means `<=0`.
- [ ] Support DATE primary, SECTOR sensitivity and IID modes.
- [ ] Run focused/full tests and commit.

---

### Task 4: Concentration stress and cost break-even

**Files:**
- Create: `engine/morning_alpha/research/concentration.py`
- Create: `engine/morning_alpha/research/cost_break_even.py`
- Test: `engine/tests/morning_alpha/test_edge_stress.py`

**Interfaces:**
- Produces `ConcentrationReport`, `analyze_edge_concentration(...)`.
- Produces `CostBreakEvenReport`, `analyze_cost_break_even(...)`.

- [ ] Write RED tests for one-winner concentration, top-1/top-5/top-10% removal, symbol/sector/year contribution maps, known linear break-even solution, non-positive gross-R break-even=0, and missing/non-positive cost coefficients unavailable.
- [ ] Implement concentration on positive edge contributions and recompute mean edge after removals.
- [ ] Implement linear break-even/safety margin/net expectancy math.
- [ ] Run focused/full tests and commit.

---

### Task 5: Immutable statistical evidence bundle and report

**Files:**
- Create: `engine/morning_alpha/research/statistical_validation.py`
- Create: `engine/morning_alpha/research/statistical_report.py`
- Test: `engine/tests/morning_alpha/test_statistical_validation_bundle.py`

**Interfaces:**
- Produces `StatisticalEvidenceStatus` (`EVIDENCE_COMPLETE`, `INSUFFICIENT_DATA`, `INVALID`).
- Produces `StatisticalValidationBundle`, `build_statistical_validation_bundle(...)`.
- Produces `render_statistical_validation_report(bundle) -> str`.

- [ ] Write RED tests for complete bundle identity, insufficient cluster sample, identity change when population/data/trial IDs change, deterministic serialization, and report wording that never says `EDGE CONFIRMED` or strategy `PASS`.
- [ ] Build bundle from Tasks 1–4; require primary paired permutation + date-cluster bootstrap + concentration; cost report optional until triggered R evidence exists.
- [ ] Hash canonical bundle identity fields/results.
- [ ] Render explicit evidence sections and non-promotional conclusion.
- [ ] Run full `pytest tests/morning_alpha -q` and `python -m compileall -q morning_alpha`.
- [ ] Commit `feat(morning-alpha): add statistical edge validation bundle`.

## Plan Self-Review

- Spec coverage: matched observations, permutation/placebo, IID/date/sector bootstrap, concentration, cost break-even and immutable evidence bundling are all mapped to Tasks 1–5.
- Exact vs Monte Carlo thresholds and deterministic seeds are explicit.
- No optimizer, strategy mutation or promotion verdict is introduced.
- No placeholders remain.