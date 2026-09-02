# O-01 — CI Baseline & Debt Classification

**Plan:** JARVIS-MIP-1.0  
**Program:** O — DevOps / CI-CD  
**Phase:** 0  
**Safety class:** S0  
**State:** **IN_PROGRESS**  
**Baseline ref:** `master@1d8f93992205d1dcacc05e0466d89247f2c789d1`  
**Started:** 2026-09-01

## Objective

Establish a machine-usable distinction between:

1. CI infrastructure / GitHub Actions startup failures,
2. repository-baseline code/test debt,
3. branch-local regressions introduced by formal JARVIS-MIP work.

Formal implementation must never label an infrastructure startup failure as a code failure or use a missing CI run as evidence that code passed.

## Required master checks

The current `master` branch protection advertises these required contexts:

- `Engine Tests (pytest, fast)`
- `Engine Lint (Python)`
- `Safety-critical config gate`
- `Dashboard Build (Next.js)`
- `Dashboard Quality (typecheck + unit tests)`

## CI workflow contract observed in repository

`.github/workflows/ci.yml` currently defines:

- Python 3.12 engine lint (`ruff==0.8.0`),
- draft PR engine lint + byte compilation,
- allowlisted blocking mypy plus non-blocking full-tree mypy debt visibility,
- fast pytest with a single fresh-process retry for an acknowledged scanner pollution flake,
- slow pytest,
- coverage merge/floor,
- Next.js production build + bundle budget + Playwright smoke/golden path,
- dashboard static guards + TypeScript + Node unit tests,
- security scans.

`.github/workflows/safety-invariant-check.yml` independently runs the stdlib-only safety-invariant script on every PR, detects safety-critical file changes, and requires `[safety-review]` for those changes.

## Baseline observation: GitHub Actions startup failure

Recent `master` push workflow records, including the current baseline commit, report:

```text
conclusion = startup_failure
path       = BuildFailed
jobs       = []
```

For baseline commit `1d8f93992205d1dcacc05e0466d89247f2c789d1`, run `32893084295` produced no jobs at all. This is **CI-INFRA**, not ENGINE/DASHBOARD test evidence.

Recent commit metadata in the same run history explicitly records that GitHub Actions had been returning `startup_failure` since approximately 2026-08-16 and references an account-level registration/support issue. O-01 records this as historical supporting evidence; the current Actions behavior is independently observable from the empty-job startup failure at the baseline commit.

### Classification rule

| Class | Meaning | Example | May block merge? | Counts as product-code failure? |
|---|---|---|---|---|
| `CI-INFRA` | Workflow never obtains runnable jobs/runner or GitHub startup fails | `startup_failure`, `jobs=[]` | Yes operationally | **No** |
| `BASELINE-LINT` | Lint failure reproducible on unchanged baseline | pre-existing Ruff debt | Yes until governed baseline/ratchet | Yes, baseline debt |
| `BASELINE-TEST` | Test failure reproducible on unchanged baseline | stale symbol assertion | Yes until governed baseline/ratchet | Yes, baseline debt |
| `BRANCH-REGRESSION` | Touched branch introduces a new failure absent at baseline | new type/test/lint error | **Yes** | **Yes** |
| `FLAKE` | Same commit/input can demonstrably fail then pass without code/input change | acknowledged scanner pollution / font fetch | Conditional | Reliability debt |
| `NOT-RUN` | Job intentionally skipped by workflow state | full pytest on draft PR | No claim | No evidence either way |

## Baseline debt already declared by workflow source

These are **source-declared**, not newly executed measurements:

1. Full-tree mypy has legacy debt (`300+` is stated in CI comments) and is non-blocking; an allowlist is the actual blocking mypy gate.
2. Fast pytest contains a process-level retry for acknowledged global-state scanner pollution.
3. Dashboard build contains one retry for an acknowledged `next/font/google` network fetch flake.
4. Draft PRs intentionally skip the expensive full engine test/build/security jobs; only draft engine lint/compile + dashboard quality run.
5. Manual/IB Gateway tests are excluded from normal cloud pytest and therefore require separate E3/E4 evidence.

These design choices must be reviewed under O-02/O-03, but O-01 does not silently rewrite CI before the baseline is established.

## Historical branch-local receipts to reproduce

Pre-plan spike validation reported:

- approximately 15 pre-existing Ruff findings outside RT-2 touched files;
- five pre-existing dashboard symbol/baseline unit-test failures while new control-plane tests passed.

These are **PROVISIONAL HISTORICAL RECEIPTS**, not formal O-01 evidence until reproduced against the current baseline in a controlled environment. They must not be copied into the baseline as fact without reproduction.

## Baseline policy adopted now

Until GitHub Actions startup is healthy:

1. Every formal WP records whether cloud CI actually started jobs.
2. `startup_failure`/empty jobs are classified `CI-INFRA`, never “tests failed”.
3. Formal code changes require the best available deterministic local/focused validation plus exact commands/evidence; lack of cloud CI remains an open blocker at the applicable gate.
4. Touched files may not add new lint/test/type debt even if unrelated baseline debt exists.
5. S2–S4 work cannot satisfy its required evidence rung solely with compile/lint signals.
6. Required branch-protection contexts must be reconciled with the real workflow names before ISG-0 closes.

## O-01 next checks

- [x] Pin master baseline commit.
- [x] Record required status contexts.
- [x] Inspect current CI workflow contract.
- [x] Inspect safety invariant workflow contract.
- [x] Classify current baseline `startup_failure` as CI infrastructure, not code failure.
- [ ] Trigger a docs-only formal-plan draft PR and record which jobs actually start on the current account.
- [ ] Reproduce baseline Ruff independently or via a functioning runner.
- [ ] Reproduce dashboard type/unit baseline independently or via a functioning runner.
- [ ] Record exact current baseline failures in a machine-readable ratchet.
- [ ] Determine whether required status contexts can actually report under current Actions health.
- [ ] Create O-01 exit decision: CI healthy, or explicit `CI-INFRA` blocker with alternate validation protocol for Phase 0 only.

**Current verification level:** repository/workflow/API observation. No claim is made that the baseline code suite currently passes.
