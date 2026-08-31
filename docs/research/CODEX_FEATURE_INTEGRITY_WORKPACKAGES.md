# Codex Work Packages — Feature Integrity → Judge V3 → Capital Path

Status: research planning only. These packages must not directly alter live trading authorization, broker settings, risk ceilings, or paper/live enablement.

## Operating model

Use Codex for bounded repository engineering where acceptance criteria can be verified by tests, static analysis, reproducible artifacts, or explicit diffs. Prefer one work package per branch/worktree. Human review remains mandatory before strategy/risk promotion or any live execution change.

The strongest Codex use cases in this project are:

- repository/codebase mapping and dependency tracing;
- repetitive source audits and parity fixtures;
- deterministic ports/refactors with strong tests;
- validation infrastructure and adversarial test generation;
- CI failures and regression diagnosis;
- documentation generated from code/source-of-truth schemas;
- research automation that produces evidence but does not authorize capital.

Codex should **not** own final live-trading authorization, strategy promotion, broker writes, or risk-limit changes.

---

## WP-01 — Execute and harden feature-integrity test suite

### Goal
Make PR #749's registry/scanner/Golden Vector/availability-contract tests executable and green under the repository's canonical environment.

### Scope
- `engine/tests/test_feature_registry_v2.py`
- `engine/tests/test_thinkscript_integrity_scan.py`
- `engine/tests/test_indicator_source_parity.py`
- `engine/tests/test_feature_availability.py`
- `engine/backtest/studies/source_parity.py`
- `engine/backtest/studies/feature_availability.py`

### Acceptance
From `engine/`:

```bash
.venv/bin/python -m pytest \
  tests/test_feature_registry_v2.py \
  tests/test_thinkscript_integrity_scan.py \
  tests/test_indicator_source_parity.py \
  tests/test_feature_availability.py -v

.venv/bin/ruff check \
  backtest/studies/source_parity.py \
  backtest/studies/feature_availability.py \
  tests/test_feature_registry_v2.py \
  tests/test_thinkscript_integrity_scan.py \
  tests/test_indicator_source_parity.py \
  tests/test_feature_availability.py --config ruff.toml
```

No production behavior changes.

### Codex suitability
**Excellent.** Bounded, testable, low-risk.

---

## WP-02 — Registry loader + typed FeatureDefinition model

### Goal
Turn `FEATURE_REGISTRY_V2.yaml` from a static artifact into a validated research API.

### Deliverables
- typed `FeatureDefinition` domain model;
- registry loader;
- enum validation;
- dependency/version lookup;
- deployment-eligibility checks;
- tests for malformed/unsafe registry entries.

### Non-goal
Do not wire it into live signal execution yet.

### Acceptance
- all existing registry schema tests pass;
- loader fails closed on invalid status combinations;
- no `live_allowed` feature can load if causal/parity/evidence requirements fail.

### Codex suitability
**Excellent.** Strong schema contract and clear tests.

---

## WP-03 — Point-in-time feature store prototype

### Goal
Create a research-only feature store/query layer enforcing:

```text
event_at <= available_at <= known_at <= decision_at
```

### Deliverables
- feature observation storage abstraction;
- latest-as-of query;
- version pinning;
- delayed-confirmation support;
- explicit `FeatureUnavailableError`;
- temporal property tests.

### Adversarial tests
Codex should generate cases for:
- ORB30 requested at 09:45;
- IB60 requested before 10:30;
- a news event published before ingestion;
- Singlefinder confirmation delayed one bar;
- higher-timeframe developing/completed bars;
- out-of-order ingest timestamps.

### Codex suitability
**Excellent.** Particularly useful for exhaustive edge-case test generation.

---

## WP-04 — ThinkScript corpus causal audit

### Goal
Run static audit across every unique ThinkScript and generate a reviewed machine-readable matrix.

### Tasks
- detect future references and chart globals;
- deduplicate nested TOS exports;
- categorize findings as cosmetic/display, delayed-confirmation, rewrite-required, or rejected;
- generate per-script Markdown report;
- update registry only with evidence-supported statuses.

### High-priority sources
1. Rangefinder v2
2. Singlefinder v2
3. Phase Oscillator
4. Calendar Edges
5. TPO/Profile family
6. multi-timeframe Keltner/CCI sources

