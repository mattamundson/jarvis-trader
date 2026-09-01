# Current-State Inventory - 2026-09-01

This inventory grounds `JARVIS_MASTER_IMPLEMENTATION_PLAN_V1.md`.

## Repository

- Repo: `C:\Users\mattm\ThinkorSwim\jarvis-trader`
- Remote: `https://github.com/mattamundson/jarvis-trader.git`
- Current branch at inventory time: `feat/pipeline-funnel-t9-20260826`
- Tracked tree at start: no tracked modifications reported by `git status --short`.
- Untracked backlog: large; includes analysis artifacts, diagnostic scripts, reports, generated cache/artifact directories, and worktree-like directories. Do not use broad `git add -A`.
- Worktree count: high; includes canonical repo plus many feature/audit worktrees. Archive/retire only after each worktree is checked for uncommitted source and pushed branch state.

## Canonical Local Docs Read

- `CLAUDE.md`
- `engine/CLAUDE.md`
- `dashboard/CLAUDE.md`
- `docs/CURRENT_STATE.md`
- `docs/JARVIS_TRADER_UNIFIED_CANON.md`
- `docs/JARVIS_SOTA_PLAN.md`
- `docs/LIVE_TRADING_READINESS.md`
- `C:\Users\mattm\Downloads\JARVIS_Conversation_History_2026-09-01.md`
- Latest global handoffs:
  - `C:\Users\mattm\.codex\handoffs\HANDOFF_2026-09-01_x-bookmarks-pipeline-repair.md`
  - `C:\Users\mattm\.codex\handoffs\HANDOFF_2026-09-01_dual-engine-parity.md`

## Runtime / Product Components

Engine:

- FastAPI Python backend.
- Expected local port: `127.0.0.1:8010`.
- Python runtime: `engine/.venv/Scripts/python.exe`.
- Restart path: `restart_engine.ps1`; never use `--reload`.
- Safety-critical areas: `engine/config.py`, `engine/risk/`, kill-switch logic.

Dashboard:

- Next.js dashboard.
- Expected local port: `127.0.0.1:3010`.
- Engine calls should use `dashboard/lib/api.ts` helpers.
- Typecheck command: `dashboard/node_modules/.bin/tsc --noEmit`.

Broker:

- IBKR paper port: `4002`.
- IBKR live port: `4001` remains blocked by policy.
- Live enablement is outside this plan's autonomous scope.

## Standing Safety State

- `LIVE_TRADING_ENABLED=False` is invariant.
- Paper mode only unless separately approved.
- No LLM path owns hard risk or capital authorization.
- Futures sentiment source is Corey Discord market updates only.
- Strategy gate v2 thresholds remain load-bearing for "good strategy" claims.

## Existing Loops / Automation Relevant To This Plan

Observed loop registry already includes:

- `jarvis-roi-engine`
- `jarvis-roi-drain`
- `jarvis-roi`
- `jarvis-ops-drain`
- `jarvis-roadmap-drain`
- `jarvis-nextsteps-drain`
- `dashboard-guard`
- `engine-health-watch`
- `ib-blind-chaos`
- `jarvis-branch-convergence-watch`
- `real-money-readiness`

Decision: do not create a duplicative autonomous scheduled loop for implementation mutation. This session registered `jarvis-master-plan-drain-20260901` as an in-session discovery-drain with top-10-per-pass brakes.

## High-Risk Drift Found

- `docs/CURRENT_STATE.md` contains intentionally retired eligibility sections and older status banners. It is useful for durable paths and invariants, not current trading eligibility.
- `docs/JARVIS_TRADER_UNIFIED_CANON.md` is older than several August 2026 gate and instrument decisions.
- Multiple prior docs state progress in terms of phases or completion, but the 2026-09-01 conversation history corrects that formal implementation had not started because no master plan had been adopted.
- Open PRs around Command Center and trade intent are current technical spikes, not formal implementation.

## Inventory Gaps To Close Next

1. Produce a compact generated repo map: engine routers, dashboard routes, data stores, scripts, tests.
2. Verify current engine health from `127.0.0.1:8010` before any runtime claim.
3. Verify current dashboard health from `127.0.0.1:3010` before any UI claim.
4. Reconcile current branch/worktree state against open PRs.
5. Update or supersede stale docs once the master plan is accepted.

