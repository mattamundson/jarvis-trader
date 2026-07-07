-- Migration: add account_id to paper_trades and pnl_snapshots
-- Applied via engine/database/migrations.py (migration_027)
-- This file is documentation only — the actual migration is in Python.
--
-- account_id='A' = production risk config (default, backwards-compatible)
-- account_id='B' = challenger risk config (populated when ENABLE_PARALLEL_PAPER=1)

-- Only runs if column does not yet exist (PRAGMA check in Python migration).
-- Equivalent SQL for reference:

SELECT COUNT(*) FROM pragma_table_info('paper_trades') WHERE name='account_id';
-- If 0: ALTER TABLE paper_trades ADD COLUMN account_id TEXT NOT NULL DEFAULT 'A';

SELECT COUNT(*) FROM pragma_table_info('pnl_snapshots') WHERE name='account_id';
-- If 0: ALTER TABLE pnl_snapshots ADD COLUMN account_id TEXT NOT NULL DEFAULT 'A';

CREATE INDEX IF NOT EXISTS idx_paper_trades_account ON paper_trades(account_id, exit_time);
CREATE INDEX IF NOT EXISTS idx_pnl_snapshots_account ON pnl_snapshots(account_id, date);
