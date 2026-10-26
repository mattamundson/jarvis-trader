# JARVIS Trader next-hour production-readiness loop — runtime snapshot freshness

## REASONING

1. What is being asked: continue from the merged runtime-truth tranche, choose the next highest-ROI one-hour goal, execute it, verify it, then re-rank and keep looping toward full dashboard production readiness.
2. The step people usually skip: production dashboards fail from stale truth and unreproducible local deploy state, not just missing UI. The current highest-risk gap is that `phase0_runtime_truth_snapshot.json` was manually generated and the canonical deploy directory has broken `.git` metadata.
3. The answer: first make the runtime truth artifact self-refreshing and observable without touching live engine/risk/kill-switch config. If completed, re-rank and move to source/deploy integrity repair next.

## Safety boundary

- No edits to live engine risk settings, kill-switch settings, broker routing, paper/live mode, or DO_NOT_TRADE lists.
- No operational commands for MCL/MNQ.
- Any live engine/risk/kill-switch config work requires a dedicated `[safety-review]` PR and explicit human approval.
- This loop may create dashboard/ops scripts, scheduled task wrappers, documentation, and read-only verification artifacts.

## Current verified baseline

- PR #776 merged: A-01 read-only runtime snapshot producer.
- PR #777 merged: Mission Control runtime snapshot panel.
- Local dashboard PM2 process was restored and authenticated `/mission-control` smoke passed.
- Canonical deploy directory is not a valid git repository; treat it as a deploy target until repaired.

## Top 10 highest-ROI tasks now

1. **Automate A-01 snapshot refresh** — make Mission Control truth fresh without manual artifact generation.
2. **Add freshness verification / alertable status** — fail visibly if the scheduled artifact is stale or generation fails.
3. **Repair canonical deploy git state** — replace broken `.git` deployment path with a clean, reproducible checkout/worktree.
4. **Add source-integrity panel state** — show local commit, branch, dirty count, PR/CI state, and deploy-vs-master drift.
5. **Add dashboard-engine contract drift tests** — freeze critical `/health`, `/trading-status`, `/config/overview`, `/pnl/truth` payload assumptions.
6. **Expose runtime contradiction ledger** — track kill switch, paper/live, IBKR ports, enabled-not-tradeable, and eligibility disagreements over time.
7. **Add incident bundle export** — one-click bundle with snapshot, PM2 status, engine health, dashboard smoke, git state, and redacted logs.
8. **Harden tailnet/public dashboard verification** — verify local 3010 and tailnet host with the same smoke contract.
9. **EOD operator report automation** — synthesize JSONL monitoring archive + DB pipeline/trade/approval data into markdown report.
10. **Options/equities readiness surface** — SPY/QQQ/VIX status panel for cache/data/chain/freshness readiness, without trading activation.

## Next-hour goal

**Goal A:** ship and verify a safe recurring A-01 snapshot refresh path.

Acceptance criteria:

1. A deterministic wrapper exists that runs the merged `scripts/phase0_runtime_truth_snapshot.py --force`, writes to the live artifact path, and logs success/failure.
2. The wrapper is committed/pushed via a clean PR branch or explicitly marked local-only if git repair blocks PR flow.
3. A Windows Scheduled Task exists or is updated for recurring refresh.
4. The scheduled task is run once on demand and verified by reading back Task Scheduler state and the artifact timestamp.
5. Live authenticated `/api/runtime-snapshot` reports fresh data from the newly generated artifact.
6. Live authenticated Playwright smoke verifies Mission Control renders the refreshed snapshot panel.
7. No live engine/risk/kill-switch/broker config changed.

## Execution strategy

1. Create a clean worktree from `origin/master` for ops wrapper/script changes.
2. Add wrapper and installer/audit script for the scheduled refresh, with logs under `logs/` and no secrets in command-line arguments.
3. Run unit/static verification for the script path and A-01 producer.
4. Push PR if checks are clean; merge only after blocking checks pass.
5. Deploy wrapper locally to the current dashboard/deploy path by archive-copy if canonical `.git` remains broken.
6. Register/update the scheduled task using a PowerShell script file, not fragile inline shell quoting.
7. Start the task manually, verify LastTaskResult, verify artifact timestamp, verify dashboard API and page.
8. Re-rank the next 10 tasks and continue with the next highest safe tranche.

## Finish line for this loop

A fresh runtime truth snapshot is produced by a durable scheduled task and Mission Control renders it live. If any task scheduler action is blocked by Windows permissions, stop the scheduler step, preserve the wrapper, report the blocker, and continue with PR/script verification only.
