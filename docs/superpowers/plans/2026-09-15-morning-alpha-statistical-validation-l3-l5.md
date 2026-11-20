# Morning Alpha Statistical Validation Levels 3–5 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden Morning Alpha statistical evidence with cluster-aware inference, concentration robustness, and execution survivability without turning statistical analysis into a promotion verdict.

**Architecture:** Extend the existing `bootstrap.py`, `permutation.py`, `concentration.py`, `cost_break_even.py`, `statistical_models.py`, `statistical_validation.py`, and `statistical_report.py` modules. Date clustering becomes the primary dependence correction, group-removal stress expands concentration analysis, and execution stress aggregates observation-specific cost/slippage/delay coefficients. `StatisticalValidationBundle` remains immutable and evidence-only.

**Tech Stack:** Python 3.12+, Pydantic v2, stdlib `statistics`, deterministic `random.Random`, pytest.

**Spec:** `docs/superpowers/specs/2026-09-15-morning-alpha-statistical-validation-l3-l5-design.md`

## Global Constraints

- Do not modify `relative_strength_breakout@1.0.0` rules.
- Do not add strategy ranking, optimizer output, paper/live routing, or promotion shortcuts.
- Date-cluster inference is primary; IID inference is diagnostic only.
- Preserve negative and inconclusive results without clipping/coercion.
- Default evidence floors: `min_observations=200`, `min_date_clusters=30`, `min_sector_clusters=3`.
- Default resamples: `10_000` bootstrap and `10_000` permutation.
- Frozen cost curve: `0, 2, 5, 10, 20` bps.
- Frozen ATR slippage fractions: `0.00, 0.02, 0.05, 0.10`.
- Delay scenarios: `5s`, `30s`, `1m`, `5m`.
- Missing execution evidence is unavailable/invalid, never silently zero-filled.
- `EVIDENCE_COMPLETE` is not a strategy PASS.

---

### Task 1: Statistical evidence spec and execution-capable observation model

**Files:**
- Modify: `engine/morning_alpha/research/statistical_models.py`
- Modify: `engine/morning_alpha/research/statistical_validation.py`
- Test: `engine/tests/morning_alpha/test_statistical_validation_spec.py`

**Interfaces:**
- Consumes: existing `MatchedEdgeObservation`.
- Produces: `StatisticalValidationSpec`; optional execution fields on `MatchedEdgeObservation`.

- [ ] **Step 1: Write failing tests for structural floors and execution fields**

```python
def test_statistical_validation_spec_defaults_are_frozen():
    spec = StatisticalValidationSpec()
    assert spec.min_observations == 200
    assert spec.min_date_clusters == 30
    assert spec.min_sector_clusters == 3
    assert spec.cost_bps == (0, 2, 5, 10, 20)
    assert spec.atr_slippage_fractions == (0.0, 0.02, 0.05, 0.10)
    assert spec.delay_scenarios == ("5s", "30s", "1m", "5m")


def test_matched_observation_rejects_non_finite_execution_coefficients():
    with pytest.raises(ValueError, match="slippage_r_per_atr_fraction"):
        _row(slippage_r_per_atr_fraction=float("inf"))
```

- [ ] **Step 2: Run tests and verify RED**

Run:
```bash
cd engine
PYTHONPATH=. pytest tests/morning_alpha/test_statistical_validation_spec.py -v
```
Expected: import/attribute failures because new interfaces do not yet exist.

- [ ] **Step 3: Implement minimal immutable spec and model fields**

Add:

```python
class StatisticalValidationSpec(BaseModel):
    model_config = ConfigDict(frozen=True)
    min_observations: int = Field(default=200, gt=0)
    min_date_clusters: int = Field(default=30, gt=1)
    min_sector_clusters: int = Field(default=3, gt=1)
    confidence: float = Field(default=0.95, gt=0, lt=1)
    bootstrap_resamples: int = Field(default=10_000, gt=0)
    permutation_resamples: int = Field(default=10_000, gt=0)
    cost_bps: tuple[int, ...] = (0, 2, 5, 10, 20)
    atr_slippage_fractions: tuple[float, ...] = (0.0, 0.02, 0.05, 0.10)
    delay_scenarios: tuple[str, ...] = ("5s", "30s", "1m", "5m")
    realistic_bps: float = Field(default=5.0, ge=0)
    realistic_atr_slippage_fraction: float = Field(default=0.02, ge=0)
    realistic_delay_scenario: str = "30s"
```

