# O-01 — CI Baseline and Debt Classification

**Plan:** JARVIS-MIP-1.0  
**Program:** O — DevOps / CI-CD  
**Phase:** MIP-0  
**Safety class:** S0  
**State:** **IN PROGRESS — BASELINE TEST DEFECT IDENTIFIED**  
**Repository baseline:** `master@e2a1006e3eb7d35a840487c80899b33103b52277`  
**Ready-PR evidence head:** `PR #768@2203a7f797b245f329fd3fe356a5675bc53547b2`  
**Repair PR:** `#773@8c1312d2de6ea6d965bde6b612bcd209c883bf14`  
**Observed:** 2026-09-02

## Objective

Maintain a machine-usable distinction among CI infrastructure failures, pre-existing baseline debt, flakes, intentionally skipped work, and branch-local regressions. A missing or still-running job is not pass evidence.

## Required contexts observed

- `Engine Tests (pytest, fast)`
- `Engine Lint (Python)`
- `Safety-critical config gate`
- `Dashboard Build (Next.js)`
- `Dashboard Quality (typecheck + unit tests)`

Repository protection metadata remains internally inconsistent: the branch endpoint has reported protection disabled while required-context metadata is present. O-05 must verify the actual enforcement settings; this document does not assume they are effective.

## Current ready-PR receipt

PR #768 final-head workflow evidence:

| Workflow/job | Run | Result at capture |
|---|---:|---|
| Claude PR Review | 33681768887 | PASS |
| Safety-critical config gate | 33681867123 | PASS |
| Engine Lint (Python) | 33681768981 | PASS |
| Engine Type Check (mypy) | 33681768981 | PASS |
| Security Scan | 33681768981 | PASS |
| Dashboard Quality | 33681768981 | PASS |
| Dashboard Build + Playwright E2E | 33681768981 | PASS |
| Engine Tests (pytest, slow) | 33681768981 | PASS |
| Engine Tests (pytest, fast), attempt 1 | 33681768981 | **FAIL — 3 failed, 9,215 passed** |
| Engine Tests (pytest, fast), fresh-process attempt 2 | 33681768981 | **FAIL — 3 failed, 9,214 passed** |
| Coverage merge/floor | 33681768981 | **SKIPPED because fast tests failed** |

The three failures are:

- `test_calibrate_kronos_threshold.py::TestOutputJsonSchema::test_per_instrument_ok_keys`
- `test_calibrate_kronos_threshold.py::TestOutputJsonSchema::test_percentile_keys`
- `test_calibrate_kronos_threshold.py::TestOutputJsonSchema::test_json_serialisable`

Both clean-process attempts failed identically. This is therefore not classified as a flake. The schema-only fixture hard-coded bars beginning 2025-09-01 while production calibration applies a 365-day lookback; on 2026-09-02 the fixture aged outside the valid window. PR #773 moves the synthetic fixture relative to the execution clock while retaining explicit insufficient-data coverage elsewhere.

This receipt supersedes the stale PR #760 baseline claims about 15 Ruff errors, a syntax error, and five dashboard failures: those defects were addressed by merged PR #757 and are not present in the completed jobs above. O-01 remains open until PR #773 passes on its exact head, the repair is merged, PR #768 is refreshed against that baseline, and one complete current-master receipt is recorded.

## Classification contract

| Class | Meaning | Counts as product-code failure? |
|---|---|---|
| `CI-INFRA` | Workflow never obtains jobs or GitHub startup fails | No |
| `BASELINE-DEBT` | Failure reproducible on the pinned unchanged baseline | Yes, governed debt |
| `BRANCH-REGRESSION` | Branch adds a failure absent at baseline | Yes |
| `FLAKE` | Same commit/input demonstrably changes result without code/input change | Reliability debt |
| `NOT-RUN` | Intentionally skipped | No evidence |
| `RUNNING` | Job has no terminal conclusion | No evidence yet |
| `PASS` | Terminal successful job on the exact recorded SHA | Positive evidence for that scope only |

## Known CI design debt

1. Full-tree mypy remains non-blocking; only an allowlist is enforced.
2. Fast pytest has a fresh-process retry for unresolved global-state pollution.
3. Dashboard font/network retry behavior remains reliability debt.
4. Draft PRs intentionally execute less coverage than ready PRs.
5. Manual/IB Gateway tests require separate E3/E4 evidence and must not run against live capital in cloud CI.
6. Security scanning is not yet a full dependency/SAST/SBOM/history-sensitive program.

## Exit checklist

- [x] Pin a reachable repository baseline.
- [x] Record advertised required contexts.
- [x] Observe final-head lint, type, dashboard, security, slow-test, safety, and review jobs.
- [x] Record terminal fast-test failures and classify their deterministic cause.
- [x] Open a narrowly scoped repair in PR #773.
- [ ] Require PR #773 exact-head fast-suite and full-CI success.
- [ ] Merge PR #773 only after all required checks pass.
- [ ] Refresh PR #768 on the repaired baseline and obtain a complete exact-head receipt.
- [ ] Merge PR #768 only after required contexts are green.
- [ ] Record the post-merge master SHA and master workflow receipt.
- [ ] Verify required contexts are actually enforced by branch protection.
- [ ] Assign CI design debts to O-02/O-03/O-05 owners and ratchets.

**Verification level:** E0/E1 cloud evidence for completed jobs only. No runtime, broker, paper E2E, or live claim.
