# Historical Candidate Population & Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic, point-in-time-safe historical Relative Strength candidate population with validation Levels 0–2, purged temporal splits, immutable population manifests, and no statistical edge inference.

**Architecture:** A `HistoricalFeatureBuilder` constructs PIT feature snapshots from certified historical bars; `HistoricalCandidatePopulationBuilder` reconstructs historical membership/liquidity, invokes the canonical `RelativeStrengthBreakout` detector, and records every qualified/rejected observation. `PopulationValidator`, `PurgedTemporalSplitter`, and `CandidatePopulationWriter` enforce temporal integrity, deterministic identities/hashes, split purity, and artifact lineage.

**Tech Stack:** Python 3.12, Pydantic v2, existing Morning Alpha models/providers/setups, hashlib/JSON, pytest.

**Spec:** `docs/superpowers/specs/2026-09-15-morning-alpha-historical-population-validation-design.md`

## Global Constraints

- Canonical decision clock: 09:00 America/New_York.
- Use certified research data only.
- No input with `available_at > decision_timestamp`.
- Do not duplicate Relative Strength detector rules.
- Do not silently forward-fill benchmarks or drop duplicates.
- Candidate identity is strategy version + stable security ID + UTC decision timestamp.
- Every processed security must terminate as a candidate or explicit rejection.
- No edge/statistical inference in this milestone.
- Full Morning Alpha regression suite must remain green.

---

### Task 1: Historical security identity and decision clock

**Files:**
- Create: `engine/morning_alpha/research/population.py`
- Test: `engine/tests/morning_alpha/test_population_identity.py`

**Interfaces:**
- Produces `PopulationDecisionClock`, `HistoricalSecurityRecord`, `candidate_identity(...)`.
- Consumed by Tasks 3–6.

- [ ] Write failing tests proving naive timestamps are rejected, 09:00 ET is produced for a trading date, historical membership respects listing/delisting boundaries, sector effective dates are enforced, and candidate IDs are deterministic.
- [ ] Run `PYTHONPATH=. pytest tests/morning_alpha/test_population_identity.py -v` and confirm RED because the module/types are missing.
- [ ] Implement the minimal immutable models/helpers.
- [ ] Re-run focused tests and require PASS.
- [ ] Run `PYTHONPATH=. pytest tests/morning_alpha -q`.
- [ ] Commit `feat(morning-alpha): add historical population identity`.

### Task 2: PIT Relative Strength feature builder

**Files:**
- Create: `engine/morning_alpha/research/feature_builder.py`
- Test: `engine/tests/morning_alpha/test_historical_feature_builder.py`

**Interfaces:**
- Produces `FeatureLineage`, `HistoricalFeatureSnapshot`, `HistoricalFeatureBuilder.build(...)`.
- Consumes `MarketBar` sequences and benchmark bars.
- Produces `InstrumentSnapshot` + `SetupContext` compatible data for canonical detectors.

- [ ] Write failing tests for exact 20-session returns, SMA20/SMA50, ATR14, prior high/low/close, 252-session high, average volume/dollar volume, aligned SPY/sector endpoints, future-row invariance, and `BENCHMARK_ALIGNMENT_FAILED`.
- [ ] Verify RED.
- [ ] Implement filtering `bar.timestamp <= decision_timestamp` and completed-daily-session selection.
- [ ] Compute all required features from aligned historical endpoints; produce deterministic feature hash and lineage.
- [ ] Verify focused and full suites.
- [ ] Commit `feat(morning-alpha): add PIT historical feature builder`.

### Task 3: Candidate/rejection population builder using canonical detector

**Files:**
- Extend: `engine/morning_alpha/research/population.py`
- Test: `engine/tests/morning_alpha/test_population_builder.py`

**Interfaces:**
- Produces `CandidateObservation`, `CandidateRejection`, `PopulationBuildResult`, `HistoricalCandidatePopulationBuilder.build(...)`.
- Consumes `DataReadinessReport`, `HistoricalSecurityRecord`, feature builder, existing `RelativeStrengthBreakout`.

- [ ] Write failing tests: uncertified readiness blocks execution; inactive/future-market records reject; liquidity rejects use existing policy; detector rejects are recorded; qualified output matches canonical detector serialization; every record has one terminal state.
- [ ] Verify RED.
- [ ] Implement builder without reproducing detector rules.
- [ ] Add deterministic population hash over sorted terminal records.
- [ ] Hard-fail duplicate candidate identity.
- [ ] Verify focused/full tests.
- [ ] Commit `feat(morning-alpha): build historical candidate populations`.