### Codex suitability
**Very high**, but human review required for semantic rulings. Static detection can be automated; causal meaning cannot be inferred from syntax alone.

---

## WP-05 — Golden Vector parity expansion

### Goal
Create deterministic source-reference parity suites for all P0/P1 features.

### Order
1. ORB / Initial Balance
2. VWAP
3. Calendar signals (using exchange-calendar causal implementation)
4. Keltner 1.5x/2x/3x
5. TPO / POC / VAH / VAL
6. CCI trend state
7. Gapfinder

### Required outputs
For each feature:
- fixture data;
- source/reference vector;
- Python vector;
- tolerance/event-match contract;
- documented intentional divergences.

### Codex suitability
**Excellent**, especially in parallel worktrees — one agent per feature family.

---

## WP-06 — Judge V3 architecture

### Goal
Extend Gate v2 into an explicit research certification pipeline.

### Components
- point-in-time leakage gate;
- experiment/trial ledger;
- purged walk-forward validation;
- CPCV;
- final locked holdout;
- DSR/PBO integration using complete trial counts;
- parameter-plateau/stability metric;
- feature-family ablation;
- cost/slippage stress;
- regime robustness;
- edge-haircut scenarios;
- default-deny promotion policy.

### Codex use
Split into parallel implementation/review agents:
- Agent A: trial ledger/schema
- Agent B: CPCV/purging
- Agent C: parameter stability/ablation
- Agent D: adversarial validator tests
- Agent E: review only — look for leakage/metric mislabeling

### Safety
Codex may compute verdicts. It must not automatically flip live strategy authorization.

### Codex suitability
**High**, provided tasks are decomposed and an independent review agent evaluates each metric.

---

## WP-07 — Validation red-team harness

### Goal
Try to fool Judge V3 deliberately.

### Placebo/adversarial families
- randomized labels;
- future-shifted feature intentionally injected;
- selected-best-of-many noise strategies;
- nonstationary edge that exists only in first half;
- cost-fragile strategy;
- sparse strategy with giant outlier winner;
- correlated trades mislabeled independent;
- parameter needle/unstable optimum;
- gap-through-stop tail losses.

### Acceptance
The Judge must reject or explicitly downgrade these synthetic failure modes.

### Codex suitability
**Exceptional.** Generating adversarial cases and looking for validator blind spots is one of the highest-value uses of independent agents.

---

## WP-08 — Meta-label dataset builder

### Goal
Build a candidate-outcome dataset without allowing the ML model to invent trade geometry.

### Labels
- `hit_1r_before_stop`
- `hit_2r_before_stop`
- `hit_3r_before_stop`
- `mfe_r`
- `mae_r`
- `holding_minutes`
- `gap_through_stop`

### Features
Use only registry-approved, point-in-time observations available at candidate time.

### Codex suitability
**High** for ETL, labeling logic, leakage tests, and dataset lineage. Human/statistical review required before interpreting model performance.

---

## WP-09 — Baseline meta-models + feature ablation

### Goal
Establish simple baselines before deep models.

### Models
1. logistic regression;
2. gradient boosting;
3. optional random forest.

### Required analysis
- calibration;
- Brier/log loss;
- expected R by score decile;
- feature-family ablation;
- CPCV stability;
- regime-conditioned performance;
- cost-adjusted decision thresholds.

### Codex suitability
**High** for experiment automation and reproducibility. Do not let Codex cherry-pick the best result without the trial ledger recording every run.

---

## WP-10 — Sequence-Risk MC rename and semantic hardening

### Goal
Clarify that current permutation Monte Carlo is a historical trade-order/sequence-risk diagnostic, not the Capital Path forecast.

### Deliverables
- semantic naming/documentation;
- invariants proving final fixed-dollar PnL is permutation-invariant when no added costs exist;
- correct DD-tail labeling (`p95`/`p99` adverse tail);
- backward-compatible API if required.

### Codex suitability
**Excellent.** Well-bounded refactor/test task.

---

## WP-11 — Capital Path Engine V1

### Goal
Implement true dynamic compounding from R outcomes.

### Core transition

