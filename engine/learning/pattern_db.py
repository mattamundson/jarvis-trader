"""
Trading patterns SQLite table definition.

Used by TradingMemoryConsolidator to persist extracted trading patterns.
Import TRADING_PATTERNS_DDL and run it via the migration system.
"""

TRADING_PATTERNS_DDL = """
CREATE TABLE IF NOT EXISTS trading_patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL,
    conditions TEXT NOT NULL,
    frequency INTEGER DEFAULT 0,
    win_rate REAL DEFAULT 0.0,
    avg_return REAL DEFAULT 0.0,
    last_seen TEXT,
    first_seen TEXT,
    is_active INTEGER DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_patterns_active ON trading_patterns(is_active, last_seen);
"""
