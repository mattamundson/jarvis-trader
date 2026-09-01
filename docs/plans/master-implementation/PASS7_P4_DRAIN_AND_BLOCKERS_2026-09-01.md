# Pass 7 P4 Drain and Blockers - 2026-09-01

Loop: `jarvis-master-plan-drain-20260901`

## Scope

Drain the ready P4 items that can be completed without starting JARVIS runtime services or replacing the active engine venv.

## Completed

### P4-002 PR #749 Ruff Cleanup

In isolated worktree:

```text
C:\Users\mattm\ThinkorSwim\wt-pr749-feature-integrity-20260901
```

Ran ruff safe fixes on changed PR Python files:

```text
ruff check <changed engine *.py> --config engine/ruff.toml --fix
Result: 33 fixed, 6 remaining
```

Patched the six remaining mechanical findings explicitly:

- `tuple()` empty fallback -> `()`.
- `dict(...)` fixtures -> literal dictionaries.
- `zip(...)` -> `zip(..., strict=False)`.

Recheck:

```text
ruff check <changed engine *.py> --config engine/ruff.toml
Result: All checks passed.
```

The PR #749 worktree is intentionally left dirty and unpushed. It is isolated from the main checkout.

### P4-003 PR #749 Scope Split Plan

Recommended split:

| Bucket | Keep in PR #749 | Move/split |
|---|---|---|
| Feature-integrity core | `engine/backtest/studies/*`, feature registry/store/availability tests | None if ruff/test pass. |
| Judge/capital-path research | `judge_v3*`, `capital_path_*`, trial ledger | Consider separate PR if review scope is too large. |
| Dashboard preview surfaces | `dashboard/app/*`, `dashboard/components/*`, `dashboard/lib/api.ts` | Separate Command Center PR unless directly needed by research contract. |
| Data artifacts | `engine/scripts/*_results.json`, `data/discord-digests/*` | Separate data-refresh PR or archive as generated provenance. |
| Cache/session deletions | tracked `.mypy_cache` and session-log deletions | Remove from PR scope before merge review. |

### P4-004 Dashboard Static Quality

Commands:

```text
pnpm run guards
pnpm run typecheck
```

Results:

```text
All dashboard guards passed.
tsc --noEmit passed.
```

Guard detail:

- no-direct-engine-url: 0 violations
- no-bare-fetch: 0 violations
- no-dynamic-import-defeated-by-static: 0 violations
- hardcoded-refresh-interval: 105, ceiling 128

### P4-005 Command Center Information Architecture

Canonical first-screen shell:

| Area | Required content | Unsafe action handling |
|---|---|---|
| Header/status strip | engine health, dashboard build status, IB gateway state, paper/live mode, kill switch | Never hide degraded state behind green aggregate labels. |
| Trade queue | pending approvals, active paper positions, stale-stop risk, order-path mode | Approve/reject/close actions require explicit user action and idempotency keys. |
| Eligibility | approved paper gates, failed gates, stale verdicts, validation freshness | No manual override from UI unless backend exposes audited override. |
| Strategy ledger | adopted/paused/research-only strategies, latest verdict, confidence and decay | Strategy promotion requires recertification artifact. |
| Data integrity | cache age, provider status, bar freshness, source parity | Block trade enablement when data is stale or provenance is unknown. |
| Research intake | open PRs, issues, experiments, candidate backlog | Research spikes cannot be displayed as production readiness. |

Navigation model:

- `/command-center` is the canonical operator shell.
- `/mission-control`, `/today`, and `/trust-pane` should be merged or demoted to reference panels.
- `/trades`, `/trades/journal`, `/trades/pending-approvals`, `/trading-eligibility`, `/validation`, `/strategy-ledger`, `/research-log`, `/health`, and `/data-integrity` remain primary supporting routes.

### P4-006 Environment Drift Detector Plan

Add a lightweight local/CI check that emits JSON and fails on:

- Python interpreter mismatch from expected `3.12.x`.
- Active engine `.venv` mismatch from CI target.
- Node/pnpm versions outside dashboard lock expectations.
- Engine/dashboard ports not explicitly configured.
- Direct engine URL or bare fetch guard regressions.
- Yanked or broken Python dependencies from `pip check` and install warnings.

Suggested output path:

```text
engine/data/health/environment_drift_latest.json
```

### P4-007 Recertification Manifest

Required after IB/VWAP semantics changes:

| Change | Must rerun | Current state |
|---|---|---|
| IB no premarket completed-level exposure | `compute_initial_balance` callers, `ib_breakout_signals`, `ib_wfo_runner`, affected Gate-v2 verdicts | Unit regression passes; full validation not rerun. |
| VWAP RTH-only accumulation and signal window | `run_mes_vwap_rank1.py`, `vwap_walk_forward.py`, `vwap_paper_track.py`, any MES VWAP artifacts | Unit regression passes; long recert runner blocked. |
| Active venv drift | focused engine tests under Python 3.12 | Passed in `.venv312-codex-loop`. |

### P4-008 PR Queue Action Plan

| PR | Action |
|---|---|
| #749 | Keep draft. Apply/commit ruff cleanup from isolated worktree, then split unrelated dashboard/data/cache/session artifacts before review. |
| #754 | Treat as Command Center reference spike until canonical IA is implemented. |
| #755 | Rebase or port the local syntax/F841/trades-journal fixes, then rerun CI. |
| #756 | Keep as trade-intent/OMS reference spike until backend contract is adopted. |

## Blocked

### P3-004 VWAP Gate-v2 Recertification

Command attempted:

```text
engine/.venv312-codex-loop/Scripts/python.exe backtest/run_mes_vwap_rank1.py
```

Result:

- Exceeded 15-minute command timeout.
- Continued running as PIDs `35820` and `53564`.
- No `engine/data/gate_v2_verdicts/MES_vwap_rank1.json` artifact existed after polling.
- Both `run_mes_vwap_rank1.py` processes were stopped.

Blocker:

```text
The current runner is too slow or stuck under patched RTH semantics for an unattended foreground pass.
```

Next action:

```text
Instrument or profile run_mes_vwap_rank1.py, then add a bounded smoke/fast mode before rerunning the full certification.
```

