# MES Sprint Gate — Design v1.0
**Date:** 2026-04-25  
**Author:** JARVIS TRADER / Matt Morrison  
**Sprint:** Q2 Apr 22–30 | Target: 1 live MES contract by Apr 30

---

## Context

Gate v2 (60 trades / 30 days) is the validation bar for MCL/MNQ. MES has a materially stronger backtest edge (PF 5.27, Sharpe 4.16, survived Liberation Day + tariff shocks). As of Apr 25, Gate v2 shows 7/60 trades and 14/30 days — physically impossible to pass by Apr 30. This design defines a lighter MES Sprint Gate justified by MES's backtested strength, while keeping Gate v2 unchanged for MCL/MNQ.

**Iteration 1 of many.** Thresholds and architecture will evolve with live data.

---

## MES Sprint Gate — Pass Criteria

| Check | Threshold | Source |
|-------|-----------|--------|
| Smoke test | `hb1_paper_smoke.py` 4/4 PASS | `engine/data/hb1_smoke_passed.json` |
| Paper trades (bracket path) | ≥ 5 with `ENABLE_BROKER_BRACKETS=True` | SQLite `paper_trades` |
| Kill-switch clean | 0 triggers across Mon/Tue/Wed RTH | Safety layer history |
| pm2 restarts | ≤ 5 in rolling 72h | pm2 sidecar file |
| Loss streak | < 3 consecutive | SQLite `paper_trades` |
| Drawdown | < 2% across paper sessions | Safety layer |

Gate v2 (60 trades / 30 days) remains **unchanged** for MCL/MNQ.

---

## Technical Architecture

### 1. Config (`engine/config.py`)
- `ENABLE_BROKER_BRACKETS: bool = True` — activates `submit_entry_with_stop()` in approval path

### 2. New Endpoint (`engine/routers/phase3_readiness_router.py`)
- `GET /system/mes-sprint-gate`
- Returns `{ "overall": "PASS"|"FAIL"|"PENDING", "checks": [...], "ready_for_live": bool }`
- Reads: SQLite paper trades, safety layer status, `hb1_smoke_passed.json`, pm2 sidecar

### 3. Smoke Test
- Script: `engine/scripts/hb1_paper_smoke.py` (already exists)
- On 4/4 PASS: writes `engine/data/hb1_smoke_passed.json`
- Run today (Apr 25) — IBKR already connected on port 4002

### 4. New Routers (commit-ready)
- `engine/routers/institutional_router.py` — volume profile + harmonic detection
- `engine/routers/super_engine_router.py` — ArbScout / RegimeGuard / ModelDrawer status
- Wire both into `main.py`, commit

### 5. Dashboard Widget
- `MESSprintGate` card polling `/system/mes-sprint-gate` every 60s
- Green/amber/red badge per check — visible during RTH sessions

---

## Day-by-Day Execution

| Day | Date | Focus | Deliverables |
|-----|------|-------|-------------|
| D3 | Sat Apr 25 | Infra + smoke | `ENABLE_BROKER_BRACKETS=True`, run smoke test (4/4 PASS), `/system/mes-sprint-gate` endpoint, commit new routers |
| D4 | Sun Apr 26 | Hardening | Dashboard widget, pm2 restart sidecar monitor, WhatsApp kill-switch alert E2E test |
| D5 | Mon Apr 27 | RTH session 1 | Pipeline at 9:35 CT, bracket trades logged, STP confirmed in TWS, gate check after close |
| D6 | Tue Apr 28 | RTH session 2 | Same cadence, accumulate trades, ≥2 clean sessions |
| D7 | Wed Apr 29 | RTH session 3 + prep | ≥5 trades, 3 clean sessions, `/system/mes-sprint-gate` → PASS, live-flip checklist ready |
| D8 | Thu Apr 30 | Go/No-Go → Live | Morning gate check → flip if green, 1 MES contract live at 9:35 CT |

---

## April 30 Go/No-Go Procedure

### Pre-RTH Checks (~8:00 CT)
1. `GET /system/mes-sprint-gate` → `"overall": "PASS"`
2. `GET /safety/status` → `kill_switch_active: false`
3. `GET /health` → `ibkr_connected: true`, `tradingview_mcp_healthy: true`
4. `pm2 status jarvis-engine` → ≤ 5 restarts in 72h
5. Confirm IBKR port switch: 4002 (paper) → 4001 (live)

### Live Flip Sequence (if all green)
```
1. LIVE_TRADING_ENABLED=True in .env
2. IBKR_PORT=4001 in .env
3. .\restart_engine.ps1
4. GET /health → live_trading: true
5. Pipeline runs at 9:35 CT
6. Monitor TWS for fill + STP child confirmation
```

### Hard Limits (Day 8, non-negotiable)
- Kill switch at -2% daily loss — no override
- Max 1 MES contract — no scaling on Day 1
- No trades outside RTH (9:35–15:30 CT)
- `REQUIRE_HUMAN_APPROVAL=True` stays on

### If Any Check Fails
- Do not flip. Extend 1 week. Reassess May 7.
- Document which check failed and why.

---

## What This Is Not
- Not a permanent gate architecture (iteration 1 of many)
- Not a replacement for Gate v2 on MCL/MNQ
- Not permission to scale beyond 1 contract on Day 1
