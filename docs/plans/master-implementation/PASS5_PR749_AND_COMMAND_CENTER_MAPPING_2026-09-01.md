# Pass 5 PR #749 and Command Center Mapping - 2026-09-01

Loop: `jarvis-master-plan-drain-20260901`

## Scope

Complete the low-mutation tasks from the third ranked set:

- Build an isolated PR #749 inspection worktree.
- Reproduce/classify the PR #749 local Python failure surface.
- Map primary Command Center routes to canonical operator workflows.
- Draft endpoint-to-dashboard dependency matrix.
- Create CI failure taxonomy for the master plan loop.
- Add supersession notes to legacy state/planning docs.

## PR #749 Inspection Worktree

Created detached inspection worktree:

```text
C:\Users\mattm\ThinkorSwim\wt-pr749-feature-integrity-20260901
HEAD: f5d19e99
Source: origin/research/feature-integrity-v2
PR: https://github.com/mattamundson/jarvis-trader/pull/749
```

PR metadata:

```text
title: research: feature integrity registry and golden-vector parity
state: OPEN
draft: true
base: master
mergeable: MERGEABLE
```

Local bounded ruff reproduction on changed PR Python files:

```text
ruff check <changed engine *.py> --config engine/ruff.toml
Result: 39 errors
```

Failure classes:

| Class | Examples | Action |
|---|---|---|
| `I001` import sorting | `capital_path_core.py`, `judge_v3.py`, many tests | Safe auto-format candidate in PR worktree. |
| `C408` unnecessary `dict()`/`tuple()` | `capital_path_monte_carlo.py`, scenario/risk tests | Safe mechanical cleanup candidate. |
| `B905` `zip()` missing `strict=` | `test_capital_path_resampling.py` | Manual choice: likely `strict=False` for current semantics. |

The PR diff also includes dashboard files, data artifacts, tracked `.mypy_cache` deletions, and session-log deletion. [RISK] Do not auto-merge or bulk-fix this draft PR without first narrowing the intended PR scope.

## Command Center Route Disposition

| Route | Disposition | Reason |
|---|---|---|
| `/command-center` | Keep as canonical operator shell candidate | Most likely final first screen. |
| `/mission-control` | Merge/reference | Potential overlap with `/command-center`; should not remain a second competing command surface. |
| `/today` | Merge/reference | Useful daily operator view, but should become a panel or tab if duplicated. |
| `/trades` | Keep | Primary trade lifecycle surface. |
| `/trades/journal` | Keep | Trade review and journal are distinct from active trade operations. |
| `/trades/pending-approvals` | Keep | Human approval queue is safety-critical. |
| `/trading-eligibility` | Keep | Canonical live eligibility view; static docs should defer to it. |
| `/validation` | Keep | Certification and readiness status. |
| `/strategy-ledger` | Keep | Strategy provenance and adoption state. |
| `/research-log` | Keep/reference | Keep if it maps to research-trial ledger; otherwise merge into strategy ledger. |
| `/health` | Keep | Runtime health, broker, data, and dependency status. |
| `/data-integrity` | Keep | Data-quality failures deserve first-class visibility. |
| `/trust-pane` | Merge/reference | Trust signals should appear in command-center context, not only as a separate page. |

## Endpoint Dependency Matrix

All browser-side engine calls should route through `dashboard/lib/api.ts` and `/api/engine/*`.

| Dashboard workflow | Likely engine surfaces | Status |
|---|---|---|
| Runtime health | `/health`, `/health/*`, `/system/data-integrity`, `/ws/status` | Known surface; runtime offline in Pass 2. |
| Trade operations | `/portfolio/paper/*`, `/trades/*`, `/paper/*`, `/approval/*` | Known surface; `/trades/journal` schema bug fixed in this loop. |
| Approval queue | `/pending-approvals/*`, `/approval-queue/*`, `/webhook/*` | Needs one canonical queue model. |
| Trading eligibility | `/paper/validation/approved-paper-gates`, `/validation/*`, `/readiness/*` | Static docs now superseded. |
| Strategy ledger | `/strategies/*`, `/strategy-ledger/*`, `/analytics/*` | Needs keep/merge review before final Command Center. |
| Research log | `/experiments/*`, `/discovery/*`, `/analytics/*` | Should align with PR #749 research trial ledger if adopted. |
| Data integrity | `/system/data-integrity`, `/cache/*`, `/prices/*` | Needs stale-cache and provider status badges. |
| External intelligence | `/discord/*`, `/sentiment/*`, `/vault/*` | Keep secondary to operator safety surfaces. |

## CI Failure Taxonomy

| Taxonomy | Examples seen in loop | Default response |
|---|---|---|
| Code syntax/collection | `test_latency_fixes_20260818.py` indentation corruption | Patch immediately with focused tests. |
| Static lint | Ruff `F841`, PR #749 `I001`/`C408`/`B905` | Auto-fix only on owned branch; otherwise classify. |
| Runtime service dependency | Dashboard tests failing `ECONNREFUSED 127.0.0.1:8010` | Do not claim app readiness; start/restart only under explicit runtime scope. |
| Environment drift | Engine venv Python 3.13.3 vs CI 3.12 | Build parallel 3.12 venv, prove, then archive/swap. |
| Validation-data semantics | IB PIT leak, VWAP pre-RTH eligibility | Patch semantics, rerun certifications, surface verdict flips. |
| Scope contamination | PR #749 includes unrelated cache/session artifacts | Split or clean PR before merge review. |

## Superseded Docs

Added 2026-09-01 supersession notes to:

- `docs/CURRENT_STATE.md`
- `docs/JARVIS_TRADER_UNIFIED_CANON.md`
- `docs/JARVIS_SOTA_PLAN.md`
- `docs/LIVE_TRADING_READINESS.md`

These docs now point readers to `docs/plans/master-implementation/README.md` for current governance and implementation planning.

## Blocked Validation Reruns

P3-004 and P3-005 remain blocked on a proven Python 3.12 engine venv. They should run after the parallel 3.12 environment passes focused verification.

