# Morning Alpha Historical Population Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic point-in-time historical Relative Strength candidate population with validation Levels 0–2, purged temporal splits, exact detector parity, immutable lineage, and repeatable population hashes.

**Architecture:** `HistoricalFeatureBuilder` transforms certified PIT source observations into immutable feature snapshots; `HistoricalCandidatePopulationBuilder` uses the existing `RelativeStrengthBreakout` detector without duplicating strategy logic; `PopulationValidator`, `SplitRegistry`, and `CandidatePopulationWriter` enforce integrity and reproducibility around the resulting qualified/rejected population.

**Tech Stack:** Python 3.12, Pydantic v2, existing Morning Alpha models/detectors/providers, pytest, standard-library hashlib/json/datetime/pathlib.

**Spec:** `docs/superpowers/specs/2026-09-15-morning-alpha-population-validation-design.md`

## Global Constraints

- Canonical historical decision clock is 09:00 `America/New_York` per trading session.
- Current-session RTH information after the decision boundary is forbidden.
- Historical population logic must call the exact existing `RelativeStrengthBreakout.evaluate()` implementation.
- Candidate identity is strategy canonical version + stable security ID + decision timestamp.
- Duplicates are hard failures; never silently deduplicate.
- Stock/SPY/sector return endpoints must align exactly.
- Every feature records source-lineage timestamps and latest source timestamp.
- Uncertified data/readiness blocks the build.
- Maximum pre-registered forward horizon is 20 trading sessions; default split purge/embargo is 20 sessions.
- Rejected observations are preserved.
- No performance/edge claim is produced by this milestone.
- No live-order capability is introduced.

---

### Task 1: Candidate identity, observations, and population result

**Files:**
- Create: `engine/morning_alpha/research/population.py`
- Test: `engine/tests/morning_alpha/test_population_models.py`

**Interfaces:**
- Produces `CandidateDecisionState(StrEnum)` with `QUALIFIED`, `REJECTED`.
- Produces immutable `CandidateObservation`.
- Produces immutable `PopulationBuildResult`.
- Produces `candidate_identity(strategy_key, stable_security_id, decision_timestamp) -> str`.

- [ ] **Step 1: Write failing identity/model tests**

Test that identical strategy/stable-ID/timestamp yields identical ID, changing any identity field changes the ID, naive decision timestamps are rejected, and duplicate IDs supplied to `PopulationBuildResult` raise `DUPLICATE_CANDIDATE`.

- [ ] **Step 2: Run focused tests and verify RED**

```bash
cd engine
PYTHONPATH=. pytest tests/morning_alpha/test_population_models.py -v
```

Expected: import/module failure because `research.population` does not exist.

- [ ] **Step 3: Implement minimal immutable models**

`CandidateObservation` must include candidate ID, campaign ID, strategy key, stable security ID, symbol, decision timestamp, trading date, sector, sector ETF, decision state, rejection reason, feature hash, universe hash, data-manifest hash, source-lineage hash, and optional detector candidate payload.

`PopulationBuildResult` includes decision timestamp, observations tuple, input-universe count, qualified count, rejected count, rejection-count mapping, universe hash and population hash, with validators requiring count reconciliation and unique candidate IDs.

- [ ] **Step 4: Run focused tests and full Morning Alpha tests**

```bash
PYTHONPATH=. pytest tests/morning_alpha/test_population_models.py -v
PYTHONPATH=. pytest tests/morning_alpha -q
```

- [ ] **Step 5: Commit**

```bash
git add engine/morning_alpha/research/population.py engine/tests/morning_alpha/test_population_models.py
git commit -m "feat(morning-alpha): add historical population models"
```

---

### Task 2: Feature lineage and PIT-safe Relative Strength feature builder

**Files:**
- Create: `engine/morning_alpha/research/feature_builder.py`
- Test: `engine/tests/morning_alpha/test_historical_feature_builder.py`

**Interfaces:**
- Produces `FeatureInputLineage`.
- Produces `HistoricalFeatureSnapshot`.
- Produces `HistoricalFeatureBuilder.build(...) -> HistoricalFeatureSnapshot`.

Inputs are completed stock daily bars, SPY daily bars, sector ETF daily bars, stable security ID, historical sector/ETF, decision timestamp and manifest identity.

- [ ] **Step 1: Write failing anti-lookahead tests**

Cover stock 20-session return, SPY 20-session return, sector 20-session return, SMA20/SMA50, ATR14, prior high/low, 252-session high, 20-session liquidity, and feature hashes. Add absurd future bars after decision timestamp and require identical serialized output/hash.

- [ ] **Step 2: Write benchmark-alignment failure test**

A stock feature endpoint of D-1 combined with SPY or sector endpoint D-2 must raise `BENCHMARK_ALIGNMENT_FAILED` rather than forward-fill.

- [ ] **Step 3: Verify RED**

```bash
PYTHONPATH=. pytest tests/morning_alpha/test_historical_feature_builder.py -v
```

- [ ] **Step 4: Implement minimal feature builder**