Extend `MatchedEdgeObservation` with optional:

```python
slippage_r_per_atr_fraction: float | None = None
delay_penalty_r: dict[str, float] = Field(default_factory=dict)
entry_gap_penalty_r: float | None = None
stop_gap_penalty_r: float | None = None
```

Validate all numeric fields are finite and delay keys are non-empty.

- [ ] **Step 4: Run focused tests GREEN**
- [ ] **Step 5: Run existing statistical tests**

```bash
PYTHONPATH=. pytest -q \
  tests/morning_alpha/test_edge_bootstrap.py \
  tests/morning_alpha/test_edge_permutation.py \
  tests/morning_alpha/test_edge_stress.py \
  tests/morning_alpha/test_statistical_validation_bundle.py \
  tests/morning_alpha/test_statistical_validation_spec.py
```

- [ ] **Step 6: Commit**

```bash
git add morning_alpha/research/statistical_models.py morning_alpha/research/statistical_validation.py tests/morning_alpha/test_statistical_validation_spec.py
git commit -m "feat(morning-alpha): add statistical evidence specification"
```

---

### Task 2: Date-cluster permutation and placebo evidence

**Files:**
- Modify: `engine/morning_alpha/research/permutation.py`
- Test: `engine/tests/morning_alpha/test_edge_cluster_permutation.py`

**Interfaces:**
- Produces: `ClusterPermutationResult`, `date_cluster_edge_permutation`, `PlaceboResult`, `evaluate_date_label_placebo`.

- [ ] **Step 1: Write failing tests**

```python
def test_date_cluster_permutation_flips_whole_dates_together():
    result = date_cluster_edge_permutation(clustered_rows(), seed=11, permutations=1000)
    assert result.cluster_unit == "date"
    assert result.n_clusters == 4


def test_cluster_permutation_differs_from_iid_on_same_day_clustered_fixture():
    iid = paired_edge_permutation(clustered_rows(), seed=5, permutations=5000)
    clustered = date_cluster_edge_permutation(clustered_rows(), seed=5, permutations=5000)
    assert clustered.two_sided_p != iid.two_sided_p


def test_placebo_preserves_control_marginal_but_breaks_pairing():
    result = evaluate_date_label_placebo(placebo_rows(), seed=9)
    assert sorted(result.placebo_control_returns) == sorted(result.original_control_returns)
    assert result.placebo_mean_edge != result.original_mean_edge
```

- [ ] **Step 2: Verify RED**
- [ ] **Step 3: Implement date-cluster sign flipping**

Group observations by `trading_date`; each permutation assigns one sign to each date cluster and applies that sign to every edge in the date. Exact enumeration is allowed only when cluster count `<= exact_max_clusters`; otherwise deterministic Monte Carlo.

- [ ] **Step 4: Implement explicit placebo result**

Persist original/placebo means, seed, original/placebo control arrays, and observation count. Do not convert the placebo into a verdict.

- [ ] **Step 5: Run focused tests GREEN**
- [ ] **Step 6: Run existing permutation tests**
- [ ] **Step 7: Commit**

```bash
git commit -am "feat(morning-alpha): add cluster-aware permutation evidence"
```

---

### Task 3: Concentration robustness v2

**Files:**
- Modify: `engine/morning_alpha/research/concentration.py`
- Test: `engine/tests/morning_alpha/test_edge_concentration_v2.py`

**Interfaces:**
- Produces: `GroupConcentrationStress`; enhanced `ConcentrationReport`.

- [ ] **Step 1: Write failing tests for group removal and HHI**

