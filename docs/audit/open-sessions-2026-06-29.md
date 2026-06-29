# Open-Sessions Audit — 2026-06-29

**Question answered:** "Why do I feel like I'm working hard across many sessions but making no
visible progress? Identify every open case, the issue with each, and what must change."

**Scope:** every branch and PR on `mattamundson/jarvis-trader`, classified by *true* content delta
against `master` (three-dot diff vs merge-base — not the raw `ahead` count, which is meaningless
here; see Methodology).

---

## TL;DR — the one-sentence diagnosis

You are not slow. **Work gets *done* but almost never *landed*.** Sessions end at "branch pushed,"
not "merged to master," so `master` — the only thing that is real — barely moves while ~200
branches accumulate. There is no single in-flight list, so every new session starts fresh and
re-attacks problems prior branches already solved. The result is high effort, high token spend,
and a flat finish line.

---

## The numbers

| Metric | Count |
|---|---|
| Branches besides `master` | **~202** |
| Open PRs | **9** (3 ready, 2 clean drafts, 1 stacked draft, 1 unreviewable giant, 1 dev-env draft, 1 order-path under safety review) |
| Open issues / tracker | **0** — there is no backlog or in-flight registry anywhere |
| Branches whose content is **already in master** (zero delta) | **98** — pure debris |
| Reviewable stranded sessions (real delta, no PR) | **47** |
| Giant / unreviewable orphans (>30 files, no PR) | **48** |

**Read that again:** ~half the "sprawl" (98 branches) is already merged or superseded — it's
uncleaned debris that makes the situation *look* worse than it is. The genuinely stuck, reviewable
work is ~47 small branches plus 9 PRs. That subset is the actual problem.

---

## Root causes (the recurring problem, not the symptoms)

