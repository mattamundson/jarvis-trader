"""
JARVIS TRADER — SQLite Migrations
===================================
Tracks schema version in a `schema_version` table and applies migrations
in order.  Each migration is a plain function that receives an open
sqlite3.Connection; it should be idempotent (use IF NOT EXISTS, etc.).

Adding a new migration
----------------------
1. Write a function  migration_NNN(conn)  below.
2. Add it to the MIGRATIONS list at the bottom of this file.
3. The next time `run_migrations(conn)` is called the new migration runs
   automatically.  The version number is the 1-based index of the entry
   in MIGRATIONS.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Callable, List

logger = logging.getLogger("jarvis_trader.database.migrations")


# ── Version bookkeeping ────────────────────────────────────────────────────────


def _ensure_version_table(conn: sqlite3.Connection) -> None:
    """Create the schema_version table if it does not already exist."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version     INTEGER NOT NULL,
            applied_at  TEXT    NOT NULL DEFAULT (datetime('now', 'utc')),
            description TEXT
        )
        """
    )
    conn.commit()


def _get_current_version(conn: sqlite3.Connection) -> int:
    """Return the highest applied migration version, or 0 if none yet."""
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return row[0] if (row and row[0] is not None) else 0


def _record_version(conn: sqlite3.Connection, version: int, description: str) -> None:
    """Insert a row marking migration `version` as successfully applied."""
    conn.execute(
        "INSERT INTO schema_version (version, description) VALUES (?, ?)",
        (version, description),
    )
    conn.commit()


# ── Individual migrations ──────────────────────────────────────────────────────


def migration_001(conn: sqlite3.Connection) -> None:
    """
    001 — Initial schema.

    Creates all five core tables:
      paper_trades  — full lifecycle of every simulated trade
      decisions     — pipeline decision log with agent reasoning
      daily_pnl     — end-of-day P&L snapshots
      positions     — current open positions (live mirror of open trades)
      settings      — key/value config store
    """

    # ── paper_trades ──────────────────────────────────────────────────────────
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS paper_trades (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id        TEXT    NOT NULL UNIQUE,   -- UUID from PortfolioTracker
            symbol          TEXT    NOT NULL,
            side            TEXT    NOT NULL,          -- buy | sell | buy_to_open | sell_to_open
            quantity        REAL    NOT NULL,
            entry_price     REAL    NOT NULL,
            exit_price      REAL,                      -- NULL while trade is open
            entry_time      TEXT    NOT NULL,          -- ISO-8601 UTC
            exit_time       TEXT,                      -- ISO-8601 UTC, NULL while open
            pnl             REAL,                      -- NULL while open
            status          TEXT    NOT NULL DEFAULT 'open',  -- open | closed | cancelled
            strategy_params TEXT,                      -- JSON blob: strategy-specific params
            notes           TEXT    DEFAULT ''
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pt_symbol     ON paper_trades(symbol)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pt_status     ON paper_trades(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pt_entry_time ON paper_trades(entry_time)")

    # ── decisions ─────────────────────────────────────────────────────────────
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS decisions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol          TEXT    NOT NULL,
            timestamp       TEXT    NOT NULL,          -- ISO-8601 UTC
            action          TEXT    NOT NULL,          -- buy | sell | hold | exit_long | exit_short
            confidence      REAL,                      -- 0.0 – 1.0
            regime          TEXT,                      -- market regime label at decision time
            signal_data_json TEXT,                     -- JSON: raw indicator values / scores
            reasoning       TEXT                       -- full LLM reasoning text
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dec_symbol    ON decisions(symbol)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dec_timestamp ON decisions(timestamp)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dec_action    ON decisions(action)")

    # ── daily_pnl ─────────────────────────────────────────────────────────────
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS daily_pnl (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            date                TEXT    NOT NULL UNIQUE,  -- YYYY-MM-DD
            starting_balance    REAL    NOT NULL DEFAULT 0.0,
            ending_balance      REAL    NOT NULL DEFAULT 0.0,
            realized_pnl        REAL    NOT NULL DEFAULT 0.0,
            unrealized_pnl      REAL    NOT NULL DEFAULT 0.0,
            total_trades        INTEGER NOT NULL DEFAULT 0,
            winning_trades      INTEGER NOT NULL DEFAULT 0,
            losing_trades       INTEGER NOT NULL DEFAULT 0,
            max_drawdown        REAL    NOT NULL DEFAULT 0.0   -- negative value or 0
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dpnl_date ON daily_pnl(date)")

    # ── positions ─────────────────────────────────────────────────────────────
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS positions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol          TEXT    NOT NULL UNIQUE,   -- one row per symbol
            quantity        REAL    NOT NULL,
            entry_price     REAL    NOT NULL,
            entry_time      TEXT    NOT NULL,          -- ISO-8601 UTC
            current_price   REAL,                      -- last known market price
            unrealized_pnl  REAL,                      -- (current_price - entry_price) * qty
            stop_loss       REAL,                      -- NULL if not set
            take_profit     REAL                       -- NULL if not set
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pos_symbol ON positions(symbol)")

    # ── settings ──────────────────────────────────────────────────────────────
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key         TEXT PRIMARY KEY,
            value       TEXT,
            updated_at  TEXT NOT NULL DEFAULT (datetime('now', 'utc'))
        )
        """
    )

    conn.commit()
    logger.info("Migration 001 applied — initial schema created.")


