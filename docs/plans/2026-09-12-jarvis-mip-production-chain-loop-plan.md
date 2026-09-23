# JARVIS MIP + Production Chain Loop Plan

## Finish line for this tranche
Create a clean, isolated planning/governance lane that reconciles:

1. JARVIS-MIP v1.x master implementation governance.
2. The new “one chain of truth” production-hardening input.
3. Current repo reality on `origin/master`.

Do this without touching the dirty canonical serving tree, without changing runtime trading behavior, and without opening live/canary authority.

## Constraints
- Paper authority only; no live/canary authorization.
- No engine `.env`, dashboard `.env.local`, risk-limit, kill-switch, broker-order, strategy-promotion, or DO_NOT_TRADE symbol changes.
- MCL and MNQ remain DO_NOT_TRADE.
- Work on branch `planning/jarvis-mip-production-chain-20260912` in worktree `C:/Users/mattm/ThinkorSwim/wt-jarvis-mip-production-chain-20260912`.
- Preserve dirty state in `C:/Users/mattm/ThinkorSwim/jarvis-trader` by avoiding edits there.

## Steps
1. Register isolated workstream ownership in `~/.Codex/session_manifest.json`.
2. Inspect existing plan/governance branches and current master planning files.
3. Reconstruct the current authoritative planning state from existing branch artifacts, not the dirty tree.
4. Add a production-hardening addendum/crosswalk that factors in the new “one chain of truth” input.
5. Add/adjust machine-readable governance only if it can be validated locally.
6. Run the narrow validation suite available in this worktree.
7. Commit a bounded docs/governance checkpoint.
8. Identify the next three dependency-safe tasks.

## Verification targets
- `git status --short --branch`
- JSON/Markdown structural checks for any added artifacts.
- Existing plan/governance validation if present.
- `git diff --check`

## Non-goals
- Do not open ISG-0.
- Do not submit or mutate broker orders.
- Do not alter runtime risk policy or kill switch.
- Do not implement strategy/research/risk/OMS code in this tranche.

## Note on `.hermes/plan.md`
Attempting to write `.hermes/plan.md` in this clean worktree was blocked by the local protected-agent-instruction guard. This normal docs plan is the durable substitute for this tranche; do not bypass the guard.
