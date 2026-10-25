# JARVIS Post-Cutover Next Top 10

**Goal:** Convert the canonical dashboard host from incident-recovered to authority-defined: the runtime is back up and the source-integrity layer is live, so the next hour should reduce deploy drift and clarify whether the canonical tree is a serving-only host or a reproducible Git-backed deployment surface.

**Strategy:** Avoid any live engine/risk/kill-switch mutations. Use the new source-integrity panel as the scoreboard, keep changes dashboard-only unless explicitly staged elsewhere, and prefer clean-worktree migration or explicit boundary docs over destructive resets.

## Top 10 ROI tasks

1. Resolve the remaining canonical deploy `source_integrity` findings one-by-one, starting with required-path gaps like `AGENTS.md`.
2. Decide and document the deploy model: clean authoritative worktree migration vs serving-only canonical tree with hard drift boundaries.
3. Quantify which canonical drift entries are intentional runtime-only artifacts vs true source drift.
4. Create a minimal archive-safe migration script for dashboard-only cutovers from the authoritative worktree.
5. Carry the auth-aware Playwright config improvement back through the clean worktree PR path so future gates stay truthful.
6. Add a dedicated local check command that proves authenticated `/mission-control` and `/api/runtime-snapshot` together after PM2 restart.
7. Stage a separate `[safety-review]` review of earlier `engine/.env` provenance restoration with no runtime value changes.
8. Decide whether PR #779 should wait for billing recovery or be treated as a local-verification-only emergency merge candidate.
9. Preserve a rolling archive of post-cutover runtime evidence snapshots for drift comparison.
10. Re-rank the next queue only after the deploy-authority decision is explicit.

## Recommended immediate next action

Use the live `source_integrity` payload as the guide and fix the lowest-risk remaining canonical deploy finding first, without touching engine config or doing any full-tree reset.
