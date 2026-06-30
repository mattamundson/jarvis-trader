# loop-reports

Output directory for autonomous loop runs (e.g. scripts/loops/triage-loop.ps1).
Loop-owned — curated state lives in CURRENT_STATE.md / MEMORY.md.

Two report kinds:
- `triage_*.md` and `*.log` — disposable, gitignored.
- `YYYY-MM-DD-overnight.md` — overnight cloud-Routine reports (see
  docs/runbooks/OVERNIGHT_ROUTINE_RUNBOOK.md). Intentionally **tracked** so each
  report rides along in its `[overnight]` draft PR for morning review.

`.heartbeat` is a local liveness signal (watched by scripts/loops/heartbeat-check.ps1)
and is gitignored. This README is tracked.

See `_example-overnight-report.md` for a worked reference of the overnight report
format (a read-only dry run showing the engine-down DEGRADED path).