```python
def test_dominant_symbol_removal_recomputes_mean_edge():
    report = analyze_edge_concentration(symbol_dominated_rows())
    assert report.symbol_stress.strongest_group == "BIG"
    assert report.symbol_stress.mean_after_remove_strongest < 0


def test_sector_year_and_regime_removals_are_reported():
    report = analyze_edge_concentration(grouped_rows())
    assert report.sector_stress.strongest_group == "Technology"
    assert report.year_stress.strongest_group == "2024"
    assert report.regime_stress.strongest_group == "bull"


def test_positive_hhi_is_higher_for_concentrated_contributions():
    assert analyze_edge_concentration(concentrated()).symbol_hhi > analyze_edge_concentration(diffuse()).symbol_hhi
```

- [ ] **Step 2: Verify RED**
- [ ] **Step 3: Implement group stress helper**

For each grouping aggregate total edge, rank only positive-contribution groups for removal, then recompute observation-level mean after removing the selected group(s). Preserve unavailable means as `None`.

- [ ] **Step 4: Implement symbol top-1/top-5/top-10%-groups removals**
- [ ] **Step 5: Implement positive-contribution HHI per grouping**
- [ ] **Step 6: Run focused + legacy concentration tests GREEN**
- [ ] **Step 7: Commit**

---

### Task 4: Execution survivability engine

**Files:**
- Create: `engine/morning_alpha/research/execution_stress.py`
- Modify: `engine/morning_alpha/research/cost_break_even.py`
- Test: `engine/tests/morning_alpha/test_execution_stress.py`

**Interfaces:**
- Consumes: `MatchedEdgeObservation`, `StatisticalValidationSpec`.
- Produces: `ExecutionStressReport`, `analyze_execution_stress`.

- [ ] **Step 1: Write failing tests**

```python
def test_cost_curve_uses_per_observation_coefficients():
    report = analyze_execution_stress(rows(), spec=spec())
    assert report.cost_curve_r[0] == pytest.approx(expected_0)
    assert report.cost_curve_r[20] == pytest.approx(expected_20)


def test_atr_break_even_solves_mean_net_zero():
    report = analyze_execution_stress(slippage_rows(), spec=spec())
    assert report.break_even_atr_fraction == pytest.approx(expected)


def test_delay_stress_aggregates_supplied_penalties():
    report = analyze_execution_stress(delay_rows(), spec=spec())
    assert report.delay_curve_r["30s"] == pytest.approx(expected)


def test_combined_realistic_stress_applies_all_penalties_per_observation():
    report = analyze_execution_stress(full_rows(), spec=spec())
    assert report.combined_realistic_r == pytest.approx(expected)
```

- [ ] **Step 2: Verify RED**
- [ ] **Step 3: Implement fixed bps curve and preserve current exact bps break-even**
- [ ] **Step 4: Implement ATR slippage curve and linear break-even**
- [ ] **Step 5: Implement delay and gap diagnostics**
- [ ] **Step 6: Implement combined realistic stress**

Return explicit availability/reason fields when required data is missing.

- [ ] **Step 7: Run focused + legacy cost tests GREEN**
- [ ] **Step 8: Commit**

---

### Task 5: Statistical evidence bundle v2 and structural gates

**Files:**
- Modify: `engine/morning_alpha/research/statistical_validation.py`
- Test: `engine/tests/morning_alpha/test_statistical_validation_bundle_v2.py`

**Interfaces:**
- Consumes: L3/L4/L5 outputs and `StatisticalValidationSpec`.
- Produces: enhanced immutable `StatisticalValidationBundle`.

- [ ] **Step 1: Write failing tests for evidence floors**

```python
def test_favorable_small_sample_is_insufficient_not_complete():
    bundle = build_statistical_validation_bundle(observations=positive_rows(50), spec=StatisticalValidationSpec())
    assert bundle.status is StatisticalEvidenceStatus.INSUFFICIENT_DATA
    assert "OBSERVATIONS_BELOW_MINIMUM" in bundle.reasons


def test_date_clusters_below_floor_are_insufficient():
    bundle = build_statistical_validation_bundle(observations=many_rows_few_dates(), spec=StatisticalValidationSpec())
    assert "DATE_CLUSTERS_BELOW_MINIMUM" in bundle.reasons


def test_complete_bundle_contains_cluster_permutation_placebo_concentration_execution():
    bundle = build_statistical_validation_bundle(observations=complete_rows(), spec=small_test_spec())
    assert bundle.date_cluster_permutation is not None
    assert bundle.placebo is not None
    assert bundle.concentration is not None
    assert bundle.execution_stress is not None
```

