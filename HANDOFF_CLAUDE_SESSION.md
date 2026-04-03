# JARVIS TRADER — Claude Cowork Session Handoff
**Date**: 2026-04-03 (updated post-Sprint 16 completion)
**Session type**: Strategy/planning (Cowork) + active Sprint 16 execution (Claude Code in Cursor)
**Branch**: master
**Sprint 16 status**: COMPLETE — all 5 stories `passes: true`

---

## SPRINT 16 COMPLETION SUMMARY

All 5 stories complete. 1,209 tests passing, 0 failures, 26/26 dashboard routes, 0 TypeScript errors.

| Story | Commit | Key Change |
|-------|--------|-----------|
| US-1605 | be8cf99 | inject_pipeline_deps wired; deprecated strategy_router deleted |
| US-1601 | f9fc4a6 | STC pre-filter made config-driven (LOW=15/HIGH=83); /pipeline/signal-debug endpoint added |
| US-1602 | 93464ae | MCL OS=23/stop=0.50/T1=1.00; composite target_3 exit bug fixed |
| US-1604 | 1654c5a | Nightly consolidator (04:00 ET APScheduler) + trade classifier hook in close_trade() |
| US-1603 | 8270c43 | DB health report written — 3 critical anomalies documented |

**Final git log (top 10)**:
```
6462b85 feat: US-1606 — enhance DB health reporting with additional checks
8270c43 docs: US-1603 — DB health report (ghost DB, NULL pnl, dual storage)
1654c5a feat: US-1604 — wire nightly learning consolidator + trade classifier hook
e75fb4a chore: US-1601/02/05 marked passes:true in prd.json
93464ae feat: US-1602 — MCL WF params (OS=23/stop=0.50/T1=1.00), composite exit fix
48af2d1 docs: strategy canon HTML review + builder script
be8cf99 fix: US-1605 — wire inject_pipeline_deps, remove deprecated strategy_router
6a4f1d4 docs: add strategy canon TRADING_RULES and EQUATIONS
67e52e2 fix: complete trading-days stats endpoint; extend CI with approval notify tests
6f3ec61 feat: Sprint 14 extended — cost tracking, SQLite paper state, E2E smoke, trade journal + WFE widgets
```

---

## US-1603 CRITICAL FINDINGS — NEW P0 BLOCKERS FOR SPRINT 17

These findings fundamentally change Sprint 17's shape. **All three must be fixed before signal frequency verification, MES work, or any dashboard P&L numbers can be trusted.**

### P0-A: Ghost Database
`engine/jarvis_trader.db` is a **0-byte ghost file**. The real database is at `engine/data/jarvis_trader.db`. Any code reading from `engine/jarvis_trader.db` gets an empty database. This explains why the dashboard shows anomalous balances and why validation gate stats look wrong.

### P0-B: NULL pnl in All Paper Trades
All 6 SQLite paper trades have `pnl = NULL`. The `close_trade()` path in `portfolio/tracker.py` never writes the P&L value back to SQLite on trade close. This means:
- The learning loop consolidator (just wired in US-1604) will process trades with NULL pnl — garbage in, garbage out
- The ValidationGatesWidget profit factor calculation is broken
- The $1,772.33 balance anomaly is explained: portfolio endpoint was computing from NULL + wrong DB path

### P0-C: Dual Storage Divergence
**416 trades exist in JSON files** vs **6 trades in SQLite**. JSON is the actual source of truth — the paper trading engine has been writing to JSON all along. SQLite was intended to be the canonical store but the write path was never completed. This means:
- 410 trades are invisible to any endpoint reading SQLite
- The learning loop is training on 6 records instead of 416
- Validation gate trade count (60-trade gate) is reading 6 instead of the real number

---

## SPRINT 17 — SHAPE AND PRIORITIES

Sprint 17 prd.json is written at `C:\Users\mattm\ThinkorSwim\jarvis-trader\prd.json`.

**Priority order**: DB fixes first (US-1701, 1702, 1703), then MES foundation (US-1704, 1705).