Use only bars before the current regular session. Require at least 252 stock sessions for the 252-session high and at least 20 aligned sessions for return/liquidity calculations. Feature lineage stores each endpoint and `latest_source_timestamp`.

The snapshot exposes helpers to create the existing `InstrumentSnapshot` and `SetupContext` expected by `RelativeStrengthBreakout`.

- [ ] **Step 5: Verify focused + full suite and commit**

```bash
PYTHONPATH=. pytest tests/morning_alpha/test_historical_feature_builder.py -v
PYTHONPATH=. pytest tests/morning_alpha -q
git add engine/morning_alpha/research/feature_builder.py engine/tests/morning_alpha/test_historical_feature_builder.py
git commit -m "feat(morning-alpha): add pit historical feature builder"
```

---

### Task 3: Historical candidate population builder and detector parity

**Files:**
- Modify: `engine/morning_alpha/research/population.py`
- Test: `engine/tests/morning_alpha/test_population_builder.py`

**Interfaces:**
- Produces `HistoricalUniverseMember` with stable ID, symbol, sector, sector ETF, listing/delisting timestamps and eligibility/liquidity state.
- Produces `HistoricalCandidatePopulationBuilder.build_session(...) -> PopulationBuildResult`.
- Consumes `HistoricalFeatureBuilder` and exact `RelativeStrengthBreakout` detector.

- [ ] **Step 1: Write failing PIT-universe tests**

Prove a delisted security can appear before delisting but not after; a future listing cannot leak backward; changing today's universe does not alter an earlier session.

- [ ] **Step 2: Write detector-parity test**

For the same generated `InstrumentSnapshot` + `SetupContext`, require builder detector payload to equal direct `RelativeStrengthBreakout.evaluate()` serialization.

- [ ] **Step 3: Write rejection-accounting test**

Create a small universe with one liquidity reject, one insufficient-history reject, one detector reject and one qualified row; require all counts to reconcile exactly to universe count.

- [ ] **Step 4: Verify RED, implement minimal builder, verify GREEN**

The builder computes a deterministic universe hash over active stable IDs, preserves all rejection observations, and raises rather than silently swallowing unexpected feature errors.

- [ ] **Step 5: Run full suite and commit**

```bash
PYTHONPATH=. pytest tests/morning_alpha/test_population_builder.py -v
PYTHONPATH=. pytest tests/morning_alpha -q
git add engine/morning_alpha/research/population.py engine/tests/morning_alpha/test_population_builder.py
git commit -m "feat(morning-alpha): build pit candidate population"
```

---

### Task 4: Population validation Levels 0–2

**Files:**
- Create: `engine/morning_alpha/research/validation.py`
- Test: `engine/tests/morning_alpha/test_population_validation.py`

**Interfaces:**
- Produces `ValidationSeverity(StrEnum)` (`ERROR`, `WARNING`).
- Produces `ValidationCode(StrEnum)` including `DATA_NOT_CERTIFIED`, `TEMPORAL_LEAKAGE`, `BENCHMARK_ALIGNMENT_FAILED`, `DUPLICATE_CANDIDATE`, `ACCOUNTING_MISMATCH`, `MANIFEST_IDENTITY_MISMATCH`, `NON_DETERMINISTIC_RESEARCH`.
- Produces `ValidationIssue`, `PopulationValidationReport`, `PopulationValidator.validate(...)`.

- [ ] **Step 1: Write temporal/manifest/duplicate/accounting tests**

Create intentionally invalid populations and require exact hard-error codes.

- [ ] **Step 2: Write determinism comparison test**

Two population results with unchanged inputs must have equal population hashes; altered candidate feature hash or universe hash must produce `NON_DETERMINISTIC_RESEARCH` when compared as repeat runs.

- [ ] **Step 3: Verify RED, implement minimal validator, verify GREEN**

`report.valid` is true only when there are zero ERROR issues.

- [ ] **Step 4: Full regression and commit**

```bash
PYTHONPATH=. pytest tests/morning_alpha/test_population_validation.py -v
PYTHONPATH=. pytest tests/morning_alpha -q
git add engine/morning_alpha/research/validation.py engine/tests/morning_alpha/test_population_validation.py
git commit -m "feat(morning-alpha): validate historical populations"
```

---

### Task 5: Immutable temporal splits with purge/embargo

**Files:**
- Create: `engine/morning_alpha/research/splits.py`
- Test: `engine/tests/morning_alpha/test_research_splits.py`

**Interfaces:**
- Produces `SplitKind`, `TemporalSplit`, `PurgedTemporalSplit`, `SplitRegistry`.
- `SplitRegistry.assign(timestamp) -> SplitKind | None`.
- `SplitRegistry.purged(kind) -> PurgedTemporalSplit`.

- [ ] **Step 1: Write failing disjointness/order tests**

Overlapping split intervals must be rejected. DEVELOPMENT < VALIDATION < OOS < FORWARD ordering is required when present.

- [ ] **Step 2: Write purge/embargo tests**

With 20 trading-session purge size and synthetic trading dates, observations within 20 sessions of an evaluation boundary must be excluded from adjacent development/validation samples.

