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


def migration_008(conn: sqlite3.Connection) -> None:
    """
    008 — Pending human trade approvals.

    Rows are created when the pipeline proposes buy/sell with requires_human=True.
    Approve/reject updates status and records audit fields.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pending_trade_approvals (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            approval_id             TEXT    NOT NULL UNIQUE,
            symbol                  TEXT    NOT NULL,
            action                  TEXT    NOT NULL,
            quantity                REAL    NOT NULL,
            entry_price             REAL,
            status                  TEXT    NOT NULL DEFAULT 'pending',
            pipeline_snapshot_json  TEXT    NOT NULL,
            created_at              TEXT    NOT NULL DEFAULT (datetime('now')),
            resolved_at             TEXT,
            resolved_by             TEXT,
            rejection_reason        TEXT,
            paper_trade_id          TEXT,
            ib_order_id             TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_pta_status_created "
        "ON pending_trade_approvals(status, created_at DESC)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pta_symbol ON pending_trade_approvals(symbol)")
    conn.commit()
    logger.info("Migration 008 applied — pending_trade_approvals table created.")


def migration_009(conn: sqlite3.Connection) -> None:
    """
    009 — LLM cost tracking per pipeline run.

    Tracks token usage (input/output) and estimated costs for each LLM call
    within a pipeline execution, allowing cost monitoring and optimization.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pipeline_llm_costs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id          TEXT    NOT NULL,
            symbol          TEXT    NOT NULL,
            stage           TEXT    NOT NULL,
            model           TEXT    NOT NULL,
            input_tokens    INTEGER NOT NULL DEFAULT 0,
            output_tokens   INTEGER NOT NULL DEFAULT 0,
            estimated_cost_usd REAL NOT NULL DEFAULT 0.0,
            created_at      TEXT    NOT NULL DEFAULT (datetime('now', 'utc'))
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_llm_costs_run_id ON pipeline_llm_costs(run_id)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_llm_costs_created_at ON pipeline_llm_costs(created_at)"
    )
    conn.commit()
    logger.info("Migration 009 applied — pipeline_llm_costs table created.")


def migration_010(conn: sqlite3.Connection) -> None:
    """
    010 — Paper trades signal provenance columns.

    Adds columns to paper_trades to store full signal provenance for every trade:
      regime          — Market regime at entry (TEXT, nullable)
      structure_position — Structural position (BUYER_CONTROL, SELLER_CONTROL, etc., TEXT, nullable)
      bias            — Directional bias from signals (TEXT, nullable)
      composite_score — Cohen composite score (REAL, nullable)
      stc_contrib     — STC oscillator signal fired (INTEGER 0/1, nullable)
      orb_contrib     — ORB signal fired (INTEGER 0/1, nullable)
      vwap_contrib    — VWAP signal fired (INTEGER 0/1, nullable)

    All nullable for backward compatibility with existing trades.
    """
    conn.execute(
        """
        ALTER TABLE paper_trades ADD COLUMN regime TEXT
        """
    )
    conn.execute(
        """
        ALTER TABLE paper_trades ADD COLUMN structure_position TEXT
        """
    )
    conn.execute(
        """
        ALTER TABLE paper_trades ADD COLUMN bias TEXT
        """
    )
    conn.execute(
        """
        ALTER TABLE paper_trades ADD COLUMN composite_score REAL
        """
    )
    conn.execute(
        """
        ALTER TABLE paper_trades ADD COLUMN stc_contrib INTEGER
        """
    )
    conn.execute(
        """
        ALTER TABLE paper_trades ADD COLUMN orb_contrib INTEGER
        """
    )
    conn.execute(
        """
        ALTER TABLE paper_trades ADD COLUMN vwap_contrib INTEGER
        """
    )
    conn.commit()
    logger.info("Migration 010 applied — paper_trades signal provenance columns added.")


def migration_011(conn: sqlite3.Connection) -> None:
    """
    011 — Layer 5 conviction-aware position sizing.

    Adds 'risk_pct_used' column to paper_trades table to track the actual
    risk percentage used for each trade, computed from signal conviction
    (bias, regime, structure_position alignment). Nullable for backward
    compatibility with existing rows.
    """
    conn.execute(
        """
        ALTER TABLE paper_trades ADD COLUMN risk_pct_used REAL
        """
    )
    conn.commit()
    logger.info("Migration 011 applied — risk_pct_used column added to paper_trades.")


def migration_012(conn: sqlite3.Connection) -> None:
    """
    012 — Trade journal attribution columns.

    Adds attribution columns to trade_journal table to track which pipeline stage
    drove each decision and what confidence/scores were involved:
      regime_tier      — Market regime tier at decision (INTEGER, nullable)
      deciding_stage   — Pipeline stage that drove decision (TEXT, e.g. 'technical', 'debate', 'news')
      bull_score       — Bull researcher score (REAL, nullable)
      bear_score       — Bear researcher score (REAL, nullable)
      debate_confidence — Confidence from debate stage (REAL, nullable)

    All nullable for backward compatibility with existing journal entries.
    """
    conn.execute(
        """
        ALTER TABLE trade_journal ADD COLUMN regime_tier INTEGER
        """
    )
    conn.execute(
        """
        ALTER TABLE trade_journal ADD COLUMN deciding_stage TEXT
        """
    )
    conn.execute(
        """
        ALTER TABLE trade_journal ADD COLUMN bull_score REAL
        """
    )
    conn.execute(
        """
        ALTER TABLE trade_journal ADD COLUMN bear_score REAL
        """
    )
    conn.execute(
        """
        ALTER TABLE trade_journal ADD COLUMN debate_confidence REAL
        """
    )
    conn.commit()
    logger.info("Migration 012 applied — attribution columns added to trade_journal.")


