# NEXT_STEPS — JARVIS TRADER
# Last updated: 2026-04-04 | Sprint 24 COMPLETE | Sprint 25 NOT STARTED

## Current priority

Fix git index corruption, commit all Sprint 24 work in 5 story-grouped commits, then begin Sprint 25.

## Immediate next action

- [ ] Run: `git fsck --full` to assess corruption scope
- [ ] Try: `git read-tree HEAD` to rebuild index from last commit
- [ ] If that fails: fresh clone + copy working files over
- [ ] Then commit Sprint 24 in 5 commits (see groups below)

## Sprint 24 — Ready to Commit (ALL stories DONE ✓)

### Commit 1 — US-2401 Confidence Scoring
- engine/learning/confidence_scorer.py (NEW)
- engine/agents/pipeline.py (MODIFIED)
- engine/routers/learning_router.py (MODIFIED)
- engine/tests/test_confidence_scorer.py (NEW)

### Commit 2 — US-2402 Events Ring Buffer
- engine/events/__init__.py, engine/events/bus.py (NEW)
- engine/routers/events_router.py (NEW)
- engine/main.py (events_router import + mount)
- dashboard/lib/api.ts, dashboard/components/EventsFeedWidget.tsx
- dashboard/app/page.tsx, engine/tests/test_events_bus.py

### Commit 3 — US-2403 Validation Checkpoint
- engine/routers/paper_validation_router.py (MODIFIED)
- dashboard/components/ValidationCheckpointWidget.tsx (NEW)
- engine/tests/test_validation_checkpoint.py (NEW)

### Commit 4 — US-2404 IB Health Monitor
- engine/health/__init__.py, engine/health/ib_monitor.py (NEW)
- engine/notifications/openclaw_notifier.py (MODIFIED)
- engine/main.py (IB health monitor APScheduler job)
- engine/tests/test_ib_monitor.py (NEW)

### Commit 5 — US-2405 Sprint 24 Close-Out
- prd.json (all passes: true)
- SPRINT_24_COMPLETION_REPORT.md

## Sprint 25 — Planned (not started)
Per SPRINT_24_COMPLETION_REPORT.md:
1. Recover git (see above)
2. Run full test suite: pytest tests/ -v (expect 0 failures)
3. Build dashboard: pnpm run build (expect 0 TypeScript errors)
4. Begin next capability sprint

## Blockers

- Git index corrupted (bad sha1 signature) — cannot commit until resolved
- See SPRINT_24_COMPLETION_REPORT.md > Known Issues for detail

## Risks

- Paper validation window: April 2 – May 2, 2026. Only 28 days remaining.
- MES still DO NOT TRADE (WFE 0.09). MCL + MNQ approved and active.
- IB Gateway must stay connected on port 4002 (paper) during validation.

## Notes for next AI session

1. Read CLAUDE.md first (project rules, commands, safety invariants)
2. Read docs/CURRENT_STATE.md second (architecture snapshot)
3. Read SPRINT_24_COMPLETION_REPORT.md third (what just shipped)
4. Read this file fourth (what to do next)
5. Fix git corruption BEFORE touching any code
6. Python venv: engine/.venv/Scripts/python (never system Python)
7. Dashboard: pnpm (system npm is broken)
8. Engine port: 8010 | Dashboard port: 3010
