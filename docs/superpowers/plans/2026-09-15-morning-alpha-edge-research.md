# Morning Alpha Edge Research Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a research layer that can isolate Relative Strength selection/timing/exit/filter edge against point-in-time controls before any production promotion decision.

**Architecture:** Add focused modules under `engine/morning_alpha/research/` for controls, forward-return horizons, excursion curves, attribution, ablation, robustness and immutable trial accounting. A Relative Strength sprint orchestrator composes these modules but reuses the existing detector, trigger lab, data-readiness gate and Gate-v2 adapter; no backtest-only strategy logic is introduced.

**Tech Stack:** Python 3.12, Pydantic v2, existing Morning Alpha domain models/providers, pytest, standard library statistics/hash/random utilities.

**Spec:** `docs/superpowers/specs/2026-09-15-morning-alpha-edge-research-design.md`

## Global Constraints

- Only certified point-in-time data may execute real research.
- `relative_strength_breakout@1.0.0` remains frozen during Sprint 1.
- Controls use only the eligible historical universe at the decision timestamp.
- Random controls are deterministic under an explicit seed.
- Forward-return/MFE/MAE calculations cannot read beyond their requested horizon.
- Future rows added to a source must not change earlier observations.
- Every experiment receives an immutable trial identity; failed trials remain in the ledger.
- No ML or automatic optimizer is used in Sprint 1.
- Canonical repository Gate-v2 remains the promotion authority.
- No live-order capability is introduced.

---

### Task 1: Point-in-Time Control Groups

**Files:**
- Create: `engine/morning_alpha/research/controls.py`
- Create: `engine/tests/morning_alpha/test_research_controls.py`
- Modify: `engine/morning_alpha/research/__init__.py`

**Interfaces:**
- Produces `ControlKind`, `UniverseMember`, `ControlObservation`, `ControlSelector`.
- `ControlSelector.select(candidate, universe, sector_etf, seed_namespace) -> tuple[ControlObservation, ...]`.
- Consumes candidate symbol/as_of/sector and a caller-supplied PIT universe; it does not query today's universe itself.

- [ ] **Step 1: Write deterministic/PIT failure tests**

Tests must prove:

```python
selected_a = selector.select(candidate, universe, sector_etf="XLK", seed_namespace="sprint1")
selected_b = selector.select(candidate, universe, sector_etf="XLK", seed_namespace="sprint1")
assert selected_a == selected_b
assert all(row.as_of == candidate.as_of for row in selected_a)
```