def migration_013(conn: sqlite3.Connection) -> None:
    """
    013 — Learning events and trading patterns tables.

    Adds two tables for the trading memory consolidation system:

    learning_events  — individual learning events from each trade execution
    trading_patterns — aggregated patterns extracted nightly from trade history
    """
    # ── learning_events ───────────────────────────────────────────────────────
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS learning_events (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id        TEXT,                              -- soft FK → paper_trades.trade_id
            event_type      TEXT    NOT NULL,                  -- entry | exit | stop_hit | profit_target
            symbol          TEXT    NOT NULL,
            regime_tier     INTEGER,                           -- market regime at event (nullable)
            signal_strength REAL,                              -- confidence of signal (0.0–1.0, nullable)
            outcome         TEXT,                              -- win | loss | neutral (nullable)
            pnl_usd         REAL,                              -- P&L realized from event (nullable)
            created_at      TEXT    NOT NULL DEFAULT (datetime('now', 'utc'))
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_le_trade_id ON learning_events(trade_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_le_symbol ON learning_events(symbol)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_le_event_type ON learning_events(event_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_le_created_at ON learning_events(created_at)")

    # ── trading_patterns ──────────────────────────────────────────────────────
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trading_patterns (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern_hash    TEXT    NOT NULL UNIQUE,           -- hash of pattern conditions
            symbol          TEXT    NOT NULL,
            regime_tier     INTEGER,                           -- market regime context (nullable)
            conditions      TEXT    NOT NULL,                  -- JSON: pattern definition
            win_rate        REAL    NOT NULL DEFAULT 0.0,      -- 0.0–1.0
            sample_count    INTEGER NOT NULL DEFAULT 0,        -- number of times pattern occurred
            last_seen       TEXT,                              -- ISO-8601 UTC timestamp
            created_at      TEXT    NOT NULL DEFAULT (datetime('now', 'utc'))
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tp_pattern_hash ON trading_patterns(pattern_hash)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tp_symbol ON trading_patterns(symbol)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tp_regime_tier ON trading_patterns(regime_tier)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tp_last_seen ON trading_patterns(last_seen)")

    conn.commit()
    logger.info("Migration 013 applied — learning_events and trading_patterns tables created.")


def migration_014(conn: sqlite3.Connection) -> None:
    """
    014 — Signal timeframe attribution columns.

    Adds 'timeframe' TEXT column to both pending_trade_approvals and trade_journal
    tables to track whether signals came from 1h or 15m timeframes. Nullable for
    backward compatibility with existing rows. Enables post-validation attribution:
    did 1h or 15m signals perform better?
    """
    conn.execute(
        """
        ALTER TABLE pending_trade_approvals ADD COLUMN timeframe TEXT
        """
    )
    conn.execute(
        """
        ALTER TABLE trade_journal ADD COLUMN timeframe TEXT
        """
    )
    conn.commit()
    logger.info(
        "Migration 014 applied — timeframe columns added to pending_trade_approvals and trade_journal."
    )


def migration_015(conn: sqlite3.Connection) -> None:
    """
    015 — Pipeline runs confidence monitoring.

    Adds columns to pipeline_runs table for tracking confidence/hold statistics:
      confidence      — Average pipeline confidence (0-1, REAL, nullable)
      final_decision  — Final decision made ('hold', 'buy', 'sell', 'pending', TEXT, nullable)

    These fields enable high-hold-rate detection for pipeline regression monitoring.
    All nullable for backward compatibility with existing runs.
    """
    conn.execute(
        """
        ALTER TABLE pipeline_runs ADD COLUMN confidence REAL
        """
    )
    conn.execute(
        """
        ALTER TABLE pipeline_runs ADD COLUMN final_decision TEXT
        """
    )
    conn.commit()
    logger.info("Migration 015 applied — confidence columns added to pipeline_runs.")


def migration_016(conn: sqlite3.Connection) -> None:
    """
    016 — WFE snapshots table + divergence flag column.

    Creates the wfe_snapshots table (if not exists) for tracking weekly walk-forward
    efficiency metrics per symbol. Also adds the divergence_flag TEXT column for
    flagging when live paper performance diverges from WFE baseline projections.
    """
    # Create the table first (idempotent)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS wfe_snapshots (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol          TEXT    NOT NULL,
            week_start      TEXT    NOT NULL,
            trades          INTEGER NOT NULL DEFAULT 0,
            win_rate        REAL,
            profit_factor   REAL,
            sharpe          REAL,
            max_dd          REAL,
            created_at      TEXT    NOT NULL DEFAULT (datetime('now', 'utc'))
        )
        """
    )
    conn.commit()
    logger.info("Migration 016 — wfe_snapshots table ensured.")

    # Add divergence_flag column (idempotent)
    try:
        conn.execute(
            """
            ALTER TABLE wfe_snapshots ADD COLUMN divergence_flag TEXT
            """
        )
        conn.commit()
        logger.info("Migration 016 applied — divergence_flag column added to wfe_snapshots.")
    except sqlite3.OperationalError:
        # Column already exists — idempotent
        logger.debug("Migration 016 skipped — divergence_flag already exists in wfe_snapshots.")


def migration_017(conn: sqlite3.Connection) -> None:
    """
    017 — System state persistence table.

    Adds the system_state key/value table for persisting engine state across
    restarts.  Initially used to persist kill switch activation so the safety
    layer re-arms automatically on restart without human re-intervention.

    Columns
    -------
    key        — state key (e.g. 'kill_switch_active', 'kill_switch_reason')
    value      — TEXT value (JSON-serialisable)
    updated_at — ISO-8601 UTC timestamp of last write
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS system_state (
            key        TEXT PRIMARY KEY,
            value      TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now', 'utc'))
        )
        """
    )
    conn.commit()
    logger.info("Migration 017 applied — system_state table created.")


def migration_018(conn: sqlite3.Connection) -> None:
    """
    018 — P&L snapshots table for safety layer state persistence.

    Stores daily P&L state so the safety layer can restore its position
    after an engine restart mid-session without resetting drawdown to 0.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pnl_snapshots (
            date             TEXT    NOT NULL,
            daily_pnl        REAL    NOT NULL DEFAULT 0.0,
            portfolio_equity REAL    NOT NULL DEFAULT 0.0,
            peak_equity      REAL    NOT NULL DEFAULT 0.0,
            consecutive_losses INTEGER NOT NULL DEFAULT 0,
            updated_at       TEXT    NOT NULL DEFAULT (datetime('now', 'utc')),
            PRIMARY KEY (date)
        )
        """
    )
    conn.commit()
    logger.info("Migration 018 applied — pnl_snapshots table created.")


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
    migration_008,  # version 8
    migration_009,  # version 9
    migration_010,  # version 10
    migration_011,  # version 11
    migration_012,  # version 12
    migration_013,  # version 13
    migration_014,  # version 14
    migration_015,  # version 15
    migration_016,  # version 16
    migration_017,  # version 17
    migration_018,  # version 18
]

MIGRATION_DESCRIPTIONS: List[str] = [
    "Initial schema: paper_trades, decisions, daily_pnl, positions, settings",
    "Trade journal: trade_journal table with notes, tags, mood, lesson",
    "Pipeline runs: pipeline_runs table for webhook/manual run history",
    "Journal notes: journal_notes table with note_type, title, body, tags (JSON array)",
    "Alert log: alert_log table for WhatsApp notification history",
    "Discord signals: discord_bot_signals, discord_ib_reports, discord_corey_alerts, discord_corey_commentary",
    "Capital allocation: capital_allocation table for $10K cross-market distribution",
    "Pending trade approvals: pending_trade_approvals for human-gated paper/live execution",
    "LLM cost tracking: pipeline_llm_costs table for token usage and estimated costs",
    "Paper trades signal provenance: regime, structure, bias, composite_score, signal contributions",
    "Layer 5 conviction-aware sizing: risk_pct_used column for position sizing by conviction",
    "Trade journal attribution: regime_tier, deciding_stage, bull_score, bear_score, debate_confidence",
    "Learning events and trading patterns: learning_events and trading_patterns tables for memory consolidation",
    "Signal timeframe attribution: timeframe column for pending_trade_approvals and trade_journal (1h/15m)",
    "Pipeline confidence monitoring: confidence and final_decision columns for hold-rate detection",
    "WFE divergence flag: divergence_flag column for wfe_snapshots table to track performance divergence",
    "System state persistence: system_state key/value table for kill switch and engine state across restarts",
    "P&L snapshots: pnl_snapshots table for safety layer daily P&L persistence across engine restarts",
]


# ── Public entry point ────────────────────────────────────────────────────────


def run_migrations(conn: sqlite3.Connection) -> None:
    """
    Run all pending migrations in order.

    Idempotent — safe to call multiple times. Only applies migrations
    that haven't been applied yet (as tracked by schema_version table).
    """
    _ensure_version_table(conn)
    current_version = _get_current_version(conn)

    for index, migration_func in enumerate(MIGRATIONS):
        version = index + 1
        if version > current_version:
            migration_func(conn)
            _record_version(conn, version, MIGRATION_DESCRIPTIONS[index])
            logger.info(f"Applied migration {version}: {MIGRATION_DESCRIPTIONS[index]}")
        else:
            logger.debug(f"Skipped migration {version} (already applied)")

    logger.info(f"Migrations complete. Current schema version: {_get_current_version(conn)}")
