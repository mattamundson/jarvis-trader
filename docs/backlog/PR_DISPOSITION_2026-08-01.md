# PR + Branch Disposition — 2026-08-01

Source: `gh pr list --repo mattamundson/jarvis-trader --state open --json number,title,headRefName,baseRefName,mergeable,isDraft,createdAt` (30 open PRs, run 2026-08-01) plus `git rev-list --count` divergence checks against `origin/master` (81a5aa1) and the two stacked-base branches. `mergeable` is GitHub's own computed field against each PR's declared base — used in place of a per-PR `git merge-tree` per the task's own fallback instruction.

## Highest priority — not a PR, needs Amo's decision NOW

| Branch | Ahead / behind master | Last commit | PR? | Disposition |
|---|---|---|---|---|
| **`wip/health-assertions-mr-3.6`** | **185 ahead / 17 behind** origin/master (81a5aa1) | 2026-08-01 22:30, "feat(dashboard): surface audit retention loop status" | **None ever opened** | **FLAG FOR AMO.** Contains dashboard work overlapping Phase 5 (dead-import/bundle fix, aae890c), Phase 6.7 (validation/perf stabilization, b25bcb2), Phase 10.1 (master-health API: `app/api/master-health/route.ts`, `MasterApiStatusBadge.tsx`, `useMasterHealth.ts`), and much of Phase 11 (agent-permissions.ts, agent-audit page/panel/hook/route). It has now diverged (17 commits behind master, not a clean fast-forward) — the longer this sits un-PR'd the worse the eventual rebase gets. **Two options, Amo's call: (1) open a PR now for review while the rebase is still small, or (2) explicitly declare it superseded/abandoned** so the phase-drain queue stops holding Phase 5/6.7/10.1/11 open pending it. This queue (`AGENT_TASK_QUEUE_2026-08-01.md`) already deliberately routes every other task around this branch — every day it stays unreviewed is a day those four phases stay blocked. |

## Open PRs (30) — by disposition

### READY — mergeable as-is, no action needed before Amo reviews (13)

| # | Title | Head → Base | Draft | Created |
|---|---|---|---|---|
| 571 | test(dashboard): E2E smoke suite across all 50 routes + drain fixes | test/dashboard-e2e-smoke → master | draft | 08-01 |
| 567 | fix(briefing): drop halted MGC from DEFAULT_BRIEFING_SYMBOLS (t029) | roi-drain/t029-mgc-briefing-symbols → master | draft | 08-01 |
| 557 | fix(discord): reset reaction_watcher backoff only after real auth | fix/reaction-watcher-backoff-reset → master | draft | 08-01 |
| 535 | fix(engine): document PRB-09 fail-open justification | fix/prb-09-fail-open-account-state → master | ready | 07-29 |
| 527 | fix(engine): apply loss-tracker size reduction to real order submission (PRB-01) | fix/prb-01-loss-tracker-size-discarded → master | ready | 07-29 |
| 487 | fix(data): deploy missing TV-CDP watchdog task | fix/tv-cdp-watchdog-deploy-onmaster → master | ready | 07-24 |
| 464 | feat(skills): TradingView MCP skill + /jarvis-tv-chart | claude/tradingview-mcp-tools-5yah1x → master | ready | 07-24 |
| 463 | fix(deep-analyzer): catch httpx.InvalidURL | claude/process-identification-zz670b → master | ready | 07-24 |
| 459 | feat(analysis): Corey self-report vs mechanical divergence grader | claude/levels-scorekeeper-bootstrap-csto43 → master | ready | 07-21 |
| 456 | docs: Compound foundations — agent tiering + STATE memory | claude/usage-skill-analysis-5lb0lp → master | draft (2wk stale, undraft?) | 07-18 |
| 454 | feat(backtest): NautilusTrader parity harness | claude/nautilus-trader-analysis-z6ynt6 → master | draft (2wk stale) | 07-17 |
| 450 | fix(sizing): stop sizing equities as micro futures | fix/equity-contract-multipliers → master | ready — recommend priority (real P&L correctness bug) | 07-17 |
| 442 | feat(backtest): gate-v2 WFO harness, 6 Stark TPO signals | feat/stark-signal-wfo-validation → master | draft (2wk stale) | 07-16 |

Note: several of these are still marked draft despite `mergeable: MERGEABLE` and no blocking dependency visible — worth a pass to undraft or explain why not.

### REBASE — mergeable against a stale/wrong base, needs to target current master (11)

