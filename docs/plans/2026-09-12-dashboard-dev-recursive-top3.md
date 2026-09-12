# Dashboard-dev recursive top-3 completion plan — 2026-09-12

## Finish line
Advance the `dashboard-dev` workstream through the next safe top-3 items only, in a clean no-push local worktree, with no live trading/risk/kill-switch/broker/.env/symbol-gate changes.

## Safety boundary
- Analysis/read-only dashboard artifacts only.
- No operational actions for MCL, MNQ, MGC, or M2K.
- No push, merge, external publish, deletion, or secret exposure.
- Canonical serving tree stays serving-first; this lane is `C:/Users/mattm/ThinkorSwim/wt-dashboard-dev-recursive-top3-20260912` on `local/dashboard-dev-recursive-top3-20260912` from `origin/master`.

## Top-3 pass 1
1. Preserve the read-only dashboard readiness/recommendation audit scripts and latest report artifacts in a clean local checkpoint lane.
2. Add a recommendation lineage design memo explaining the current attribution gap and a safe implementation/verification path.
3. Add a read-only dashboard readiness badge/scorecard plan for `operator_analysis_ready`, `monitoring_ready`, and `execution_ready` without mutating runtime UI in this pass.

## Verification plan
- `git status --short --branch` and scoped diff/name checks.
- `python -m py_compile` for both audit scripts.
- JSON parse checks for latest reports and key metric assertions.
- Report/memo content checks for safety boundary and exact attribution blockers.
