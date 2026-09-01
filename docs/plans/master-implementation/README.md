# JARVIS Master Implementation Plan Package

This package is the working source for the JARVIS Master Implementation Plan.

Status: candidate v1.0, created 2026-09-01.

Use these files together:

- `JARVIS_MASTER_IMPLEMENTATION_PLAN_V1.md` - canonical product, architecture, delivery, and gate plan.
- `CURRENT_STATE_INVENTORY_2026-09-01.md` - verified repo and project-state inventory used by the plan.
- `PR_ISSUE_SPIKE_DISPOSITION_2026-09-01.md` - current treatment of open PRs, issues, and spike branches.
- `IMPLEMENTATION_BACKLOG.json` - machine-readable backlog for the in-session drain loop.
- `PASS8_VWAP_RUNNER_BOUNDS_2026-09-01.md` - bounded VWAP recert runner controls and smoke evidence.
- `PASS9_IB_AND_VWAP_RECERT_2026-09-01.md` - refreshed IB verdicts, VWAP profiling, optimization, and canonical VWAP verdict.

Formal implementation rule:

1. Work against this package, not ad-hoc chat claims.
2. Treat pre-plan branches and PRs as spikes until disposition says otherwise.
3. Do not promote any strategy, execution path, or live setting without the matching gate evidence.
4. Keep `LIVE_TRADING_ENABLED=False` unless Amo explicitly approves a separate live-promotion gate.
