# JARVIS Session Handoff Template

> Copy this template. Fill in all fields. Save as `handoff-YYYY-MM-DD-HH.md` in this directory.
> Use BEFORE /compact or session end. Read FIRST when resuming.

---

```yaml
session_id: "2026-04-02-14"
goal: "Brief description of what this session was working on"
status: "in_progress | completed | blocked"

files_changed:
  - path: "engine/main.py"
    change: "Added X endpoint for Y purpose"
  - path: "dashboard/app/page.tsx"
    change: "Fixed Z component to use fetchEngine"

decisions:
  - "Chose SQLite over Postgres for RL cache because portability"
  - "Disabled Polymarket by default (U.S. regulatory concern)"

blockers:
  - "Need engine restart after config.py changes (no --reload flag)"
  - "Anthropic billing = zero, pipeline agents will fail until topped up"

next_steps:
  - "Run full test suite: cd engine && .venv/Scripts/python -m pytest tests/ -v"
  - "Check IB Gateway paper port 4002 connection"
  - "Investigate composite PF discrepancy (Sharpe 2.23 vs PF 0.28)"

context_to_reload:
  - "engine/config.py:1-50 — capital parameters ($10K)"
  - "engine/backtest/signals.py — STC params OS=15, OB=83"
  - "engine/risk/safety_layer.py — kill switch logic"
  - "MEMORY.md — current project state"

test_status:
  passing: 235
  failing: 0
  last_run: "2026-04-02"

engine_state:
  port: 8010
  ib_gateway: "paper port 4002"
  kill_switch: "INACTIVE"
  daily_pnl: "$0.00"
```

---

## How to Use

1. **Before `/compact`**: Copy template, fill in all fields, save as `handoff-YYYY-MM-DD-HH.md`
2. **Before closing Claude Code**: Same as above
3. **On session resume**: Run `Read("jarvis-trader/docs/session-logs/handoff-LATEST.md")` FIRST
4. **After completing a phase**: Update `status` field and add to `next_steps`

## Naming Convention
```
handoff-2026-04-02-14.md  → April 2, 2026, 2pm session
handoff-2026-04-02-22.md  → April 2, 2026, 10pm session
```

## What Makes a Good Handoff
- Specific file paths with line numbers when context-critical
- Decisions with RATIONALE (not just "chose X")
- Blockers that are actionable (what needs to happen)
- Next steps in priority order
- Test status snapshot
