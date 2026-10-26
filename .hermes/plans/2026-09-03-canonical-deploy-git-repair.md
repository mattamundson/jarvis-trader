# JARVIS Trader loop 2 — canonical deploy git repair

## REASONING

1. What is being asked: after completing snapshot-refresh automation, re-rank the next ten highest-ROI tasks and continue the loop.
2. The step people usually skip: local dashboard truth can pass while the deploy directory remains unreproducible. `C:/Users/mattm/ThinkorSwim/jarvis-trader` currently cannot answer `git status`, so every future deploy risks archive-copy drift.
3. The answer: repair git metadata in-place without overwriting tracked files, then verify the deploy directory can report branch/head/status while preserving live `.env`, data, logs, and runtime artifacts.

## Top 10 highest-ROI tasks after snapshot-refresh automation

1. **Repair canonical deploy git metadata safely** — restore `git status/log/fetch` in `C:/Users/mattm/ThinkorSwim/jarvis-trader` without destructive reset.
2. **Add deploy-vs-origin drift audit** — script compares local deploy tree to `origin/master` and reports source/runtime dirt explicitly.
3. **Expose source integrity in Mission Control** — branch/head/dirty count/PR checks visible to operator.
4. **Schedule snapshot freshness watchdog** — verify scheduled task last result + artifact age and alert if stale.
5. **Add dashboard-engine contract tests** — pin `/health`, `/trading-status`, `/config/overview`, `/pnl/truth` schema expectations.
6. **Add contradiction history ledger** — append each snapshot summary for kill-switch/IBKR/eligibility trend review.
7. **Incident bundle export** — generate redacted zip/markdown evidence pack for the current runtime state.
8. **Tailnet smoke parity** — same auth smoke for local `3010` and Tailscale host.
9. **MES/SPY/QQQ/VIX readiness surface** — operator panel showing validation/freshness, not routing changes.
10. **Canonical deploy path migration** — if in-place repair is insufficient, replace with a clean `master` worktree after archiving deploy-only artifacts.

## Next-hour goal

**Goal B:** repair canonical git metadata in-place, safely and reversibly.

Acceptance criteria:

1. Existing broken `.git` is archived under `C:/Users/mattm/Archive/2026/`.
2. Canonical deploy directory has a real `origin` remote and local `master` HEAD at current `origin/master`.
3. No working-tree files are overwritten by a hard reset.
4. `git status --short --branch`, `git log --oneline -1`, and `git diff --stat` work.
5. Live dashboard remains healthy after the metadata repair.

## Safety boundary

- No `git reset --hard` in the deploy directory.
- No file deletion; archive broken metadata instead.
- No engine/risk/kill-switch/broker config edits.