### Task 4: Validation Levels 0–2

**Files:**
- Create: `engine/morning_alpha/research/validation.py`
- Test: `engine/tests/morning_alpha/test_population_validation.py`

**Interfaces:**
- Produces `ValidationSeverity`, `ValidationCode`, `ValidationIssue`, `PopulationValidationReport`, `PopulationValidator.validate(...)`.

- [ ] Write failing tests for missing manifest hash, naive decision timestamps, temporal leakage, invalid historical membership/sector timing, duplicate IDs, accounting mismatch, missing mandatory feature lineage, and valid population PASS.
- [ ] Verify RED.
- [ ] Implement fatal/nonfatal issue collection and exact accounting checks.
- [ ] Ensure temporal leakage and duplicate identity are fatal.
- [ ] Verify focused/full tests.
- [ ] Commit `feat(morning-alpha): add population validation levels`.

### Task 5: Purged temporal split registry

**Files:**
- Create: `engine/morning_alpha/research/splits.py`
- Test: `engine/tests/morning_alpha/test_purged_splits.py`

**Interfaces:**
- Produces `SplitLabel`, `TemporalSplit`, `PurgedSplitAssignment`, `PurgedTemporalSplitter`.

- [ ] Write failing tests for overlapping split rejection, one-split-only assignment, 20-session forward-window purge at boundaries, embargo behavior, and deterministic assignments.
- [ ] Verify RED.
- [ ] Implement split validation and trading-session-index based purge/embargo.
- [ ] Verify focused/full tests.
- [ ] Commit `feat(morning-alpha): add purged temporal splits`.

### Task 6: Immutable candidate population artifact store

**Files:**
- Create: `engine/morning_alpha/research/candidate_store.py`
- Test: `engine/tests/morning_alpha/test_candidate_store.py`

**Interfaces:**
- Produces `CandidatePopulationManifest`, `CandidatePopulationWriter.write(...)`.

- [ ] Write failing tests that output contains campaign/strategy/code commit/data-manifest hash/counts/population hash/decision clock and SHA-256 of persisted population bytes.
- [ ] Verify RED.
- [ ] Implement deterministic JSONL serialization sorted by identity and manifest generation.
- [ ] Ensure repeated identical writes produce identical population artifact hash.
- [ ] Verify focused/full tests.
- [ ] Commit `feat(morning-alpha): persist candidate population artifacts`.

### Task 7: Synthetic golden population replay

**Files:**
- Create: `engine/tests/morning_alpha/test_population_golden.py`
- Modify: `engine/morning_alpha/research/__init__.py`

**Interfaces:**
- Integrates Tasks 1–6.

- [ ] Write synthetic certified fixture with qualified, detector-rejected, liquidity-rejected, inactive, and benchmark-misaligned securities.
- [ ] Assert candidate/rejection counts reconcile, canonical detector parity holds, population validation passes for clean records, and repeat build hashes are identical.
- [ ] Add future absurd rows and assert identical prior population.
- [ ] Intentionally inject future lineage and assert temporal-leakage failure.
- [ ] Run focused and full suites.
- [ ] Export stable public research interfaces.
- [ ] Commit `test(morning-alpha): add golden population replay`.

### Task 8: CLI/reporting and protocol documentation

**Files:**
- Modify: `engine/morning_alpha/cli.py`
- Modify: `engine/docs/MORNING_ALPHA_RESEARCH_PROTOCOL.md`
- Test: `engine/tests/morning_alpha/test_population_cli.py`

**Interfaces:**
- Adds `research-population-validate` and `research-split-plan` CLI commands using dependency injection where real historical stores are unavailable.

- [ ] Write failing CLI tests: uncertified data exits 2; validation JSON exposes level/issues/hash; split-plan output includes purge/embargo settings.
- [ ] Verify RED.
- [ ] Implement minimal CLI/report serialization.
- [ ] Document Levels 0–2 and promotion prohibition.
- [ ] Run full suite and `python -m compileall -q morning_alpha`.
- [ ] Commit `docs(morning-alpha): document population validation workflow`.

## Final Verification

- [ ] `PYTHONPATH=. pytest tests/morning_alpha -q`
- [ ] `python -m compileall -q morning_alpha`
- [ ] Confirm no new live-order/broker mutation path.
- [ ] Confirm design requirements map to Tasks 1–8.
- [ ] Confirm no placeholder/TODO plan items remain.