| Story | Title | Priority |
|-------|-------|----------|
| US-1701 | Fix ghost DB path — canonicalize to engine/data/jarvis_trader.db | 1 |
| US-1702 | Fix NULL pnl — complete the SQLite close_trade() write path | 2 |
| US-1703 | Unify dual storage — migrate 416 JSON trades into SQLite | 3 |
| US-1704 | Recover n-autoresearch experiment loop files | 4 |
| US-1705 | MES search space definition + first 10 experiments | 5 |

---

## CURRENT SYSTEM STATE (post-Sprint 16)

### Engine (port 8010)
- **Status**: Requires `.\restart_engine.ps1` to activate Sprint 16 changes (migration + scheduler jobs)
- **Tests**: 1,209 passed, 94 skipped, 0 failures
- **DB**: TWO databases exist — `engine/jarvis_trader.db` (0-byte ghost), `engine/data/jarvis_trader.db` (real, 6 SQLite trades + 416 JSON trades)
- **STC pre-filter**: Now config-driven. LOW=15, HIGH=83. Signals at OS/OB extremes skip LLM; mid-range signals go through full pipeline.
- **MCL params**: OS=23, stop=0.50, T1=1.00 (walk-forward validated)
- **Learning loop**: Wired but will process NULL pnl until US-1702 is fixed
- **Anthropic credits**: Confirmed $50+ — LLM pipeline fully operational

### Dashboard (port 3010)
- **Build**: 26/26 routes, 0 TypeScript errors
- **Validation gates**: Reading from wrong/empty DB until US-1701/1702 fixed

### Paper Trading
- **Real trade count**: 416 trades in JSON (source of truth), 6 in SQLite (broken)
- **P&L**: Cannot be trusted until NULL pnl is fixed and dual storage unified
- **30-day validation clock**: Started 2026-04-02. Day 1 = 2026-04-02. Must complete by 2026-05-02.

### Validated Instruments
| Symbol | TF | WFE | Status |
|--------|----|-----|--------|
| MCL | 1h | 0.82 | APPROVED — paper active, now using WF params (OS=23) |
| MNQ | 1h | 0.57 | APPROVED — paper active |
| MGC | 1d | 0.14 | HALTED |
| MES | 1h | 0.09 | DO NOT TRADE — experiment loop development pending |

---

## SPRINT 17 CLAUDE CODE PROMPT

Paste this into a fresh Cursor Claude Code terminal after Task 2 (ops setup) is complete:

> "Read `prd.json` at the project root and run `/ralph` to execute Sprint 17.
>
> **Critical context**: US-1603 from Sprint 16 found 3 database P0 blockers that must be fixed before any MES or signal work:
> 1. Ghost DB: `engine/jarvis_trader.db` is 0-byte. Real DB is `engine/data/jarvis_trader.db`. All DB path references need to point to the data/ subdirectory.
> 2. NULL pnl: All paper trades in SQLite have `pnl = NULL` because `close_trade()` in `portfolio/tracker.py` never writes pnl back to SQLite on close.
> 3. Dual storage: 416 trades in JSON, 6 in SQLite. JSON is source of truth. Need migration to SQLite.
>
> Work stories in priority order: US-1701 → 1702 → 1703 → 1704 → 1705. Each story must pass `cd engine && .venv/Scripts/python -m pytest tests/ -v` with 0 failures before the next begins. 5 parallel agents should be deployed and maintained throughout."

---

## IMMEDIATE ACTIONS REQUIRED (Matt — before Sprint 17)

1. **`.\restart_engine.ps1`** — activates Sprint 16 APScheduler jobs and MCL param changes
2. **Set `IB_ACCOUNT_ID`** in `engine/.env` (replace `YOUR_IBKR_ACCOUNT_ID`)
3. **Start IB Gateway** in paper mode (port 4002) if not running
4. **Run smoke test**: `cd engine && .venv\Scripts\python ..\scripts\smoke_test_approvals.py`
5. **Do NOT run signal frequency check yet** — the 416 JSON vs 6 SQLite divergence means the query will return wrong results until US-1701/1702/1703 are complete

