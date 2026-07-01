# Outstanding local actions (2026-07-01)

Two items a cloud/CI session cannot complete — both need the operator's local
machine, where the running engine and IB Gateway actually live. A cloud
session verified this directly (`curl localhost:8010/health` — connection
refused) rather than assuming it. Run these locally, then delete this file or
mark both done.

## 1. Land the stranded `worktree-dashboard-honesty-safety` branch

Flagged in `docs/CURRENT_STATE.md`'s "Current reality" note as staged-but-not-
pushed, with a `[safety-review]` equity-peak clamp that activates on the next
`restart_engine.ps1`.

```bash
./scripts/audit-stranded-work.sh
```

Surfaces it (and anything else stranded). Push it, open a PR, tag it
`[safety-review]` per `.claude/rules/commits.md` since it touches the safety
layer.

## 2. Check MES/MGC RV-filter live-trade readiness

The `min_rv_annualized=9.0` filter passed gate-v2 for both instruments on
2026-05-24 but is held pending 60+ live trades for calibration/confirmation
(see `engine/CLAUDE.md` Active Instruments table).

```bash
cd engine && .venv/Scripts/python.exe scripts/rv_filter_calibration_report.py
```

**Do not** use `data/paper_trades.json` for this — it's documented as
synthetic seed data (`scripts/seed_paper_trades.py` — "Synthetic Paper Trade
Seeder"), predates MGC's approval, and has zero MGC rows. A prior session
almost reported a false readiness number off this file before catching the
mismatch; the script above reads the real live ledger instead.

If either instrument shows `ready: true`, enabling the filter is still a
separate, explicit Tier-3 / gate-v2 decision — this script only tells you
whether the data exists to make that decision, per its own read-only scope
(`engine/analytics/rv_filter_calibration.py`).