- [ ] **Step 3: Implement trading-session-index-based purge**

Do not approximate with 20 calendar days. Purging accepts an ordered tuple of actual trading dates and returns included/excluded sets.

- [ ] **Step 4: Full regression and commit**

```bash
PYTHONPATH=. pytest tests/morning_alpha/test_research_splits.py -v
PYTHONPATH=. pytest tests/morning_alpha -q
git add engine/morning_alpha/research/splits.py engine/tests/morning_alpha/test_research_splits.py
git commit -m "feat(morning-alpha): add purged temporal research splits"
```

---

### Task 6: Immutable candidate population storage and content hashes

**Files:**
- Create: `engine/morning_alpha/research/candidate_store.py`
- Test: `engine/tests/morning_alpha/test_candidate_store.py`

**Interfaces:**
- Produces `CandidatePopulationManifest`.
- Produces `CandidatePopulationWriter.write(result, root, ...) -> CandidatePopulationManifest`.
- Produces `verify_population_artifact(root, manifest) -> bool`.

- [ ] **Step 1: Write failing deterministic-storage tests**

Writing identical population content twice must yield identical content hash. Changing feature hash, strategy version, manifest identity or candidate set must change the population hash.

- [ ] **Step 2: Write artifact-tamper test**

Modify persisted candidate bytes after write and require verification failure.

- [ ] **Step 3: Implement deterministic JSONL storage**

Sort observations by candidate ID before serialization, use canonical JSON key ordering, store manifest identity/code strategy metadata/counts/hash. No database dependency for the research artifact.

- [ ] **Step 4: Full regression and commit**

```bash
PYTHONPATH=. pytest tests/morning_alpha/test_candidate_store.py -v
PYTHONPATH=. pytest tests/morning_alpha -q
git add engine/morning_alpha/research/candidate_store.py engine/tests/morning_alpha/test_candidate_store.py
git commit -m "feat(morning-alpha): persist candidate population artifacts"
```

---

### Task 7: Golden repeatability and negative-contamination fixtures

**Files:**
- Test: `engine/tests/morning_alpha/test_population_golden.py`

**Interfaces:**
- Uses Tasks 1–6 without new production APIs.

- [ ] **Step 1: Build positive golden fixture**

Construct historical universe + 252-session bars such that exactly one Relative Strength candidate qualifies, one detector reject remains rejected, and expected candidate/rejection hashes are stable.

- [ ] **Step 2: Add future-contamination fixture**

Append absurd future stock/SPY/sector bars and future universe rows; rerun the earlier session and require byte-equivalent population result serialization/hash.

- [ ] **Step 3: Add manifest/split mutation fixture**

Changing data-manifest identity or split registry identity must alter the population artifact identity while leaving detector feature values unchanged.

- [ ] **Step 4: Run focused/full suite and commit**

```bash
PYTHONPATH=. pytest tests/morning_alpha/test_population_golden.py -v
PYTHONPATH=. pytest tests/morning_alpha -q
git add engine/tests/morning_alpha/test_population_golden.py
git commit -m "test(morning-alpha): add golden historical population replay"
```

---

### Task 8: Population diagnostics and CLI/report surface

**Files:**
- Create: `engine/morning_alpha/research/population_report.py`
- Modify: `engine/morning_alpha/cli.py`
- Test: `engine/tests/morning_alpha/test_population_reporting.py`

**Interfaces:**
- Produces `PopulationDiagnostics` with counts by decision state, rejection reason, sector, symbol and month/year.
- Produces `render_population_report(result, validation, diagnostics) -> str`.
- Adds CLI command `research-population-validate --population-manifest <path> [--json]`.

- [ ] **Step 1: Write report/CLI tests**

Require report sections `POPULATION IDENTITY`, `ACCOUNTING`, `VALIDATION`, `DISTRIBUTION`, `RESEARCH STATUS`. Invalid validation must produce nonzero CLI exit and never print `EDGE CONFIRMED` or equivalent language.

- [ ] **Step 2: Implement report and CLI**

The output may say `POPULATION_VALIDATED` or `POPULATION_INVALID`; it may not issue a strategy PASS/FAIL edge verdict.

- [ ] **Step 3: Run complete verification**

```bash
cd engine
PYTHONPATH=. pytest tests/morning_alpha -q
python -m compileall -q morning_alpha
```

Expected: zero pytest failures and compile exit 0.

- [ ] **Step 4: Commit**

```bash
git add engine/morning_alpha/research/population_report.py engine/morning_alpha/cli.py engine/tests/morning_alpha/test_population_reporting.py
git commit -m "feat(morning-alpha): report candidate population validation"
```

---

## Plan Self-Review

- Spec coverage: Tasks 1–8 cover candidate identity, feature lineage, PIT universe construction, exact detector parity, validation Levels 0–2, split purity/purge, immutable storage, repeatability and descriptive distribution diagnostics.
- Later Levels 3–11 are intentionally interfaces/future stages, not implemented here.
- No placeholders or unspecified implementation steps remain.
- Type names and signatures are consistent across tasks.
- This milestone does not make a historical edge claim.
