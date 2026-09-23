# O-05 — Branch, PR, and Coding-Agent Governance

**Plan:** JARVIS-MIP-1.0  
**Program:** O — Delivery, Verification & Governance  
**Phase:** MIP-0  
**Safety class:** S1 workflow/governance change  
**State:** **IMPLEMENTED ON STACKED BRANCH — DEFAULT-BRANCH ENFORCEMENT NOT YET ACTIVE**  
**Depends on:** O-01, O-02, A-02/A-03  
**Required for:** governed implementation after ISG-0

## 1. Decision

JARVIS will use work-package-scoped branches and pull requests with machine-checked MIP metadata. Coding agents may create branches, commits, tests, evidence and draft PRs within the assigned work package, but may not self-authorize higher safety classes, merge safety-sensitive work, enable live trading, or bypass required verification rungs.

## 2. Branch contract

Preferred prefixes:

```text
docs/<wp>-<topic>
chore/<wp>-<topic>
feature/<wp>-<topic>
fix/<wp>-<topic>
research/<wp>-<topic>
```

Rules:

1. One primary work package per implementation PR.
2. Stacked PRs are permitted when the base/dependency is explicit.
3. Do not mix unrelated refactors with safety/runtime behavior changes.
4. Do not mix live configuration or credentials with code changes.
5. Do not force-push shared/review branches after review evidence is attached unless the review is explicitly reset.
6. Direct default-branch pushes are prohibited by process; repository-admin branch protection must enforce this where available.
7. Experimental spikes remain non-authoritative until harvested through a governed WP.

## 3. PR contract

`.github/pull_request_template.md` requires:

- Plan
- Program
- Work Package
- Phase / Milestone
- Safety Class
- Objective
- Dependencies
- Acceptance Criteria
- Required Verification Rung(s)
- Evidence / Reports
- Migration / Rollback
- Production / Capital Impact

S3/S4 or safety-critical execution/risk/broker paths require `[safety-review]` in the PR title.

## 4. Machine governance check

`.github/workflows/pr-governance.yml` validates metadata using `pull_request_target` **without checking out PR code**.

Security properties:

- permissions are read-only (`contents: read`, `pull-requests: read`);
- changed filenames are obtained through the GitHub API;
- no `actions/checkout` step exists;
- no PR scripts, package manifests or repository code are executed;
- the job fails when required metadata is absent;
- safety-critical paths require S3/S4 classification;
- workflow changes require at least S1;
- declared verification rung must meet the minimum for the safety class.

This workflow becomes authoritative only after it is merged into the base/default branch and, where desired as a hard merge gate, added to the repository's required checks.

## 5. Safety classification floors

The initial machine floor treats changes under these paths as safety critical:

```text
engine/risk/**
engine/execution/**
engine/brokers/**
engine/config.py
engine/routers/orders_router.py
engine/routers/approval_queue_router.py
engine/routers/safety_router.py
```

Those paths require S3 or S4 and the safety-review title marker. This is a conservative floor, not a declaration that all other paths are low risk. Reviewers may raise a PR's safety class based on behavior even when no listed path is touched.

GitHub workflow changes require at least S1 because they alter the verification/control plane.

## 6. Coding-agent authorization matrix

| Action | Agent may do autonomously? | Conditions |
|---|---:|---|
| inspect/read/search repository | yes | no secret disclosure |
| create WP branch | yes | scoped branch name |
| write docs/tests/non-live implementation | yes | within WP/safety bounds |
| create draft PR | yes | complete metadata |
| run deterministic CI/tests | yes | no real broker/capital side effects |
| add verification evidence | yes | accurate, commit-scoped |
| classify obvious safety-critical path as S3/S4 | yes | may raise, never lower to evade review |
| merge S0/S1 documentation/CI repair | only when explicitly authorized by repository policy/user | no implied self-approval |
| merge S2/S3/S4 | **no autonomous merge** | human review/approval required |
| mark safety PR ready for review | **no unless explicitly requested** | preserve draft safety boundary |
| edit active live risk/broker credentials | **no** | explicit separate human authorization required |
| enable LIVE trading | **no** | D4/V5 explicit human capital authorization |
| submit real broker order during validation | **no** | dedicated authorized canary only |
| promote Judge/research result to live | **no** | lifecycle + human gate |
| auto-retry ambiguous broker submission | **no** | reconcile first |

## 7. Required-check ratchet

After O-01 establishes the baseline and O-05 is active:

- current required checks may be strengthened, not silently weakened;
- workflow changes state their verification impact;
- safety/secret checks remain independent of feature tests;
- pre-existing failures require baseline evidence and a tracked repair WP;
- new failures cannot be excused as “repository debt” without proving they already exist on the relevant baseline;
- test deselection/skips are reviewed as behavior changes.

## 8. Branch protection / ruleset status

Phase-0 evidence currently cannot prove classic branch protection through the available GitHub connector: the classic branch-protection endpoint is not readable with the current integration permissions, and no repository rulesets were returned by the rulesets endpoint at the time of inspection.

Therefore O-05 does **not** claim that required-check enforcement or direct-push blocking is active at the repository-admin layer.

Repository owner/admin follow-up after merge:

1. verify default-branch protection/ruleset in GitHub settings;
2. require PRs before merge;
3. require the canonical CI checks and `PR Governance` check;
4. prevent force pushes/deletion of the default branch;
5. require conversation resolution/review policy appropriate to the repository;
6. document any admin bypass identities and use them only for recovery.

Until that receipt exists, process governance + CI checks are implemented but hard GitHub merge enforcement is `UNVERIFIED`.

## 9. PR-stack discipline

A stacked PR must state:

```text
base branch / parent PR
why stacking is necessary
which acceptance criteria belong to this PR
what happens if the parent changes or closes
```

A child stack is not independently mergeable merely because its own diff is clean. Before final merge, rebase/merge-current-parent and rerun required verification on the final tree.

## 10. Review semantics

- Draft means evidence can accumulate but adoption is not requested.
- Ready for review means the author believes the required non-runtime rungs are complete.
- Approved means review requirements are satisfied; it does not by itself grant PAPER/LIVE/capital authorization.
- Merged means code/doc state landed; environment activation remains a separate decision where applicable.
- Production/capital activation must have its own auditable authorization receipt.

## 11. Acceptance criteria

- [x] Canonical PR template created.
- [x] Required MIP metadata is machine-checked.
- [x] Safety-critical path floor is machine-checked.
- [x] Safety class to verification-rung floor is machine-checked.
- [x] Governance workflow uses read-only permissions.
- [x] Privileged PR event does not checkout or execute PR code.
- [x] Coding-agent authorization limits are explicit.
- [x] Stacked PR semantics are explicit.
- [x] Branch-protection uncertainty is recorded instead of assumed.
- [ ] Workflow merged into default branch.
- [ ] Repository-admin protection/ruleset receipt captured.
- [ ] `PR Governance` configured as required check if repository policy supports it.

## 12. Decision status

**In-repository governance implementation:** COMPLETE ON THIS BRANCH.  
**Default-branch enforcement:** PENDING MERGE.  
**Repository-admin branch protection:** UNVERIFIED.  
**Live/capital authorization:** NONE.
