# O-01 — CI Baseline and Debt Classification

**Plan:** JARVIS-MIP-1.0  
**Program:** O — DevOps / CI-CD  
**Phase:** MIP-0  
**Safety class:** S0  
**State:** **EVIDENCE COMPLETE — MIP ADOPTION / ADMIN ENFORCEMENT PENDING**  
**Repository repair baseline:** `master@20ce13ca07c34b5159f05518abe670f7f3c32d24`  
**Refreshed MIP evidence head:** `PR #768@b4701a901ccddf01633b235fc71c807015acf6bf`  
**Repair PR:** `#773@4c1f5006d50a4304d74f25385abde4ca898ea577` — merged as `20ce13c`  
**Observed:** 2026-09-02 America/Chicago

## Objective

Maintain a machine-usable distinction among CI infrastructure failures, pre-existing baseline debt, flakes, intentionally skipped work, and branch-local regressions. A missing or still-running job is not pass evidence.

## Repaired baseline result

PR #773 repaired the deterministic CI defects discovered by O-01 and merged only after its required checks passed. PR #768 was then refreshed onto that repaired `master` with merge commit `b4701a…`, leaving it **0 commits behind master** at refresh time and triggering a complete final-head receipt.

The refreshed head is documentation-only relative to repaired master; therefore this receipt establishes the current CI ratchet for the MIP adoption tree without changing trading behavior.

## Exact refreshed-head receipt

| Workflow/job | Run | Result |
|---|---:|---|
| Claude PR Review | 33707562735 | PASS |
| Safety Invariant Check | 33707562597 | PASS |
| JARVIS TRADER CI | 33707562601 | **PASS** |
| Engine Lint (Python) | 33707562601 | PASS |
| Engine Type Check (mypy) | 33707562601 | PASS |
| Security Scan | 33707562601 | PASS |
| Engine Tests (pytest, fast) | 33707562601 | PASS |
| Engine Tests (pytest, slow) | 33707562601 | PASS |
| Engine Tests (coverage merge/floor) | 33707562601 | PASS |
| Dashboard Quality (typecheck + unit tests) | 33707562601 | PASS |
| Dashboard Build (Next.js) | 33707562601 | PASS |
| Playwright smoke (50 routes) + golden-path | 33707562601 | PASS |
| Dashboard static fetch/poll guards | 33707562601 | PASS |

`Engine Draft Check (ruff + compile)` was skipped by workflow policy because this is a ready/non-draft path; the dedicated `Engine Lint (Python)` job passed and fast/slow pytest both collected and passed.

## Debt that O-01 repaired

Earlier untouched-master and ready-PR probes found real baseline debt rather than branch-local regressions:

1. malformed `engine/tests/test_latency_fixes_20260818.py` blocked pytest collection;
2. `/trades/journal` selected model-only columns absent from the backing table contract;
3. Ruff contained deterministic baseline findings;
4. dashboard active/halted-symbol expectations had drifted;
5. Playwright contained a stale-body async rendering race;
6. a Kronos schema fixture aged outside the production 365-day lookback and failed reproducibly on two clean fast-suite attempts.

Those stale baseline claims are superseded by the exact green receipt above. The disposable full-CI probe PR #762 and superseded repair PR #761 are both closed without merge.

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

## Current CI ratchet

The green refreshed-head receipt becomes the Phase-0 minimum for ordinary repository work:

- Ruff must remain green.
- Fast and slow pytest must remain green when required by workflow policy.
- Coverage merge/floor must remain green.
- Mypy allowlist gate must remain green; full-tree mypy debt remains separately governed.
- Dashboard type/unit, production Next build and route/golden-path E2E must remain green.
- Security Scan and Safety Invariant Check remain independent required evidence.
- New failures may not be relabeled “pre-existing” without a pinned baseline reproduction.
- Test deselection, quarantine or skip-count changes require review.

O-02 owns the verification-rung model; O-03 owns build reproducibility; O-05 owns PR/workflow governance and the required-check/admin enforcement follow-up.

## Known CI design debt

1. Full-tree mypy remains non-blocking; only an allowlist is enforced.
2. Fast pytest retains a fresh-process retry mechanism for global-state reliability defense; its use must remain observable.
3. Hosted runner/package ecosystem is bounded rather than bit-for-bit reproducible; see O-03.
4. Draft/stacked PRs may execute less CI depending on base/workflow triggers; final candidate trees must rerun the required matrix.
5. Manual/IB Gateway tests require separate V4/V5 evidence and must not run against live capital in cloud CI.
6. Security scanning is not yet a full dependency/SBOM/history-sensitive supply-chain program.
7. Repository-admin branch-protection/required-check enforcement remains unverified through the available connector and belongs to O-05.

## Exit checklist

### Technical evidence

- [x] Pin a reachable repository baseline.
- [x] Classify original baseline failures with terminal logs.
- [x] Repair deterministic collection/lint/dashboard/test defects in governed PRs.
- [x] Merge PR #773 only after required checks pass.
- [x] Refresh PR #768 on repaired master.
- [x] Obtain one complete exact-head receipt after refresh.
- [x] Fast pytest PASS.
- [x] Slow pytest PASS.
- [x] Coverage merge/floor PASS.
- [x] Ruff/mypy/security PASS.
- [x] Dashboard type/unit/build/E2E PASS.
- [x] Safety Invariant Check PASS.
- [x] Assign remaining CI design debt to O-02/O-03/O-05.

### Program/adoption follow-up

- [ ] Merge/adopt PR #768 only after explicit human review/approval.
- [ ] Record post-adoption default-branch workflow receipt.
- [ ] Verify required contexts are actually enforced by repository-admin branch protection/rulesets.

These remaining items do not invalidate the technical green baseline; they prevent claiming that MIP adoption and repository-admin enforcement are complete.

**Verification level:** V0/V1/V3 cloud evidence for the scopes above. No local runtime, broker PAPER, canary or live-capital claim.