| # | Title | Head → Base | Base staleness vs origin/master |
|---|---|---|---|
| 562 | Add es-research-platform package, deterministic pipelines, registry | codex/implement-phase-1-of-research-platform-rv7an0 → master | **CONFLICTING** directly against master — needs rebase |
| 570 | fix(dashboard): wire /parallel-paper to fixed fmtPct (GT-08) | fix/parallel-paper-fmtpct-wiring → fix/corey-standalone-vertex-routing | base is **93 ahead / 154 behind** master (stale de-facto trunk, last synced via merged PR #308) |
| 569 | fix(portfolio): correct equity/cash/daily-pnl key mismatch (GT-01) | fix/portfolio-router-equity-keys-trunk → fix/corey-standalone-vertex-routing | same 154-behind base |
| 568 | docs(safety): reconcile remaining stale kill-switch/risk numbers | fix/kill-switch-docs-reconcile-remaining → fix/corey-standalone-vertex-routing | same base; newest of 3 reconcile PRs (see close-superseded) |
| 466 | fix(gate-v2): tag mc_95th_dd/dsr FAIL in core_reasons | roi-drain/t028-wfo-gate-fail-tagging → fix/corey-standalone-vertex-routing | same base |
| 458 | fix(safety): exclude bool from live_promotion_gate brier check | roi-drain/t022-live-promotion-gate-brier-bool2 → fix/corey-standalone-vertex-routing | same base |
| 457 | docs: include M2K in HALTED-symbol summary | fix/claude-md-m2k-halted-symbol → fix/corey-standalone-vertex-routing | same base |
| 452 | fix(portfolio): restore T1-14 breakeven fix (t022) | roi-drain/t022-tracker-gap → fix/corey-standalone-vertex-routing | same base |
| 444 | fix(ci): restate 'not manual' in deploy-check pytest markers | fix/deploy-check-manual-marker → fix/corey-standalone-vertex-routing | same base |
| 443 | fix(tests): keep cache audit from aborting engine suite | fix/cache-audit-suite-timeout → fix/corey-standalone-vertex-routing | same base |
| 441 | fix(paper-trading): restore lost T0-06 commission deduction | roi-drain/t026-restore-stop-commission-deduction → fix/corey-standalone-vertex-routing | same base |

**Root cause for the 10-PR cluster:** `fix/corey-standalone-vertex-routing` has functioned as a de-facto integration trunk (2 prior converge PRs: #279, #308, both merged) but hasn't been converged with master since, and master has since moved 154 commits ahead. Rather than rebasing all 10 individually onto that stale trunk, the more efficient path is likely a fresh converge PR (trunk → master) first, then re-target these 10 onto master directly — Amo's call on ordering.

### CLOSE-SUPERSEDED — duplicate work, older PR should close in favor of newer (3)

| # | Title | Superseded by | Reason |
|---|---|---|---|
| 492 | Introduce ES research platform package (codex, 07-27) | #562 (same feature, 08-01, newer) | Same "research platform package" scope; #562 is the later attempt on the same topic. Both currently CONFLICTING — Amo should pick one lineage, not run both. |
| 554 | docs: reconcile stale kill-switch/risk numbers (trunk, 07-31) | #568 ("...remaining", 08-01) | Middle PR in a 3-deep reconcile chain on the same base; #568's "remaining" title implies it already accounts for this one. |
| 451 | docs: reconcile stale kill-switch/risk numbers (07-17) | #568 | Earliest of the same 3-PR reconcile chain (451 → 554 → 568), same topic, same base branch, superseded twice over. |

### BLOCKED — depends on another PR landing first (2)

| # | Title | Blocked on |
|---|---|---|
| 523 | fix(ops-console): disable manual trade simulation against dead endpoint (GT-41) | #462 (base: merge/roadmap-to-master-2026-07-23) — already flagged as held in queue (P12-5) |
| 465 | fix(llm): retry Kimi last-resort even when it served as decision primary | #462 (same base) |

### NEEDS-AMO-DECISION (1)

| # | Title | Status |
|---|---|---|
| 462 | merge/roadmap-to-master-2026-07-23 → master (P0-2 real IB path + 139 commits, 19 conflicts resolved) | **CONFLICTING**, draft. Base is now 139 ahead / 91 behind master — the 19 conflicts it already resolved were resolved against a master that's since moved 91 commits further. Already flagged in the queue's own held list (P12-4, "PR #462 tombstone... rescope recommended"). A fresh 91-commit-stale re-resolve is high-risk; recommend Amo either (a) tombstones this PR and cherry-picks the still-wanted P0-2 real-IB-path pieces into a fresh PR against current master, or (b) commits to a full re-resolve now before master drifts further. #523 and #465 are stacked on this branch and blocked either way. |

## Summary

- 30 open PRs total + 1 un-PR'd branch (wip/health-assertions-mr-3.6, highest priority).
- READY: 13 · REBASE: 11 · CLOSE-SUPERSEDED: 3 · BLOCKED: 2 · NEEDS-AMO-DECISION: 1.
- Two systemic issues found beyond individual PR triage: (1) `fix/corey-standalone-vertex-routing` is an unmaintained de-facto trunk 154 commits behind master, silently stacking 10 open PRs on stale ground; (2) a 3-deep duplicate chain on "reconcile stale kill-switch numbers" (451→554→568) should have closed the earlier two when the later ones opened.

This is a report only — no PRs were merged, rebased, or closed by this task.