```text
risk_dollars = equity * risk_fraction
pnl = risk_dollars * realized_r
equity_next = equity + pnl
```

### V1 requirements
- milestones: 10k / 25k / 100k / 300k;
- first-passage times;
- ruin/soft-halt events;
- max DD and time underwater;
- day-level/bootstrap resampling;
- dynamic DD governor;
- edge haircut scenarios;
- deterministic seeds/path replay;
- convergence checks.

### Codex suitability
**High** for implementation/testing. Mathematical specification and risk objective should remain human-owned and independently reviewed.

---

## WP-12 — Capital Path model ensemble

### Goal
Compare IID, empirical/day bootstrap, moving block, stationary bootstrap, and regime-conditioned simulations.

### Output
Report model disagreement rather than hiding it.

### Codex suitability
**High** for parallel implementations and cross-checks. Have separate agents implement independent versions where possible.

---

## WP-13 — Robust risk-policy optimizer

### Goal
Search transparent risk policies using Capital Path success probability rather than backtest CAGR.

### Objective
Maximize approximately:

```text
P(target before ruin and within horizon)
```

subject to drawdown/heat constraints.

### Search dimensions
- base trade risk;
- drawdown multipliers;
- daily loss stop;
- portfolio heat;
- sector/factor heat;
- milestone deleveraging.

### Codex suitability
**Medium-high** for optimizer infrastructure and scenario generation. Final policy promotion must be human approved; never permit an agent to update live risk configuration from optimization output.

---

## WP-14 — Research observability/dashboard

### Goal
Make evidence visible.

### Screens
- Feature Integrity
- Parity
- Judge verdicts
- Experiment ledger
- Candidate/rejected counterfactuals
- Capital Path milestone funnel
- competing target/ruin curves
- DD distribution
- risk frontier
- edge-haircut sensitivity

### Codex suitability
**Excellent**, particularly for dashboard implementation from stable APIs and screenshot-based iteration.

---

## WP-15 — PR/CI continuous Codex review

### Recommended workflow
- keep Codex PR review enabled for research/validation code;
- explicitly request targeted reviews for:
  - look-ahead leakage;
  - statistical-metric semantics;
  - unit mismatch;
  - fail-open behavior;
  - live-trading blast radius;
  - test gaps;
- use a second agent to implement fixes, not the same reasoning context that authored the change when practical.

### Example review prompts

```text
@codex review this PR specifically for point-in-time leakage, hidden future references,
and any path that could promote a feature to paper/live without satisfying registry gates.
```

```text
@codex review the statistical semantics. Verify every metric name matches what is actually
computed, units are consistent, sparse samples fail closed, and no window-level aggregate
is mislabeled as a trade-level Monte Carlo statistic.
```

### Codex suitability
**Exceptional.** Independent review is especially important for validation code.

---

# Where Codex should have no autonomous authority

Codex may recommend or prepare a PR, but must not autonomously:

- merge a strategy/risk promotion into the live branch;
- enable live trading;
- alter broker credentials/accounts;
- submit/cancel real orders;
- raise risk-per-trade, portfolio-heat, or drawdown ceilings;
- mark statistical evidence `live_pass` based only on its own analysis;
- overwrite locked OOS/holdout datasets;
- delete failed experiments from the research ledger;
- reinterpret an unsafe source as causal merely to improve parity.

Use human approval and independent evidence for these transitions.

---

# Recommended parallel Codex topology

For the next phase, use 5 isolated agents/worktrees:

```text
Agent 1 — Test/CI hardening
Agent 2 — Feature registry loader + typed contracts
Agent 3 — ThinkScript causal audit
Agent 4 — ORB/IB/VWAP Golden Vectors
Agent 5 — Adversarial reviewer/red team
```

Do not have all five edit the same files. Integrate through small PRs after independent review.

# Definition of done for the current research branch

Before PR #749 can move from draft to ready-for-review:

1. focused feature-integrity tests pass;
2. ruff passes on new Python files;
3. registry V2 loads and governance tests pass;
4. Golden Vector intended-equivalence/non-equivalence tests pass;
5. point-in-time availability tests pass;
6. a Codex/human review finds no live execution path or risk-config mutation;
7. PR remains research-only unless a separate promotion decision is made.