1. **"Done" is defined as "branch pushed," not "merged."** The unglamorous last 20% — rebase, fix
   CI, get the safety sign-off, merge, delete the branch — is exactly the 20% that never happens.
   Three PRs (#169, #178, #179) have been *ready* and ignored since June 26.

2. **No in-flight registry + no WIP limit.** Zero issues, a stale `CURRENT_STATE.md` (last touched
   June 18). A new session can't see what's already in progress, so it re-solves it on a new
   branch. Evidence of re-invention: **6× `feat/dashboard-*`, 6× `feat/forward-test*`, 4×
   `feat/bar-quality-*`, multiple `fix/corey-*`, multiple `fix/dsr-*`, multiple `ralph/*` loop
   attempts, #134 → re-extracted as #160.**

3. **`master`'s history was squash-rewritten** (clean integration merges), which orphaned the
   ancestry of ~130 branches. Git now reports them as "1,600 commits ahead" even when their real
   delta is 17 files. A naive merge of any of them would be a catastrophe, so they sit untouched
   and un-mergeable — effectively abandoned by the tooling itself.

4. **Data blobs committed to branches.** `fix/corey-cache-stale-nodata` (PR #160),
   `feat/corey-extract-viewer`, and `claude/beautiful-fermi-yeecq4` each carry **~1.7M lines of CSV
   bar-cache**. They can never be reviewed or merged.

5. **Safety gates with no review ritual.** `[safety-review]` / Tier-3 PRs (#177 order-path, #160
   config defaults) correctly require Amo sign-off — but the sign-off is never *scheduled*, so a
   correct gate becomes permanent paralysis.

6. **Churn counted as progress.** Even merged work gets undone: #175 reverted #172+#174; #180 was a
   "full revert." Motion without displacement.

7. **Tool fragmentation.** `claude/*`, `cursor/*`, `ralph/*`, `worktree-*`, and hand-made branches
   each spawn a namespace; nothing reconciles them.

Your two named examples fit exactly:
- **"Claude loop system — not implemented anywhere":** draft PR **#181** (`/overnight` Routine),
  never finalized, plus a graveyard of parallel loop attempts (`ralph/auto-0605`,
  `ralph/high-roi-*`, `ralph/top10-roi-*`, `feat/forward-test-loop`, `feat/trade-review-loop`).
- **"Hermes agent — no progress":** Hermes code exists in the tree
  (`engine/tests/test_discord_deep_analyzer/test_hermes_upgrade/`, `scripts/hermes_upgrade_scan.ps1`)
  but no open PR is driving it to a verified, documented, on-master state.

---

## The 9 open PRs — per-PR verdict

| PR | Branch | True size | State | Verdict |
|---|---|---|---|---|
| **#169** | `feat/corey-feed-hardening` | 7 files | ready, 19 tests pass | **MERGE NOW** |
| **#178** | `fix/dsr-runner-migration` | ~40 files (mechanical) | ready, static-guard test | **MERGE NOW** |
| **#179** | `feat/funnel-vwap-shadow` | 2 files | ready, observe-only | **MERGE NOW** |
| **#177** | `feat/systematic-exec-bridge` | 5 files | CI `unstable`, order-path | **SAFETY REVIEW** → fix CI → merge or hold. Do not merge unreviewed. |
| **#181** | `claude/overnight-execution` | clean (6↑/1↓) | draft | **FINALIZE & MERGE** — this is "the loop system." Clean and mergeable today. |
| **#182** | `claude/obsidian-second-brain` | clean (5↑/1↓) | draft | **FINALIZE & MERGE** — clean. |
| **#163** | `cursor/fix-dashboard-homepage-crash` | small, real bug | draft, **stacked on #157** | **REBASE onto master**, finalize, merge. Real null-price crash fix. |
| **#157** | `cursor/setup-dev-environment` | AGENTS.md + env | draft | **DECIDE**: merge (unblocks #163) or close. Don't leave it blocking a bugfix. |
| **#160** | `fix/corey-cache-stale-nodata` | **262 files / 1.7M ins** | `[safety-review]` config.py | **CLOSE & RE-SLICE.** Unreviewable (CSV blobs). Cherry-pick the real source files into a <30-file PR. |

---

<!-- BUCKETS START -->
## Bucket R — Reviewable orphans (real delta, NO open PR) — RESCUE or CLOSE

These are the genuine "stranded sessions." Each is small enough to review. For each: either open a
PR and drive it to merge, or close it explicitly. Do **not** leave them in limbo.

| Branch | Files | +Lines | Last commit |
|---|---|---|---|
| `integration/decision-identity-stack` | 26 | 2710 | 2026-06-16 |
| `feat/strategy-factory` | 24 | 3398 | 2026-06-26 |
| `claude/modest-keller-qiartr` | 17 | 88 | 2026-06-26 |
| `feat/stationarity-record-first` | 16 | 1186 | 2026-06-26 |
| `consolidate/gate-integrity` | 14 | 967 | 2026-06-26 |
| `feat/ts-overlay` | 11 | 1280 | 2026-06-22 |
| `claude/compassionate-cerf-2mgcp2` | 11 | 1577 | 2026-06-24 |
| `claude/twitter-link-implementation-4t2bng` | 10 | 893 | 2026-06-26 |
| `feat/queue-shared-dedup` | 8 | 834 | 2026-06-29 |
| `feat/lightweight-charts-jarvis` | 8 | 260 | 2026-06-16 |
| `claude/auction-gate-v2-eval` | 8 | 498 | 2026-06-26 |
| `claude/vix-regime-phase4` | 7 | 264 | 2026-06-24 |
| `claude/clever-bardeen-gkqnzh` | 7 | 1314 | 2026-06-22 |
| `feat/ib-data-watchdog` | 6 | 558 | 2026-06-16 |
| `feat/es-nq-spread-dark-track` | 6 | 1374 | 2026-06-24 |
| `feat/execution-fidelity-gate-wiring` | 5 | 302 | 2026-06-16 |
| `feat/bar-quality-observability` | 5 | 494 | 2026-06-16 |
| `test/backtest-analysis-coverage` | 4 | 511 | 2026-06-24 |
| `feat/trading-status-live` | 4 | 711 | 2026-06-25 |
| `feat/perm-gate-shadow-wire` | 4 | 291 | 2026-06-16 |
| `test/oms-order-router-coverage` | 3 | 711 | 2026-06-22 |
| `fix/us09-trailing-stop-atr` | 3 | 379 | 2026-06-22 |
| `fix/scrub-hardcoded-api-key` | 3 | 12 | 2026-06-16 |
| `feat/saty-atr-strategy` | 3 | 736 | 2026-06-16 |
| `feat/mcpt-trades-bootstrap` | 3 | 134 | 2026-06-24 |
| `claude/nikkei-breakout-critique-y5z3pl` | 3 | 988 | 2026-06-26 |
| `fix/vault-posix-and-smoke-auth-skip` | 2 | 31 | 2026-06-26 |
| `fix/technical-analysis-signal-type` | 2 | 56 | 2026-06-25 |
| `fix/safety-guards-phantom-degraded-2026-06-16` | 2 | 103 | 2026-06-25 |
| `fix/proactive-validation-integrity` | 2 | 212 | 2026-06-16 |
| `fix/paper-order-quote-guard` | 2 | 52 | 2026-06-22 |
| `feat/loader-complete-preference` | 2 | 188 | 2026-06-26 |
| `feat/cache-completeness` | 2 | 853 | 2026-06-26 |
| `feat/bar-quality-audit-cli` | 2 | 215 | 2026-06-16 |
| `feat/backtest-bar-quality-gate` | 2 | 117 | 2026-06-16 |
| `claude/trading-strategy-tools-vi9r2g` | 2 | 187 | 2026-06-24 |
| `claude/fix-confluence-audit-fairness` | 2 | 209 | 2026-06-26 |
| `claude/decision-log-audit-chain` | 2 | 376 | 2026-06-26 |
| `chore/pandas3-ci` | 2 | 3 | 2026-06-26 |
| `test/e6-gating-precedence` | 1 | 120 | 2026-06-16 |
| `fix/lint-vol-target-wiring-import` | 1 | 0 | 2026-06-26 |
| `feat/spread-track-zbzn` | 1 | 34 | 2026-06-26 |
| `docs/safety-do-not-trade-comment` | 1 | 8 | 2026-06-17 |
| `claude/fix-lint-vol-target-import` | 1 | 1 | 2026-06-26 |
| `claude/dsr-forward-test-diagnostic` | 1 | 2 | 2026-06-24 |
| `claude/awesome-euler-yk0q1w` | 1 | 18 | 2026-06-22 |
| `claude/activate-mes-vix-candidate` | 1 | 147 | 2026-06-26 |

> Note: several here are 0–2 line lint/doc shims (`fix/lint-vol-target-wiring-import`,
> `claude/fix-lint-vol-target-import`, `chore/pandas3-ci`, `claude/awesome-euler-yk0q1w`) — almost
> certainly already-superseded; close on sight. Pairs like `fix/lint-vol-target-wiring-import` +
> `claude/fix-lint-vol-target-import` are the same fix done twice — textbook re-invention.

## Bucket G — Large/giant orphans (>30 files, NO open PR) — CLOSE (cherry-pick the idea only if it still matters)

Mostly history-tangle branches (60–77K insertions from re-merged old history) plus two CSV-blob
branches. None is cleanly mergeable. Treat the branch as a write-off; if the underlying idea is
still wanted, re-implement it as a fresh <30-file PR off current `master`.

| Branch | Files | +Lines | Last commit |
|---|---|---|---|
| `feat/corey-extract-viewer` | 244 | 1708194 | 2026-06-26 |
| `claude/beautiful-fermi-yeecq4` | 233 | 1707025 | 2026-06-26 |
| `feat-live-2026-06-18` | 235 | 77009 | 2026-06-18 |
| `feat/strategy-edge-wave` | 179 | 77500 | 2026-06-18 |
| `perf/offload-gather-compute` | 241 | 77072 | 2026-06-19 |
| `perf/offload-ta-compute` | 231 | 76781 | 2026-06-18 |
| `chore/wfo-live-config-match` | 145 | 73858 | 2026-06-17 |
| `chore/discovery-scripts-2026-06-16` | 144 | 72913 | 2026-06-17 |
| `claude/trading-agents-deepdives` | 170 | 72676 | 2026-06-18 |
| `claude/adoring-bardeen-caythe` | 163 | 71992 | 2026-06-18 |
| `feat/b1-trend-diversifiers` | 161 | 71900 | 2026-06-17 |
| `claude/trading-agents-analysis-4w8ivm` | 163 | 71396 | 2026-06-18 |
| `railway/fix-deploy-431971` | 159 | 71078 | 2026-06-17 |
| `feat/regime-conditional-v2` | 154 | 70109 | 2026-06-17 |
| `feat/regime-conditional-verdicts` | 144 | 68978 | 2026-06-25 |
| `feat/family-fdr-standing-gate` | 149 | 68583 | 2026-06-17 |
| `claude/regime-live-endpoint` | 146 | 68406 | 2026-06-17 |
| `fix/paper-maxdd-guard` | 146 | 68414 | 2026-06-17 |
| `feat/cl-trend-validation` | 139 | 68149 | 2026-06-17 |
| `feat/cpcv-validation` | 141 | 67977 | 2026-06-17 |
| `claude/fix-flaky-scanner-tests` | 141 | 67504 | 2026-06-17 |
| `feat/fwdtest-attribution` | 140 | 67441 | 2026-06-17 |
| `fix/us1703-retire-jsonl-store` | 136 | 67361 | 2026-06-17 |
| `feat/mgc-adx-trend-conditioning` | 127 | 65194 | 2026-06-17 |
| `fix/ta-offload-guard` | 152 | 65491 | 2026-06-17 |
| `fix/dashboard-honest-metrics` | 152 | 65491 | 2026-06-17 |
| `fix/dashboard-sota-2026-06-16` | 150 | 65488 | 2026-06-17 |
| `fix/forward-test-curated-ledger` | 123 | 65437 | 2026-06-16 |
| `ralph/north-star-surfacing-2026-06-16` | 130 | 66297 | 2026-06-16 |
| `fix/calibration-direction-aware` | 105 | 63021 | 2026-06-16 |
| `feat/post-trade-analytics` | 102 | 63411 | 2026-06-16 |
| `claude/trading-dashboard-z74mcd` | 104 | 63337 | 2026-06-16 |
| `feat/data-history-extension` | 103 | 62850 | 2026-06-16 |
| `fix/stats-summary-metrics` | 103 | 62824 | 2026-06-16 |
| `feat/post-trade-dashboard` | 102 | 62809 | 2026-06-16 |
| `feat/deploy-runbook-gate` | 102 | 62805 | 2026-06-16 |
| `fix/degraded-feed-trade-guard-pr` | 105 | 62768 | 2026-06-16 |
| `fix/phantom-pnl-aggregate` | 102 | 62725 | 2026-06-16 |
| `feat/live-verdict-pane` | 101 | 62692 | 2026-06-25 |
| `fix/ci-fast-suite-flake-retry` | 102 | 62624 | 2026-06-16 |
| `fix/pin-tzlocal-core` | 103 | 62591 | 2026-06-16 |
| `fix/safety-test-fixtures-2026-06-16` | 101 | 62589 | 2026-06-16 |
| `integration/master-converge-2026-06-16` | 100 | 62578 | 2026-06-16 |
| `chore/sync-master-into-fdr` | 89 | 61632 | 2026-06-16 |
| `feat/spread-pairs-generalization` | 171 | 16001 | 2026-06-24 |
| `feat/discovery-factory` | 142 | 12924 | 2026-06-24 |
| `feat/morning-brief-self-improving` | 40 | 24338 | 2026-06-25 |
| `feat/session-anomaly-mes` | 47 | 5765 | 2026-06-24 |

## Bucket D — Zero content delta vs `master` (already merged / superseded) — DELETE

**98 branches.** Each branch's tree is identical to its merge-base — there is literally nothing to
lose. These are the debris inflating the count. Safe to delete in bulk.

`worktree-rl-executor-flag-gate` `worktree-quirky-swinging-lollipop` `worktree-journal-review`
`worktree-generation-engine` `worktree-feat-gemini-primary-routing` `worktree-dashboard-honesty-safety`
`worktree-cryptic-purring-pond` `test/us0607-live-coverage` `ralph/top10-roi-2026-06-21`
`ralph/top10-roi-2026-06-16` `ralph/ns-surfacing-base-2026-06-16` `ralph/high-roi-2026-06-03`
`ralph/auto-0605` `ralph/auto-0605-rebased` `phase0/emergency-hardening` `perf/health-ib-timebox`
`patch09-llm-fallback` `merge/session-anomaly-into-family-fdr`
`integration/free-daily-to-master-2026-06-26` `integration/family-fdr-to-master-2026-06-25`
`fix/ws-events-403` `fix/today-pnl-label` `fix/test-import-prefix` `fix/test-db-isolation`
`fix/scanner-entry-price-gate` `fix/reconciler-tick-and-pnl-honesty` `fix/price-fallback-staleness`
`fix/phantom-mes-mark-guard` `fix/paper-max-loss-backstop` `fix/master-ci-green`
`fix/ib-data-feed-restore` `fix/ib-data-client-id` `fix/gate-v2-metric-integrity`
`fix/forward-proving-paper` `fix/flaky-intraday-trading-hours-test` `fix/era-aware-price-contamination`
`fix/drawdown-staleness` `fix/degraded-feed-trade-guard` `fix/data-integrity-write-gates`
`fix/dashboard-honesty-safety` `fix/claude-review-skip-when-no-key` `fix/ci-test-ordering-and-verdict-skip`
`fix/ci-test-defects` `fix/ci-eager-db-import` `fix/bar-gate-shadow-test` `feat/wave-a-reliability`
`feat/vol-target-sizer` `feat/vertex-landing` `feat/vertex-ai-integration` `feat/unified-trust-pane`
`feat/tradingview-mcp-gamma-kraken` `feat/trade-review-loop` `feat/tpo-score-layer2` `feat/top10-roadmap`
`feat/tom-forward-track-task` `feat/thinkscript-strategy-sweep` `feat/symbol-aware-charting`
`feat/realtime-signal-broadcast` `feat/quantstats-integration` `feat/promotion-pipeline-extension`
`feat/preholiday-forward-track` `feat/permutation-significance-gate` `feat/paper-stop-monitor`
`feat/p3-register-lineage` `feat/master-scheduler-tile` `feat/llm-degraded-surfacing`
`feat/live-fills-observability` `feat/gate-v2-sample-adequacy` `feat/ft-wiring` `feat/ft-attribution`
`feat/free-daily-export` `feat/forward-test-panel` `feat/forward-test-panel-lineages`
`feat/forward-test-loop` `feat/fdr-saty-clean` `feat/family-fdr-campaign` `feat/edge-ledger`
`feat/discovery-round3` `feat/decision-identity` `feat/decision-identity-p4` `feat/dashboard-tv-widget-3d`
`feat/dashboard-resilience` `feat/dashboard-price-chart-panel` `feat/dashboard-completion`
`feat/claude-on-vertex` `feat/candidate-registry` `feat/beta-harvest-wire` `feat/bar-quality-write-gate`
`feat/amo-edge-verdict-trust-pane` `feat-live-2026-06-22` `docs/llm-decision-identity`
`discovery/daily-trend` `deploy/dashboard` `claude/friendly-mendel-u5hjor`
`claude/contesttrade-belief-ensemble` `chore/engine-lint-green` `backtest/bt10-cohen-composite`
`agent/ci-and-audit`
<!-- BUCKETS END -->

---

## Remediation — do these in order

**Phase 1 — visible progress this week (low risk):**
1. Merge the three ready PRs: **#169, #178, #179.** Instant on-master output.
2. Finalize + merge the two clean drafts: **#181** (the loop system) and **#182.**
3. Rebase **#163** onto `master`, decide **#157**, merge the dashboard crash fix.

**Phase 2 — clear the safety queue (needs Amo):**
4. Schedule the two `[safety-review]` decisions — **#177** (order-path) and the **#160** config
   defaults — as explicit approve/close calls. A gate with no review date is just paralysis.
5. **Close #160**; re-slice its real source files into a <30-file PR with the CSV blobs gitignored.

**Phase 3 — clean the board (makes the in-flight set legible):**
6. Delete the **98 zero-delta branches** (Bucket D) — zero risk.
7. Close the **48 giant orphans** (Bucket G) — write-offs; re-implement ideas fresh if wanted.
8. Walk the **47 reviewable orphans** (Bucket R): each becomes a PR-to-merge or a close. No limbo.

**Phase 4 — stop the recurrence (the actual fix):**
9. **Redefine "done" = merged to `master` + branch deleted.** A pushed branch is not done.
10. **WIP cap ≤ 5.** Maintain ONE in-flight registry — a pinned GitHub issue or a single
    `docs/IN_FLIGHT.md` — that every session reads first and may not add to without parking
    something. This is what kills the re-invention.
11. **Hard PR-size cap (~30 files / ~1000 lines).** Bigger than that = split or it never merges.
12. **Never commit data** (`*.csv`, `*.parquet` bar-caches). Add a pre-commit/CI size gate.
13. **Pick one driver** (Claude Code vs Cursor vs Ralph) or run a weekly convergence session to
    reconcile namespaces. Keep `CURRENT_STATE.md` current at session end.

---

## Methodology

- Branches enumerated via `git for-each-ref refs/remotes/origin` after a full
  `git fetch origin '+refs/heads/*:refs/remotes/origin/*'` (204 refs).
- **True size** = `git diff --shortstat origin/master...origin/<branch>` (three-dot → diff against
  merge-base). The raw two-dot `ahead` count was discarded: `master`'s history was squash-rewritten,
  so orphaned branches report 1,500+ phantom "ahead" commits with a real delta of a handful of files
  (verified on `claude/modest-keller-qiartr`: 1,639 "ahead", actual diff 17 files / 88 lines).
- PR metadata via the GitHub API (`list_pull_requests`, `pull_request_read`).
- Bucket thresholds: `0 files` = already-in-master; `1–30 files` = reviewable; `>30 files` = giant.

_Generated for the open-sessions audit. Read-only analysis — no branches or PRs were modified._