- [ ] **Step 2: Verify RED**
- [ ] **Step 3: Wire L3–L5 analyses into bundle**
- [ ] **Step 4: Enforce structural status semantics**
- [ ] **Step 5: Include spec and all evidence in deterministic bundle identity**
- [ ] **Step 6: Run focused/legacy bundle tests GREEN**
- [ ] **Step 7: Commit**

---

### Task 6: Statistical report v2

**Files:**
- Modify: `engine/morning_alpha/research/statistical_report.py`
- Test: `engine/tests/morning_alpha/test_statistical_report_v2.py`

**Interfaces:**
- Consumes: enhanced `StatisticalValidationBundle`.
- Produces: deterministic text report.

- [ ] **Step 1: Write failing section-order test**

Require exactly these major headings in order:

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

- [ ] **Step 2: Verify RED**
- [ ] **Step 3: Render primary cluster inference before IID sensitivity**
- [ ] **Step 4: Render group-removal concentration and execution curves/break-even margins**
- [ ] **Step 5: Preserve explicit non-promotional statement**
- [ ] **Step 6: Run focused/legacy report tests GREEN**
- [ ] **Step 7: Commit**

---

### Task 7: Golden negative/clustered statistical fixtures

**Files:**
- Create: `engine/tests/morning_alpha/test_statistical_validation_golden.py`

**Interfaces:**
- Exercises Levels 3–5 end-to-end using synthetic evidence only.

- [ ] **Step 1: Add clustered false-confidence fixture**

Construct many same-date positive observations with few independent dates; assert IID evidence looks narrower than date-cluster evidence and the bundle obeys the cluster floor.

- [ ] **Step 2: Add negative-edge fixture**

Assert negative point estimate/CI remains negative and no report language contains `PASS`, `EDGE CONFIRMED`, or equivalent promotion language.

- [ ] **Step 3: Add dominant-symbol fixture**

Assert raw edge is positive but turns non-positive after strongest-symbol removal.

- [ ] **Step 4: Add execution-fragility fixture**

Assert raw gross R is positive but combined realistic stress is non-positive.

- [ ] **Step 5: Run all L3–L5 tests**

```bash
PYTHONPATH=. pytest -q \
 tests/morning_alpha/test_edge_bootstrap.py \
 tests/morning_alpha/test_edge_permutation.py \
 tests/morning_alpha/test_edge_cluster_permutation.py \
 tests/morning_alpha/test_edge_stress.py \
 tests/morning_alpha/test_edge_concentration_v2.py \
 tests/morning_alpha/test_execution_stress.py \
 tests/morning_alpha/test_statistical_validation_spec.py \
 tests/morning_alpha/test_statistical_validation_bundle.py \
 tests/morning_alpha/test_statistical_validation_bundle_v2.py \
 tests/morning_alpha/test_statistical_report_v2.py \
 tests/morning_alpha/test_statistical_validation_golden.py
```

- [ ] **Step 6: Commit**

---

### Task 8: Full regression and protocol update

**Files:**
- Modify: `engine/docs/MORNING_ALPHA_RESEARCH_PROTOCOL.md`
- Modify: `engine/morning_alpha/research/__init__.py`

- [ ] **Step 1: Export new public research interfaces**
- [ ] **Step 2: Document L3–L5 evidence hierarchy and non-promotion semantics**
- [ ] **Step 3: Run complete Morning Alpha suite**

```bash
cd engine
PYTHONPATH=. pytest tests/morning_alpha -q
python -m compileall -q morning_alpha
```

- [ ] **Step 4: Run repository checks if available**

```bash
ruff check morning_alpha tests/morning_alpha
python scripts/check_gate_v2_integrity.py
```

If tooling/full-repo files are unavailable, record the blocker explicitly rather than claiming success.

- [ ] **Step 5: Commit and update PR #847 evidence**

The PR must distinguish local subsystem evidence from authoritative repository CI evidence.
