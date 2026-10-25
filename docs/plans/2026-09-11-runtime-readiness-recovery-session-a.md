# JARVIS Runtime Readiness Recovery — Session A Plan

> **For Hermes:** Execute this as a safe runtime/docs lane only. Do not edit live trading, risk parameters, kill-switch state, `.env`, `.env.local`, or symbol routing. Do not use MCL/MNQ operationally.

**Goal:** Restore and verify JARVIS dashboard monitoring-readiness for real-time analysis.

**Architecture:** Use runtime truth over PM2 claims: sanitized PM2/process snapshot → listener ownership → HTTP health → targeted dashboard build/restart if `.next` artifacts are missing → engine health diagnosis/restart only if necessary → reproducible audit script.

**Tech Stack:** Windows PM2, Next.js dashboard on `:3010`, FastAPI engine on `:8010`, IBKR paper port `4002`, TradingView CDP `9222`, SQLite ledger, Python audit script.

## Finish line

- `http://127.0.0.1:8010/health` returns 200.
- Authenticated dashboard `/` and `/mission-control` return 200.
- Dashboard proxy `/api/engine/health` and `/api/runtime-snapshot` return 200.
- `scripts/jarvis_dashboard_recommendation_audit.py --json` exits 0 and writes latest artifacts.
- `monitoring_ready=true`, or every remaining blocker is documented as external/manual.
- `execution_ready` remains false unless a separate `[safety-review]` PR exists.

## Steps

1. Capture sanitized PM2/process/listener state. Print only name/status/pid/restart_time/cwd.
2. Check `.next/required-server-files.json`, `.next/server/app/page.js`, `/api/runtime-snapshot` route bundle, and dashboard package scripts.
3. If dashboard artifacts are missing or listener is stale, run `pnpm run build:clean`, restart only `jarvis-dashboard`, then verify HTTP.
4. Inspect engine logs for `port_guardian`, startup failures, env poisoning, or port conflict. Do not print secrets.
5. If engine is not listening and PM2 entry is stale/restarting, restart only `jarvis-engine` using canonical PM2 entry; do not run `restart_engine.ps1` because it can rotate env/client IDs.
6. Verify direct engine health and dashboard proxy health.
7. Re-run audit script and write final report/handoff.
