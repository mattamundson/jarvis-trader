# JARVIS TRADER — Claude Cowork Session Handoff
**Date**: 2026-04-03 (updated post-Sprint 17 completion)
**Session type**: Strategy/planning (Cowork) + Sprint 16 + Sprint 17 execution (Claude Code in Cursor)
**Branch**: master
**Sprint 16 status**: COMPLETE
**Sprint 17 status**: COMPLETE

---

## SPRINT 17 COMPLETION SUMMARY

All 5 stories complete. 1,212 tests passing, 0 failures, 26/26 dashboard routes, 0 ruff errors.

| Story | Commit | Key Change |
|-------|--------|-----------|
| US-1701 | a559f50 | Ghost 0-byte DB deleted. `SQLITE_DB_PATH` constant added to `config.py` pointing to `engine/data/jarvis_trader.db` |
| US-1702 | 66efdac | `close_trade()` now computes pnl with `INSTRUMENT_MULTIPLIERS` (MCL=100, MNQ=2, MES=5, MGC=10). `backfill_pnl.py` written. |
| US-1703 | 1ee915b | JSONL migration: 11 unique trades → 9 inserted, 2 dupes skipped. Source was `portfolio/trades.jsonl` |
| US-1704 | e9fc15d | `experiment_log.py`, `run_experiment.py`, `search_strategy.py`, `mes_search_space.json`, 3 unit tests |
| US-1705 | b4a53ff | `run_walk_forward_for_params()` added to `walk_forward.py`. 10 MES experiments logged. `GET /experiments/mes/status` wired. Report written. |

**Final git log (top 10)**:
```
b4a53ff feat: US-1705 — run 10 MES WFE experiments, add run_walk_forward_for_params, write round1 report
a2882ca feat: US-1705 — add GET /experiments/mes/status endpoint
e9fc15d feat: US-1704 — recover n-autoresearch experiment loop, mes_search_space.json, 3 unit tests
7357dbb chore: US-1703 passes: true — migration ran (9 inserted, 2 dupes)
1ee915b feat: US-1703 — write migration script for JSONL paper trades to SQLite
daa0029 chore: US-1701/1702 passes: true in prd.json
66efdac fix: US-1702 — fix NULL pnl in close_trade(), add INSTRUMENT_MULTIPLIERS
a559f50 fix: US-1701 — add SQLITE_DB_PATH config constant, delete ghost DB
6462b85 feat: US-1606 — enhance DB health reporting with additional checks
8270c43 docs: US-1603 — DB health report (ghost DB, NULL pnl, dual storage)
```

---

## CRITICAL FINDINGS FROM SPRINT 17 — CHANGES SPRINT 18 SHAPE

### Finding 1 — The 416 trades were a miscount (IMPORTANT)
The earlier estimate of 416 JSON trades was wrong. The actual live paper trade source is `engine/portfolio/trades.jsonl` with only **11 trades total** (9 inserted into SQLite, 2 dupes). The 416 figure came from backtest result files, not the live trading engine. This means:
- The 30-day validation gate (60 trades) is at 11/60 after ~2 days
- Signal frequency (US-1601 fix) needs verification immediately — we need ~2/day per instrument
- The real paper trade P&L picture is much smaller than assumed

### Finding 2 — MES WFE = 0.0 at 1h STC (all 10 experiments)
Every MES walk-forward experiment returned WFE = 0.0. The 1h STC signal has no generalizable edge for MES regardless of OS/OB/ATR parameter combinations. Root cause: insufficient 1h MES historical data available via current Polygon key. Sprint 18 must:
1. Rotate the Polygon API key (current one needs rotation per agent report)
2. Fetch 4h and 15m MES data
3. Run experiments 11-30 on 4h timeframe specifically

### Finding 3 — Real paper trade count is 11, not 416
Only 11 trades are in `portfolio/trades.jsonl`. Of these, some are open (MCL positions), some closed. The $7 total P&L mentioned earlier from 3 closed trades is likely accurate. The validation gate clock is running but signal frequency is the critical metric to check now.

---

## CURRENT SYSTEM STATE (post-Sprint 17)

### Engine (port 8010)
- **DB path**: Canonicalized to `engine/data/jarvis_trader.db` via `SQLITE_DB_PATH` in `config.py`
- **P&L tracking**: Fixed — `close_trade()` now computes pnl using `INSTRUMENT_MULTIPLIERS`
- **Paper trades in SQLite**: 9 records (migrated from JSONL)
- **STC pre-filter**: Config-driven, LOW=15/HIGH=83 (Sprint 16 fix)
- **MCL params**: OS=23, stop=0.50, T1=1.00 (WF validated)
- **Learning loop**: Wired — nightly consolidator at 04:00 ET, trade classifier on close
- **Experiment loop**: `engine/strategies/experiment_log.py`, `run_experiment.py`, `search_strategy.py` all committed
- **MES experiments**: 10 run, all WFE=0.0 at 1h. Report at `docs/reports/sprint17_mes_experiment_round1.md`

### Dashboard (port 3010)
- **Build**: 26/26 routes, 0 TypeScript errors
- **Experiment status**: `GET /experiments/mes/status` endpoint live

### Paper Trading
- **Real live trades**: 11 in `portfolio/trades.jsonl` → 9 in SQLite
- **Validation gate progress**: ~11/60 trades, Day 1-2 of 30
- **Signal frequency**: UNVERIFIED — must check after engine restart

### Validated Instruments
| Symbol | TF | WFE | Status |
|--------|----|-----|--------|
| MCL | 1h | 0.82 | APPROVED — paper active, WF params (OS=23) |
| MNQ | 1h | 0.57 | APPROVED — paper active |
| MGC | 1d | 0.14 | HALTED |
| MES | 1h | 0.09 | DO NOT TRADE — 1h STC WFE=0.0, need 4h/15m data (Polygon key rotation required) |