---

## FULL TODO LIST (updated)

| Priority | Item | Status | Sprint |
|----------|------|--------|--------|
| P0 | Fix ghost DB path (jarvis_trader.db → data/jarvis_trader.db) | NOT STARTED | S17 US-1701 |
| P0 | Fix NULL pnl in close_trade() SQLite write path | NOT STARTED | S17 US-1702 |
| P0 | Migrate 416 JSON trades into SQLite (unify dual storage) | NOT STARTED | S17 US-1703 |
| P0 | Restart engine + run smoke test | Matt action | Immediate |
| P0 | Set IB_ACCOUNT_ID in engine/.env | Matt action | Immediate |
| P1 | Recover n-autoresearch experiment loop files | NOT STARTED | S17 US-1704 |
| P1 | MES search space + first 10 experiments | NOT STARTED | S17 US-1705 |
| P1 | Signal frequency verification (after US-1701/1702/1703) | Matt action | Post-S17 DB fix |
| P2 | MCL/MNQ parallel scan confirmation | NOT STARTED | S17 or standalone |
| P2 | MES parameter search experiments 11–30 | NOT STARTED | S18 |
| P2 | RL 500-episode training run (MES) | NOT STARTED | S17–S18 parallel |
| P3 | MES experiment dashboard endpoint | NOT STARTED | S17 US-1705 |
| P3 | Learning loop feedback validation | After DB fix | Post-S17 |
| P3 | Sprint 18 prd.json authoring | NOT STARTED | After S17 complete |

---

## KEY DECISIONS (standing)

- **MES**: DO NOT TRADE until WFE ≥ 0.50 via experiment loop. RL agent (PPO) is the MES sandbox. Proper path: experiment loop → WFE gate → isolated paper validation → Tier 3 sign-off.
- **Workflow**: Cowork = strategy/planning/PRD authoring. Claude Code in Cursor = all coding/testing/git.
- **5-agent protocol**: Always maintain 5 parallel agents in Cursor. Replace on completion. Saved to MEMORY.md.
- **DB canonical path**: After US-1701, all code must reference `engine/data/jarvis_trader.db`. Never `engine/jarvis_trader.db`.
- **JSON vs SQLite**: After US-1703, SQLite is canonical. JSON files become archive/backup only.

---

## GIT STATE (post-Sprint 16)

**Branch**: master (5 commits ahead of origin/master)

**Last 10 commits**:
```
6462b85 feat: US-1606 — enhance DB health reporting with additional checks
8270c43 docs: US-1603 — DB health report (ghost DB, NULL pnl, dual storage)
1654c5a feat: US-1604 — wire nightly learning consolidator + trade classifier hook
e75fb4a chore: US-1601/02/05 marked passes:true in prd.json
93464ae feat: US-1602 — MCL WF params (OS=23/stop=0.50/T1=1.00), composite exit fix
48af2d1 docs: strategy canon HTML review + builder script
be8cf99 fix: US-1605 — wire inject_pipeline_deps, remove deprecated strategy_router
6a4f1d4 docs: add strategy canon TRADING_RULES and EQUATIONS
67e52e2 fix: complete trading-days stats endpoint; extend CI with approval notify tests
6f3ec61 feat: Sprint 14 extended — cost tracking, SQLite paper state, E2E smoke, trade journal + WFE widgets
```

**Uncommitted changes**: None (all Sprint 16 work committed)
**Untracked**: tradingview-mcp (submodule with modified content — do not commit)

---

## SAFETY RULES (never override)
- `LIVE_TRADING_ENABLED = False` — paper mode only
- `REQUIRE_HUMAN_APPROVAL = True` — never disable
- Kill switch: -2% daily P&L OR -10% drawdown
- Port 4001 (IB live) permanently blocked during paper phase
- Safety layer is hardcoded Python — never LLM

---

*Handoff updated: 2026-04-03 post-Sprint 16 completion*
*Next action: Matt runs ops setup (restart + .env), then Sprint 17 prompt into fresh Cursor session*
