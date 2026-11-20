# Morning Alpha Verification-of-Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add independent statistical conformance, adversarial corruption tests, placebo diagnostics, realistic execution replay, and immutable verification receipts around the existing L0-L14 Morning Alpha validation stack.

**Architecture:** Add four focused research modules plus a receipt/orchestrator. The new layer consumes existing immutable research artifacts and never mutates strategy logic. SciPy/NumPy are reference dependencies for conformance only; execution replay is deterministic and fail-closed on missing quote evidence.

**Tech Stack:** Python 3.12+, Pydantic v2, SciPy 1.17+, NumPy, statsmodels metadata, pytest.

**Spec:** `docs/superpowers/specs/2026-09-15-morning-alpha-verification-of-verification-design.md`

## Global Constraints

- No setup/trigger/threshold changes.
- No live-order routing.
- Reference-library disagreements are fatal to the affected method.
- Missing execution evidence is `UNVERIFIED_EXECUTION`, never zero friction.
- Placebos and adversarial failures are preserved.
- Verification status is not a strategy-promotion verdict.

---

### Task 1: Statistical conformance harness

**Files:**
- Create: `engine/morning_alpha/research/conformance.py`
- Test: `engine/tests/morning_alpha/test_statistical_conformance.py`

**Interfaces:**
- Consumes: `MatchedEdgeObservation`, `bootstrap_edge_ci`, `paired_edge_permutation`, `date_cluster_edge_permutation`, cost break-even functions.
- Produces: `ConformanceCaseResult`, `ConformanceReport`, `run_statistical_conformance()`.

- [ ] Write RED tests comparing exact paired permutation with SciPy, cluster sign-flip with exhaustive enumeration, deterministic repeatability, and negative/tied fixtures.
- [ ] Implement reference comparisons with explicit tolerances and library-version capture.
- [ ] Add IID percentile-bootstrap comparison to SciPy using a fixed fixture/resample budget and pre-registered tolerance.
- [ ] Run focused tests; require GREEN.
- [ ] Run prior L3-L5 tests; require no regression.

### Task 2: Adversarial red-team battery

**Files:**
- Create: `engine/morning_alpha/research/red_team.py`
- Test: `engine/tests/morning_alpha/test_research_red_team.py`

**Interfaces:**
- Consumes: existing population/validation/split/OOS locks and persisted artifacts.
- Produces: `RedTeamCase`, `RedTeamCaseResult`, `RedTeamReport`.

- [ ] Write RED tests for all 12 mandatory corruption classes in the spec.
- [ ] Implement deterministic mutation helpers that operate on copied fixtures only.
- [ ] Require each case to name the expected gate/failure reason and compare it with the observed result.
- [ ] A missed corruption sets the report to FAILED.
- [ ] Run population/OOS/split regression tests.

### Task 3: Negative-control/placebo battery

**Files:**
- Create: `engine/morning_alpha/research/placebo_battery.py`
- Test: `engine/tests/morning_alpha/test_placebo_battery.py`

**Interfaces:**
- Consumes: matched observations and deterministic control identities.
- Produces: `PlaceboKind`, `PlaceboRun`, `PlaceboBatteryResult`.

- [ ] Write RED tests for within-date reassignment, date-block rotation, date-label shuffle, and deterministic signal-date shifts.
- [ ] Verify cluster-size and marginal-return preservation where required.
- [ ] Produce actual-edge percentile versus placebo distribution without promotion semantics.
- [ ] Verify deterministic seeds and fixture hashing.

### Task 4: Microstructure execution replay

**Files:**
- Create: `engine/morning_alpha/research/execution_replay.py`
- Test: `engine/tests/morning_alpha/test_execution_replay.py`

**Interfaces:**
- Consumes: quote sequences and immutable execution intent.
- Produces: `ExecutionReplayResult` and per-fill details.

- [ ] Write RED tests for full fill, spread crossing, partial fill, delayed fill, expired remainder, gap-through stop, and missing quotes.
- [ ] Implement deterministic quote selection at/after trigger/delay.
- [ ] Cap fill quantity by displayed-size participation.
- [ ] Preserve commissions, spread, impact, shortfall, fill ratio, and realized/theoretical R separately.
- [ ] Missing executable quote returns `UNVERIFIED_EXECUTION`.

### Task 5: Verification receipt/orchestrator

**Files:**
- Create: `engine/morning_alpha/research/verification_receipt.py`
- Modify: `engine/morning_alpha/research/__init__.py`
- Test: `engine/tests/morning_alpha/test_verification_receipt.py`

**Interfaces:**
- Consumes: V15-V18 reports plus research identity.
- Produces: immutable `VerificationReceipt` with deterministic `receipt_id`.

- [ ] Write RED tests for VERIFIED / FAILED / INCOMPLETE semantics.
- [ ] Include runtime/library versions, hashes, seeds, spec version and component IDs in receipt identity.
- [ ] Prove any evidence-identity change changes `receipt_id` while presentation-only fields do not.
- [ ] Export public interfaces.

### Task 6: Golden verification-of-verification chain

**Files:**
- Create: `engine/tests/morning_alpha/test_verification_of_verification_golden.py`
- Modify: `engine/docs/MORNING_ALPHA_RESEARCH_PROTOCOL.md`

**Interfaces:**
- Consumes: public V15-V19 APIs.
- Produces: one cross-layer regression proving conformance, corruption detection, placebo null behavior, execution fail-closed semantics, and receipt identity.

- [ ] Add a golden positive-conformance fixture.
- [ ] Add a golden contaminated fixture that the red-team/placebo layers expose.
- [ ] Add an execution-fragile fixture where theoretical R is positive but replay R is non-positive.
- [ ] Add explicit protocol language that V15-V19 validate the verifier and cannot establish permanent edge.
- [ ] Run focused V15-V19 tests.
- [ ] Run full `PYTHONPATH=. pytest tests/morning_alpha -q`.
- [ ] Run `python -m compileall -q morning_alpha`.
- [ ] Record ruff/full-repo/Gate-v2 integrity as external if unavailable; never infer PASS.