Also assert a universe member with `effective_from > candidate.as_of` or `effective_to <= candidate.as_of` is never selected, and a missing same-sector pool yields an explicit unavailable control rather than future backfill.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
cd engine
PYTHONPATH=. pytest tests/morning_alpha/test_research_controls.py -v
```

Expected: collection/import failure because `morning_alpha.research.controls` does not exist.

- [ ] **Step 3: Implement immutable control models and deterministic selection**

Use SHA-256 of `seed_namespace + candidate.strategy.canonical + candidate.symbol + candidate.as_of.isoformat() + control_kind` to seed `random.Random`.

Required `ControlKind` values:

```python
RANDOM_UNIVERSE
RANDOM_SAME_SECTOR
NEXT_OPEN
SPY
SECTOR_ETF
```

`UniverseMember` must contain `symbol`, `sector`, `effective_from`, `effective_to`, `eligible` and validate timezone-aware timestamps.

- [ ] **Step 4: Run focused tests and verify GREEN**

```bash
PYTHONPATH=. pytest tests/morning_alpha/test_research_controls.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add morning_alpha/research/controls.py morning_alpha/research/__init__.py tests/morning_alpha/test_research_controls.py
git commit -m "feat(morning-alpha): add point-in-time research controls"
```

---

### Task 2: Forward-Return Horizon Engine

**Files:**
- Create: `engine/morning_alpha/research/forward_returns.py`
- Create: `engine/tests/morning_alpha/test_forward_returns.py`
- Modify: `engine/morning_alpha/research/__init__.py`

**Interfaces:**
- Produces `ForwardHorizon`, `ForwardReturnObservation`, `ForwardReturnEngine`.
- `ForwardReturnEngine.measure(symbol, decision_time, entry_price, bars, horizons) -> tuple[ForwardReturnObservation, ...]`.

- [ ] **Step 1: Write horizon/anti-lookahead tests**

Use synthetic intraday/daily bars to assert:

```python
obs = engine.measure("XYZ", decision, 100.0, bars, (ForwardHorizon.MIN_30, ForwardHorizon.DAY_1))
assert obs[0].end_timestamp <= decision + timedelta(minutes=30)
```

Add future bars beyond a tested horizon and assert the earlier observation is unchanged.

- [ ] **Step 2: Verify RED**

```bash
PYTHONPATH=. pytest tests/morning_alpha/test_forward_returns.py -v
```

- [ ] **Step 3: Implement pre-registered horizons**

Support:

```text
30m, 60m, EOD, 1d, 2d, 3d, 5d, 10d, 20d
```

Every observation records start/end timestamps, start/end prices, simple return, availability status and horizon identifier. Never interpolate through a missing bar; use the latest eligible bar at/before the horizon boundary and mark unavailable if no eligible endpoint exists.

- [ ] **Step 4: Verify GREEN and full anti-lookahead behavior**

```bash
PYTHONPATH=. pytest tests/morning_alpha/test_forward_returns.py -q
```

- [ ] **Step 5: Commit**

```bash
git add morning_alpha/research/forward_returns.py morning_alpha/research/__init__.py tests/morning_alpha/test_forward_returns.py
git commit -m "feat(morning-alpha): add forward-return horizon engine"
```

---

### Task 3: Horizon MFE/MAE Excursion Curves

**Files:**
- Create: `engine/morning_alpha/research/excursions.py`
- Create: `engine/tests/morning_alpha/test_excursion_curves.py`
- Modify: `engine/morning_alpha/research/__init__.py`

**Interfaces:**
- Produces `ExcursionHorizon`, `ExcursionObservation`, `ExcursionCurve`, `ExcursionEngine`.
- `ExcursionEngine.measure(plan, entry_timestamp, bars) -> ExcursionCurve`.

- [ ] **Step 1: Write entry-slicing and horizon tests**

Construct a pre-entry session high that would inflate MFE and prove it is ignored. Verify 30m/60m/EOD/1d/2d/3d/5d observations cannot incorporate bars beyond their horizon.

- [ ] **Step 2: Verify RED**

```bash
PYTHONPATH=. pytest tests/morning_alpha/test_excursion_curves.py -v
```

- [ ] **Step 3: Implement long/short R excursion math**

For a long plan:

```python
mfe_r = (max_high_after_entry - entry) / risk_per_share
mae_r = (min_low_after_entry - entry) / risk_per_share
```

For a short plan use the symmetric inverse. Derived curve summary supports probabilities later but this task only emits deterministic per-trade observations.

- [ ] **Step 4: Verify GREEN**

```bash
PYTHONPATH=. pytest tests/morning_alpha/test_excursion_curves.py -q
```

- [ ] **Step 5: Commit**

```bash
git add morning_alpha/research/excursions.py morning_alpha/research/__init__.py tests/morning_alpha/test_excursion_curves.py
git commit -m "feat(morning-alpha): add excursion horizon curves"
```

---

### Task 4: Transparent Edge Attribution

**Files:**
- Create: `engine/morning_alpha/research/attribution.py`
- Create: `engine/tests/morning_alpha/test_edge_attribution.py`
- Modify: `engine/morning_alpha/research/__init__.py`

**Interfaces:**
- Produces `EdgeAttribution`, `EdgeAttributionEngine`.
- `EdgeAttributionEngine.attribute(strategy_return, next_open_return, sector_return, market_return, exit_adjustment=0, filter_adjustment=0) -> EdgeAttribution`.

- [ ] **Step 1: Write reconciliation tests**

Require:

```python
result = engine.attribute(0.43, 0.19, 0.10, 0.04)
assert result.total_increment == pytest.approx(0.39)
assert sum(result.components.values()) == pytest.approx(result.total_increment)
```

Test negative selection/timing edge as well; attribution must not clip unfavorable components.

- [ ] **Step 2: Verify RED**

```bash
PYTHONPATH=. pytest tests/morning_alpha/test_edge_attribution.py -v
```

- [ ] **Step 3: Implement transparent counterfactual decomposition**

Define:

```text
market contribution      = market return
sector increment         = sector return - market return
selection increment      = next-open same-stock return - sector return
timing increment         = strategy return - next-open same-stock return
exit/filter adjustments  = caller-supplied explicit counterfactual deltas
residual                 = reconciliation remainder
```

Store raw counterfactuals in the result for audit.

- [ ] **Step 4: Verify GREEN**

```bash
PYTHONPATH=. pytest tests/morning_alpha/test_edge_attribution.py -q
```

- [ ] **Step 5: Commit**

```bash
git add morning_alpha/research/attribution.py morning_alpha/research/__init__.py tests/morning_alpha/test_edge_attribution.py
git commit -m "feat(morning-alpha): add transparent edge attribution"
```

---

### Task 5: Ablation Variants

**Files:**
- Create: `engine/morning_alpha/research/ablation.py`
- Create: `engine/tests/morning_alpha/test_ablation.py`
- Modify: `engine/morning_alpha/research/__init__.py`

**Interfaces:**
- Produces `AblationKind`, `AblationResult`, `AblationRunner`.
- Runner accepts an injected evaluator so it does not fork detector implementation.

- [ ] **Step 1: Write isolation tests**

Assert the runner passes exactly one ablation label at a time and never mutates the original strategy key or candidate object.

- [ ] **Step 2: Verify RED**

```bash
PYTHONPATH=. pytest tests/morning_alpha/test_ablation.py -v
```

- [ ] **Step 3: Implement diagnostic variants**

Supported labels:

```text
FULL
FULL_MINUS_SECTOR_FILTER
FULL_MINUS_VOLUME_CONFIRMATION
FULL_MINUS_REGIME_FILTER
FULL_MINUS_ENTRY_CONFIRMATION
```

The module stores variant identity and evaluator outputs only; detector-specific logic remains in the evaluator/sprint orchestrator.

- [ ] **Step 4: Verify GREEN and commit**

```bash
PYTHONPATH=. pytest tests/morning_alpha/test_ablation.py -q
git add morning_alpha/research/ablation.py morning_alpha/research/__init__.py tests/morning_alpha/test_ablation.py
git commit -m "feat(morning-alpha): add research ablation framework"
```

---

### Task 6: Immutable Research Trial Ledger

**Files:**
- Create: `engine/morning_alpha/research/trial_ledger.py`
- Create: `engine/tests/morning_alpha/test_trial_ledger.py`
- Modify: `engine/morning_alpha/research/__init__.py`

**Interfaces:**
- Produces `TrialStatus`, `ResearchTrial`, `InMemoryTrialLedger`.
- Trial IDs are deterministic hashes of immutable experiment identity fields, not mutable result metrics.

- [ ] **Step 1: Write identity/failure-preservation tests**

Prove identical experiment identity generates the same trial ID, changing trigger/ablation/cost changes the ID, and a failed result remains queryable after later successful trials.

- [ ] **Step 2: Verify RED**

```bash
PYTHONPATH=. pytest tests/morning_alpha/test_trial_ledger.py -v
```

- [ ] **Step 3: Implement ledger**

Required identity fields:

```text
campaign_id
strategy_key
control_version
trigger_version
exit_version
ablation_kind
parameter_fingerprint
cost_bps
data_manifest_hash
sample_start
sample_end
```

Record status, sample size, output hash/path and error separately from the ID.

- [ ] **Step 4: Verify GREEN and commit**

```bash
PYTHONPATH=. pytest tests/morning_alpha/test_trial_ledger.py -q
git add morning_alpha/research/trial_ledger.py morning_alpha/research/__init__.py tests/morning_alpha/test_trial_ledger.py
git commit -m "feat(morning-alpha): add immutable research trial ledger"
```

---

### Task 7: Parameter Stability / Plateau Diagnostics

**Files:**
- Create: `engine/morning_alpha/research/robustness.py`
- Create: `engine/tests/morning_alpha/test_parameter_robustness.py`
- Modify: `engine/morning_alpha/research/__init__.py`

**Interfaces:**
- Produces `ParameterPoint`, `ParameterStabilityReport`, `analyze_parameter_stability(points)`.

- [ ] **Step 1: Write broad-plateau vs spike tests**

A smooth sequence such as `[0.28, 0.31, 0.34, 0.33, 0.31]` must score more stable than `[0.02, 0.04, 0.48, -0.01, 0.03]` with equal sample sizes.

- [ ] **Step 2: Verify RED**

```bash
PYTHONPATH=. pytest tests/morning_alpha/test_parameter_robustness.py -v
```

- [ ] **Step 3: Implement diagnostic metrics**

Compute adjacent expectancy dispersion, maximum neighbor drop, positive-neighbor fraction and sample-size floor. Do not emit a recommended parameter value.

- [ ] **Step 4: Verify GREEN and commit**

```bash
PYTHONPATH=. pytest tests/morning_alpha/test_parameter_robustness.py -q
git add morning_alpha/research/robustness.py morning_alpha/research/__init__.py tests/morning_alpha/test_parameter_robustness.py
git commit -m "feat(morning-alpha): add parameter stability diagnostics"
```

---

### Task 8: Relative Strength Sprint Orchestrator

**Files:**
- Create: `engine/morning_alpha/research/relative_strength_sprint.py`
- Create: `engine/tests/morning_alpha/test_relative_strength_sprint.py`
- Modify: `engine/morning_alpha/research/__init__.py`

**Interfaces:**
- Produces `RelativeStrengthSprintInput`, `RelativeStrengthSprintReport`, `RelativeStrengthResearchSprint`.
- Composes existing data readiness, detector outputs, control selector, forward-return engine, trigger lab, excursion engine, attribution, ablation, robustness and trial ledger.

- [ ] **Step 1: Write fail-closed and synthetic happy-path tests**

Test that uncertified data returns/raises a blocked result before any control evaluator is invoked. Synthetic certified fixtures must generate a report whose strategy key is exactly `relative_strength_breakout@1.0.0` and whose control sample counts are explicit.

- [ ] **Step 2: Verify RED**

```bash
PYTHONPATH=. pytest tests/morning_alpha/test_relative_strength_sprint.py -v
```

- [ ] **Step 3: Implement orchestration without optimizer behavior**

Sprint stages:

```text
validate readiness
freeze strategy key
construct PIT controls
measure raw forward returns
measure excursions
run frozen trigger comparisons
run caller-supplied exit evaluations
run ablations
compute attribution
record every trial
emit report
```

The sprint may return `INSUFFICIENT_DATA` or `FAIL`; it must never infer PASS from missing stages.

- [ ] **Step 4: Verify GREEN**

```bash
PYTHONPATH=. pytest tests/morning_alpha/test_relative_strength_sprint.py -q
```

- [ ] **Step 5: Commit**

```bash
git add morning_alpha/research/relative_strength_sprint.py morning_alpha/research/__init__.py tests/morning_alpha/test_relative_strength_sprint.py
git commit -m "feat(morning-alpha): add relative strength research sprint"
```

---

### Task 9: Research Reporting / CLI

**Files:**
- Create: `engine/morning_alpha/reporting/edge_research_report.py`
- Create: `engine/tests/morning_alpha/test_edge_research_reporting.py`
- Modify: `engine/morning_alpha/cli.py`
- Modify: `engine/morning_alpha/reporting/__init__.py`

**Interfaces:**
- Produces `render_edge_research_report(report) -> str`.
- Adds CLI command `research-relative-strength` that refuses to run unless `research-data-check` would be READY.

- [ ] **Step 1: Write output/NO-DATA tests**

Require report sections:

```text
SAMPLE / CONTROLS
RAW FORWARD RETURNS
SELECTION ALPHA
TRIGGER COMPARISON
MFE / MAE
EXIT STUDY
ABLATIONS
REGIME / ROBUSTNESS
COST / OOS / WFO
TRIAL COUNT
GATE V2
CONCLUSION
```

- [ ] **Step 2: Verify RED**

```bash
PYTHONPATH=. pytest tests/morning_alpha/test_edge_research_reporting.py -v
```

- [ ] **Step 3: Implement renderer/CLI contract**

The CLI may report `BLOCKED` or `INSUFFICIENT_DATA` with exit code 2; it may not print an edge verdict when required stages are absent.

- [ ] **Step 4: Verify GREEN and commit**

```bash
PYTHONPATH=. pytest tests/morning_alpha/test_edge_research_reporting.py -q
git add morning_alpha/reporting/edge_research_report.py morning_alpha/reporting/__init__.py morning_alpha/cli.py tests/morning_alpha/test_edge_research_reporting.py
git commit -m "feat(morning-alpha): add edge research reporting"
```

---

### Task 10: Full Regression and Synthetic Edge-Decomposition Golden Test

**Files:**
- Create: `engine/tests/morning_alpha/test_edge_research_golden.py`
- Modify: `engine/docs/MORNING_ALPHA_RESEARCH_PROTOCOL.md`

**Interfaces:**
- Golden fixture validates all new modules compose without changing v1 strategy rules.

- [ ] **Step 1: Build synthetic golden fixture**

Construct a fixture where the Morning Alpha candidate intentionally outperforms market/sector controls and where a delayed next-open entry is worse than the frozen trigger. Assert attribution identifies positive selection and timing increments and reconciles exactly.

- [ ] **Step 2: Add anti-edge fixture**

Construct a second fixture where the candidate underperforms the sector control. Assert the system reports negative incremental selection edge rather than coercing it positive.

- [ ] **Step 3: Run complete Morning Alpha suite**

```bash
cd engine
PYTHONPATH=. pytest tests/morning_alpha -q
python -m compileall -q morning_alpha
```

Expected: zero failures and compile exit 0.

- [ ] **Step 4: Update research protocol**

Document the five control groups, attribution semantics, trial-ledger requirement, ablation versioning and robustness plateau rule.

- [ ] **Step 5: Commit**

```bash
git add tests/morning_alpha/test_edge_research_golden.py docs/MORNING_ALPHA_RESEARCH_PROTOCOL.md
git commit -m "test(morning-alpha): add edge decomposition golden research fixture"
```

---

## Execution / Review Gates

1. Tasks 1-3 establish unbiased observations before interpretation.
2. Tasks 4-7 establish attribution and statistical research hygiene.
3. Task 8 composes Sprint 1 but cannot promote a strategy.
4. Task 9 exposes results without converting missing evidence into a verdict.
5. Task 10 is the regression gate before any real certified-data run.

## Real-Data Handoff

After all tasks pass synthetically, stop if certified historical data is still unavailable. Do not substitute current web quotes or survivorship-biased free data. Once issue #849 is resolved, run `research-data-check`, then execute Relative Strength Sprint 1 exactly once against the frozen final OOS block before any v1 changes.
