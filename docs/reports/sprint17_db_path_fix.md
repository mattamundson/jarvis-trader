# Sprint 17 — DB Path Fix Report

**Date**: 2026-04-03
**Story**: US-1701

## Canonical DB Path
`engine/data/jarvis_trader.db` (438 KB, 18 tables)

## Integrity Check
```
('ok',)
Tables: ['alert_log', 'capital_allocation', 'daily_pnl', 'decisions', 'discord_bot_signals',
         'discord_corey_alerts', 'discord_corey_commentary', 'discord_ib_reports', 'journal_notes',
         'paper_trades', 'pending_trade_approvals', 'pipeline_llm_costs', 'pipeline_runs',
         'positions', 'schema_version', 'settings', 'sqlite_sequence', 'trade_journal']
```
PRAGMA integrity_check: `ok`

## Changes Made
- Added `SQLITE_DB_PATH` constant to `engine/config.py` TradingConfig (Infrastructure section)
- Deleted 0-byte ghost file at `engine/jarvis_trader.db`
- No production code path corrections needed — all files already used `data/jarvis_trader.db`

## Files With Hardcoded DB References (correct paths — no change needed)
- `engine/database/manager.py` — uses `data/jarvis_trader.db`
- `engine/main.py` — uses `data/jarvis_trader.db`
- `engine/routers/discord_router.py` — uses `data/jarvis_trader.db`
- `engine/init_db.py` — uses `data/jarvis_trader.db`
- `engine/paper/` modules — use `data/jarvis_trader.db`

## Ghost File
`engine/jarvis_trader.db` was 0 bytes, created 2026-04-02. Deleted.

## Test Suite
1209 passed, 94 skipped (RL live-engine + IBKR/Polygon offline), 0 failures.

## Config Change
```python
# engine/config.py — TradingConfig — new Infrastructure section

# -- Infrastructure --------------------------------------------------------
SQLITE_DB_PATH: str = Field(
    "data/jarvis_trader.db",
    description="Canonical SQLite database path (relative to engine root)",
)
```

## US-1702: NULL pnl Fix

### Root Cause
`close_trade()` in `portfolio/tracker.py` computed pnl without contract multipliers,
meaning all stored pnl values were raw point differences instead of real dollar values.
The 6 seed trades in the DB had `pnl=NULL` and `exit_price=NULL` — they were inserted
directly as `status='closed'` without going through the close path at all.

### Fix
Added `INSTRUMENT_MULTIPLIERS` dict to `portfolio/tracker.py` and applied it in both
`close_trade()` and `close_paper_trade()` before the DB UPDATE call.

Multipliers applied:
- MCL = 100.0 (micro crude oil, 100 barrels per contract)
- MNQ = 2.0 (micro Nasdaq, $2/point)
- MES = 5.0 (micro E-mini S&P 500, $5/point)
- MGC = 10.0 (micro gold, 10 troy oz per contract)
- ES = 50.0, NQ = 20.0, CL = 1000.0, GC = 100.0

### Backfill
Ran `scripts/backfill_pnl.py` — updated 0 trades (all 6 existing closed trades have
`exit_price=NULL` as they are synthetic seed data with no exit; the backfill targets
`exit_price IS NOT NULL AND pnl IS NULL` which correctly finds no rows to update).

### Test Updates
Updated 4 assertions in `tests/test_integration.py::TestTrackerSQLiteIntegration`
to reflect multiplier-correct expected values:
- MES long 1 contract: 50 pts → $250 (×5)
- MNQ long 2 contracts: 100 pts → $400 (×2 qty × $2)
- MES long 3 contracts: 10 pts → $150 (×3 qty × $5)
- MES short 2 contracts: 20 pts → $200 (×2 qty × $5)