---

## IMMEDIATE ACTIONS REQUIRED (Matt — before Sprint 18)

1. **`.\restart_engine.ps1`** — activates all Sprint 16+17 changes
2. **Set `IB_ACCOUNT_ID`** in `engine/.env` (replace `YOUR_IBKR_ACCOUNT_ID`) if not done
3. **Rotate Polygon API key** — current key cannot fetch sufficient MES historical data. Go to polygon.io, generate a new key, update `engine/.env` POLYGON_API_KEY.
4. **Run smoke test**: `cd engine && .venv\Scripts\python ..\scripts\smoke_test_approvals.py`
5. **Run signal frequency check** (48h after restart):
```powershell
cd C:\Users\mattm\ThinkorSwim\jarvis-trader\engine
.venv\Scripts\python -c "
import sqlite3
conn = sqlite3.connect('data/jarvis_trader.db')
cur = conn.cursor()
cur.execute(\"SELECT symbol, COUNT(*) as signals, DATE(created_at) as day FROM trade_signals GROUP BY symbol, day ORDER BY day DESC LIMIT 20\")
for row in cur.fetchall(): print(row)
"
```

---

## SPRINT 18 — SHAPE AND PRIORITIES

Sprint 18 prd.json is written at `C:\Users\mattm\ThinkorSwim\jarvis-trader\prd.json`.

| Story | Title | Priority |
|-------|-------|----------|
| US-1801 | Rotate Polygon key + fetch MES 4h/15m historical data | 1 |
| US-1802 | MES experiments 11-30 on 4h timeframe | 2 |
| US-1803 | Signal frequency audit + validation gate status report | 3 |
| US-1804 | RL training baseline — 100 PPO episodes on MES | 4 |
| US-1805 | MCL/MNQ parallel scan confirmation + trade count projection | 5 |

---

## SPRINT 18 CLAUDE CODE PROMPT

Paste this into a fresh Cursor Claude Code terminal:

> "Read `prd.json` at the project root and run `/ralph` to execute Sprint 18.
>
> **Critical context**: Sprint 17 complete (1,212 tests passing). Two key findings shape Sprint 18:
> 1. MES WFE=0.0 across all 10 experiments at 1h — the Polygon API key needs rotation to fetch 4h/15m MES data. Without fresh data, MES experiments are meaningless. US-1801 must rotate the key and fetch data before US-1802 runs experiments.
> 2. Only 11 real paper trades exist in portfolio/trades.jsonl (not 416 — that was a miscount from backtest files). The 60-trade validation gate is at ~11/60. Signal frequency after the US-1601 pre-filter fix is the most important metric to verify.
>
> Work stories in priority order: US-1801 → 1802 → 1803 → 1804 → 1805. Each story must pass `cd engine && .venv/Scripts/python -m pytest tests/ -v` with 0 failures before the next begins. Deploy and maintain 5 parallel agents throughout."

---

## FULL TODO LIST (updated post-Sprint 17)

| Priority | Item | Status | Sprint |
|----------|------|--------|--------|
| P0 | Restart engine (activate S16+S17 changes) | Matt action | Immediate |
| P0 | Rotate Polygon API key | Matt action | Immediate |
| P0 | Rotate Polygon key + fetch MES 4h/15m data | NOT STARTED | S18 US-1801 |
| P0 | MES experiments 11-30 on 4h timeframe | NOT STARTED | S18 US-1802 |
| P1 | Signal frequency audit + validation gate status | NOT STARTED | S18 US-1803 |
| P1 | RL training baseline — 100 PPO episodes MES | NOT STARTED | S18 US-1804 |
| P1 | MCL/MNQ parallel scan confirmation | NOT STARTED | S18 US-1805 |
| P2 | Signal frequency check (48h after restart) | Matt action | Post-restart |
| P2 | MES experiments 21-30 (if 4h WFE promising) | NOT STARTED | S18-S19 |
| P3 | MES paper validation protocol (if WFE gate passes) | NOT STARTED | S19 |
| P3 | Sprint 19 prd.json authoring | NOT STARTED | After S18 complete |

---

## KEY DECISIONS (standing)

- **MES**: DO NOT TRADE until WFE ≥ 0.50. 1h STC exhausted (WFE=0.0). Next: 4h timeframe with fresh Polygon data.
- **Workflow**: Cowork = strategy/planning/PRD. Claude Code in Cursor = all coding/testing/git.
- **5-agent protocol**: Always maintain 5 parallel agents in Cursor. Saved to MEMORY.md.
- **DB canonical path**: `engine/data/jarvis_trader.db` via `SQLITE_DB_PATH` in `config.py`.
- **SQLite is canonical**: JSON write path removed in US-1703. All new trades write to SQLite only.
- **INSTRUMENT_MULTIPLIERS**: MCL=100, MNQ=2, MES=5, MGC=10. Defined in `config.py`.
- **Validation gate clock**: Started 2026-04-02. Target 60 trades by 2026-05-02. Currently ~11/60.

---

## SAFETY RULES (never override)
- `LIVE_TRADING_ENABLED = False` — paper mode only
- `REQUIRE_HUMAN_APPROVAL = True` — never disable
- Kill switch: -2% daily P&L OR -10% drawdown
- Port 4001 (IB live) permanently blocked during paper phase
- Safety layer is hardcoded Python — never LLM

---

*Handoff updated: 2026-04-03 post-Sprint 17 completion*
*Next action: Matt rotates Polygon key + restarts engine, then Sprint 18 prompt into fresh Cursor session*
