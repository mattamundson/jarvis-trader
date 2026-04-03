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
