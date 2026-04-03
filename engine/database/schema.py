"""
JARVIS TRADER -- schema.py (re-export shim)
=============================================
This module re-exports DatabaseManager, init_db, and get_db from the
refactored manager module for backwards compatibility.

All implementation now lives in:
  engine/database/manager.py           -- DatabaseManager class + singletons
  engine/database/_mixins_trades.py    -- paper_trades CRUD
  engine/database/_mixins_analytics.py -- stats/drawdown queries
  engine/database/_mixins_decisions.py -- decisions log CRUD
  engine/database/_mixins_pnl.py       -- daily_pnl CRUD
  engine/database/_mixins_positions.py -- positions CRUD
  engine/database/_mixins_settings.py  -- settings key/value CRUD
  engine/database/_mixins_journal.py   -- trade_journal + journal_notes CRUD
  engine/database/_mixins_alerts.py    -- alert_log + pipeline_runs CRUD
  engine/database/_helpers.py          -- shared utilities (_utcnow, _to_json, etc.)
"""

from .manager import DatabaseManager, get_db, init_db

__all__ = ["DatabaseManager", "init_db", "get_db"]