def migration_002(conn: sqlite3.Connection) -> None:
    """
    002 — Trade journal table.

    Adds the trade_journal table for annotating individual trades with
    free-text notes, comma-separated tags, a mood label, and a lesson field.
    The trade_id column is a soft foreign key to paper_trades.trade_id
    (not enforced by SQLite FK constraint so entries survive trade deletion).
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trade_journal (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id    TEXT    NOT NULL,               -- soft FK → paper_trades.trade_id
            timestamp   TEXT    NOT NULL,               -- ISO-8601 UTC
            note        TEXT    NOT NULL DEFAULT '',    -- journal entry body
            tags        TEXT,                           -- comma-separated (e.g. "missed_entry,good_setup")
            mood        TEXT,                           -- confident | uncertain | frustrated | neutral
            lesson      TEXT                            -- what was learned from this trade
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tj_trade_id  ON trade_journal(trade_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tj_timestamp ON trade_journal(timestamp)")
    conn.commit()
    logger.info("Migration 002 applied — trade_journal table created.")


def migration_003(conn: sqlite3.Connection) -> None:
    """
    003 — Pipeline runs history table.

    Adds the pipeline_runs table for persisting every TradingPipeline
    execution triggered by a TradingView webhook or manual call.
    Each row captures the symbol, webhook action, final decision,
    status, duration, and a human-readable summary line.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pipeline_runs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id          TEXT    UNIQUE NOT NULL,          -- 8-char UUID prefix
            symbol          TEXT    NOT NULL,
            webhook_action  TEXT,                             -- LONG | SHORT | CLOSE | NULL (manual)
            source          TEXT    NOT NULL DEFAULT 'tradingview',
            final_action    TEXT,                             -- buy | sell | hold | pending_human_approval
            final_quantity  INTEGER,
            requires_human  BOOLEAN NOT NULL DEFAULT 0,
            summary         TEXT,                             -- human-readable one-liner
            status          TEXT    NOT NULL,                 -- completed | error | skipped
            error_message   TEXT,                             -- populated on status=error
            duration_ms     REAL,                             -- wall-clock ms for the full run
            created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pr_symbol     ON pipeline_runs(symbol)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pr_created_at ON pipeline_runs(created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pr_status     ON pipeline_runs(status)")
    conn.commit()
    logger.info("Migration 003 applied — pipeline_runs table created.")


def migration_004(conn: sqlite3.Connection) -> None:
    """
    004 — Journal notes table.

    Adds the journal_notes table for free-form trade observations, lessons,
    and alerts that are not necessarily tied to a specific trade.  Unlike
    trade_journal (migration 002), notes have a note_type enum, a title
    field, and store tags as a JSON array.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS journal_notes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id    TEXT,                                    -- optional soft FK → paper_trades.trade_id
            note_type   TEXT NOT NULL DEFAULT 'observation',    -- observation | lesson | alert
            title       TEXT NOT NULL,
            body        TEXT,
            tags        TEXT DEFAULT '[]',                      -- JSON array of tag strings
            created_at  TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
            updated_at  TEXT NOT NULL DEFAULT (datetime('now', 'utc'))
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_journal_notes_created ON journal_notes(created_at DESC)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_journal_notes_trade ON journal_notes(trade_id)")
    conn.commit()
    logger.info("Migration 004 applied — journal_notes table created.")


def migration_005(conn: sqlite3.Connection) -> None:
    """
    005 — Alert log table.

    Adds the alert_log table for persisting every WhatsApp (or other channel)
    notification that JARVIS sends.  This enables Matt to review a complete
    history of every alert during the paper trading phase without relying on
    the WhatsApp conversation history.

    Columns
    -------
    alert_type  — e.g. 'trade_opened', 'trade_closed', 'morning_briefing',
                  'vix_alert', 'circuit_breaker', 'notification'
    symbol      — optional ticker (NULL for non-trade alerts)
    message     — the actual message content that was sent
    channel     — delivery channel, default 'whatsapp'
    status      — 'sent' | 'failed' | 'suppressed'
    error       — error text when status='failed', NULL otherwise
    created_at  — ISO-8601 UTC timestamp
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS alert_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_type  TEXT NOT NULL,
            symbol      TEXT,
            message     TEXT NOT NULL,
            channel     TEXT NOT NULL DEFAULT 'whatsapp',
            status      TEXT NOT NULL DEFAULT 'sent',
            error       TEXT,
            created_at  TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_alert_log_created_at ON alert_log(created_at DESC)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_alert_log_type ON alert_log(alert_type)")
    conn.commit()
    logger.info("Migration 005 applied — alert_log table created.")


def migration_006(conn: sqlite3.Connection) -> None:
    """
    006 — Discord signal tables.

    Adds four tables for persisting parsed Discord messages from the JARVIS
    trading Discord server:

      discord_bot_signals      — parsed signals from proton-bot-alerts and
                                  instrument channels (es, nq, gc, cl, ym, rty,
                                  eurusd, btc, spy).  Captures direction, entry,
                                  targets, stops, win-rate, MFE/MAE, R:R, etc.
      discord_ib_reports       — Initial Balance reports from indicator-alerts
                                  channel (IB OHLC, extensions ibu/ibd, auction
                                  context, trade plan).
      discord_corey_alerts     — Manual trade alerts posted by Corey (tathedog)
                                  in the trade-alerts channel.
      discord_corey_commentary — Market commentary from Corey in market-updates
                                  or general channels.

    All tables use message_id as a UNIQUE key so re-importing the same Discord
    export is idempotent (INSERT OR IGNORE).
    """
    # ── discord_bot_signals ───────────────────────────────────────────────────
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS discord_bot_signals (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id      TEXT    UNIQUE NOT NULL,
            timestamp       TEXT    NOT NULL,          -- ISO-8601 UTC
            symbol          TEXT    NOT NULL,           -- e.g. ES, NQ, GC, CL
            timeframe       TEXT,                       -- e.g. "1 m", "15 m"
            direction       TEXT,                       -- LONG | SHORT
            signal_type     TEXT,                       -- ENTRY | EXIT
            entry_price     REAL,
            target1         REAL,
            target2         REAL,
            stop1           REAL,
            stop2           REAL,
            win_rate        REAL,
            wins            INTEGER,
            losses          INTEGER,
            mfe             REAL,
            mae             REAL,
            rr              REAL,
            gain            REAL,
            draw            REAL,
            net             REAL,
            last_price      REAL,
            raw_description TEXT,
            source_channel  TEXT,
            created_at      TEXT    NOT NULL DEFAULT (datetime('now', 'utc'))
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dbs_symbol    ON discord_bot_signals(symbol)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dbs_timestamp ON discord_bot_signals(timestamp)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dbs_direction ON discord_bot_signals(direction)")

    # ── discord_ib_reports ────────────────────────────────────────────────────
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS discord_ib_reports (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id      TEXT    UNIQUE NOT NULL,
            timestamp       TEXT    NOT NULL,          -- ISO-8601 UTC
            symbol          TEXT    NOT NULL,           -- e.g. ES, NQ
            timeframe       TEXT,
            ib_open         REAL,
            ib_high         REAL,
            ib_low          REAL,
            ib_close        REAL,
            ib_range        REAL,
            ibu50           REAL,
            ibu100          REAL,
            ibd50           REAL,
            ibd100          REAL,
            auction_context TEXT,
            trade_plan      TEXT,
            raw_content     TEXT,
            source_channel  TEXT    NOT NULL DEFAULT 'indicator-alerts',
            created_at      TEXT    NOT NULL DEFAULT (datetime('now', 'utc'))
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dir_symbol    ON discord_ib_reports(symbol)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dir_timestamp ON discord_ib_reports(timestamp)")

    # ── discord_corey_alerts ──────────────────────────────────────────────────
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS discord_corey_alerts (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id      TEXT    UNIQUE NOT NULL,
            timestamp       TEXT    NOT NULL,          -- ISO-8601 UTC
            content         TEXT    NOT NULL,
            symbol          TEXT,
            direction       TEXT,                       -- LONG | SHORT
            price           REAL,
            source_channel  TEXT    NOT NULL DEFAULT 'trade-alerts',
            created_at      TEXT    NOT NULL DEFAULT (datetime('now', 'utc'))
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dca_timestamp ON discord_corey_alerts(timestamp)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dca_symbol    ON discord_corey_alerts(symbol)")

    # ── discord_corey_commentary ──────────────────────────────────────────────
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS discord_corey_commentary (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id      TEXT    UNIQUE NOT NULL,
            timestamp       TEXT    NOT NULL,          -- ISO-8601 UTC
            content         TEXT    NOT NULL,
            channel         TEXT    NOT NULL,           -- market-updates | general
            author_id       TEXT    NOT NULL DEFAULT '564449478174703646',
            created_at      TEXT    NOT NULL DEFAULT (datetime('now', 'utc'))
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_dcc_timestamp ON discord_corey_commentary(timestamp)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_dcc_channel   ON discord_corey_commentary(channel)"
    )

    conn.commit()
    logger.info("Migration 006 applied — Discord signal tables created.")


def migration_007(conn: sqlite3.Connection) -> None:
    """
    007 — Capital allocation table.

    Tracks how the $10,000 total account capital is distributed across
    trading instruments/markets.  One row per symbol (e.g. MES, MNQ, MGC,
    MCL).  The script scripts/init_capital.py seeds the initial rows;
    subsequent writes use INSERT OR REPLACE so the table is always current.

    Columns
    -------
    symbol          — instrument ticker (e.g. MES, MNQ)
    market          — market module name (futures | options | crypto | polymarket)
    allocation      — USD amount allocated to this instrument
    allocation_pct  — fraction of total capital (0.0–1.0)
    total_capital   — total account capital at time of last update (USD)
    notes           — optional free-text notes
    updated_at      — ISO-8601 UTC timestamp of last upsert
    created_at      — ISO-8601 UTC timestamp when row was first inserted
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS capital_allocation (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol          TEXT    NOT NULL UNIQUE,
            market          TEXT    NOT NULL DEFAULT 'futures',
            allocation      REAL    NOT NULL DEFAULT 0.0,
            allocation_pct  REAL    NOT NULL DEFAULT 0.0,
            total_capital   REAL    NOT NULL DEFAULT 10000.0,
            notes           TEXT    DEFAULT '',
            updated_at      TEXT    NOT NULL DEFAULT (datetime('now', 'utc')),
            created_at      TEXT    NOT NULL DEFAULT (datetime('now', 'utc'))
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ca_market ON capital_allocation(market)")
    conn.commit()
    logger.info("Migration 007 applied — capital_allocation table created.")


# ── Migration registry ─────────────────────────────────────────────────────────
# Add new migrations here in order.  The list index + 1 = migration version.

MIGRATIONS: List[Callable[[sqlite3.Connection], None]] = [
    migration_001,  # version 1
    migration_002,  # version 2
    migration_003,  # version 3
    migration_004,  # version 4
    migration_005,  # version 5
    migration_006,  # version 6
    migration_007,  # version 7
]

MIGRATION_DESCRIPTIONS: List[str] = [
    "Initial schema: paper_trades, decisions, daily_pnl, positions, settings",
    "Trade journal: trade_journal table with notes, tags, mood, lesson",
    "Pipeline runs: pipeline_runs table for webhook/manual run history",
    "Journal notes: journal_notes table with note_type, title, body, tags (JSON array)",
    "Alert log: alert_log table for WhatsApp notification history",
    "Discord signals: discord_bot_signals, discord_ib_reports, discord_corey_alerts, discord_corey_commentary",
    "Capital allocation: capital_allocation table for $10K cross-market distribution",
]


# ── Public entry point ─────────────────────────────────────────────────────────


def run_migrations(conn: sqlite3.Connection) -> None:
    """
    Apply any pending migrations to `conn` in version order.

    This function is idempotent — calling it multiple times is safe.
    Each migration runs inside its own implicit transaction; the version
    record is written only after the migration function returns without
    raising.

    Parameters
    ----------
    conn:
        An open sqlite3.Connection to the target database.
        WAL mode should already be set by the caller for best concurrency.
    """
    _ensure_version_table(conn)
    current = _get_current_version(conn)
    total = len(MIGRATIONS)

    if current >= total:
        logger.debug(f"Database schema is up-to-date (version {current}/{total}).")
        return

    logger.info(f"Running migrations {current + 1}–{total} (currently at version {current})...")

    for idx, migrate_fn in enumerate(MIGRATIONS):
        version = idx + 1
        if version <= current:
            continue  # already applied
        description = MIGRATION_DESCRIPTIONS[idx]
        logger.info(f"  Applying migration {version:03d}: {description}")
        try:
            migrate_fn(conn)
            _record_version(conn, version, description)
            logger.info(f"  Migration {version:03d} applied successfully")
        except Exception as exc:
            logger.error(f"Migration {version:03d} failed: {exc}")
            raise
