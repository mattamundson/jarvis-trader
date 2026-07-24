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

    learning_events  — GHOST TABLE. Has no writers anywhere in the codebase.
                       The per-trade feedback signal is actually written to
                       `trade_outcomes` by AgentFeedbackTracker.record_outcome()
                       (analytics/agent_feedback.py). learning_events is kept
                       in schema only for historical migration replay. Readers
                       should query `trade_outcomes` instead. Do not add a
                       writer here without deleting trade_outcomes first — you
                       will end up with two half-populated parallel tables.
    trading_patterns — aggregated patterns extracted nightly. Active: written
                       by learning/pattern_db.py and learning/patterns.py.
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


def migration_019(conn: sqlite3.Connection) -> None:
    """
    019 — Full pipeline JSON column on decisions table.

    Adds full_pipeline_json TEXT column so that the complete stage-by-stage
    pipeline result (analyst_reports, debate_result, trade_decision,
    risk_decision, fund_decision, confidence gate, etc.) is persisted
    alongside each decision row.  Existing rows get NULL for the new column.
    """
    conn.execute("ALTER TABLE decisions ADD COLUMN full_pipeline_json TEXT")
    conn.commit()
    logger.info("Migration 019 applied — full_pipeline_json column added to decisions.")


def migration_020(conn: sqlite3.Connection) -> None:
    """
    020 — Supervisor decisions table for Hermes-pattern supervisor agent.

    Records every ACK / REVIEW / ESCALATE / HOLD_FOR_INFO decision made by
    the in-process SupervisorAgent that gates openclaw_notifier outputs.
    Enables noise-reduction metrics (via /supervisor/stats) and decision
    replay for prompt tuning (via POST /supervisor/replay/{id}).

    Source pattern: https://x.com/gkisokay/status/2037902655016804496
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS supervisor_decisions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ts              TEXT    NOT NULL,              -- ISO-8601 UTC
            event_type      TEXT    NOT NULL,              -- signal|approval|kill_switch|morning_brief|target|drawdown|cron_failure|trade_closed|ib_disconnect
            marker          TEXT    NOT NULL,              -- ACK|REVIEW|ESCALATE|HOLD_FOR_INFO
            reason          TEXT,                          -- <=200 chars
            payload_json    TEXT,                          -- serialized event payload
            latency_ms      INTEGER NOT NULL DEFAULT 0,
            pass_through    INTEGER NOT NULL DEFAULT 1,    -- 0=swallowed, 1=fired
            correlation_id  TEXT,
            cost_usd        REAL    NOT NULL DEFAULT 0.0
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_supervisor_decisions_ts " "ON supervisor_decisions(ts DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_supervisor_decisions_event_type "
        "ON supervisor_decisions(event_type)"
    )
    conn.commit()
    logger.info("Migration 020 applied — supervisor_decisions table created.")


def migration_022(conn: sqlite3.Connection) -> None:
    """
    022 — mes_session_hypothesis table for the forward-recorder experiment.

    Records daily pre-open state (Corey bias + TradingView gamma snapshot
    + IB levels + hypothesis side) and the session outcome (high/low/close
    + outcome_delta vs. hypothesis). Powers the post-grid-search experiment
    to determine whether Corey-bias + gamma levels predict MES session
    direction, since gamma levels have no historical archive and must be
    recorded forward.

    Schema-first design — extra instruments can be added later via the
    symbol column without another migration.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS mes_session_hypothesis (
            id                         INTEGER PRIMARY KEY AUTOINCREMENT,
            date                       TEXT NOT NULL,              -- YYYY-MM-DD, session date in CT
            symbol                     TEXT NOT NULL,              -- "MES" (expandable)
            recorded_at                TEXT NOT NULL,              -- ISO-8601 UTC when morning row was written
            corey_bias                 TEXT,                       -- bullish|bearish|neutral|null
            corey_conviction           REAL,                       -- 0.0-1.0
            corey_session_type         TEXT,                       -- range_day|trend_day|outside_bar|uncertain|null
            corey_ib_bias              TEXT,                       -- above_ib|below_ib|inside_ib|null
            corey_data_quality         TEXT,                       -- fresh|stale|none
            gamma_snapshot_json        TEXT,                       -- serialized {gex_flip,call_wall,put_wall,hvl,vol_trigger_up,vol_trigger_down,max_pain,data_quality}
            ib_levels_json             TEXT,                       -- serialized DiscordBriefing.ib_levels dict
            entry_hypothesis_side      TEXT,                       -- long|short|skip (derived at record time)
            entry_hypothesis_reason    TEXT,                       -- short text explaining why
            open_price                 REAL,                       -- CT 08:30 open snapshot (or NULL if unavailable)
            high_price                 REAL,                       -- session high (filled by outcome job)
            low_price                  REAL,                       -- session low (filled by outcome job)
            close_price                REAL,                       -- CT 15:00 close (filled by outcome job)
            outcome_delta              REAL,                       -- close-open * (side sign), in points (filled by outcome job)
            outcome_recorded_at        TEXT,                       -- ISO-8601 UTC when outcome row was filled
            UNIQUE(date, symbol)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_mes_session_hyp_date "
        "ON mes_session_hypothesis(date DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_mes_session_hyp_outcome_missing "
        "ON mes_session_hypothesis(date, outcome_recorded_at) "
        "WHERE outcome_recorded_at IS NULL"
    )
    conn.commit()
    logger.info("Migration 022 applied — mes_session_hypothesis table created.")


def migration_024(conn: sqlite3.Connection) -> None:
    """
    024 — Market data bars persistence table.

    Stores OHLCV bars fetched by MarketDataManager.get_bars() so the daily
    post-trade report can re-run signal generators on actual bar history
    (counterfactual + tomorrow's outlook sections).

    PRIMARY KEY (symbol, interval, ts_utc) makes double-inserts a no-op via
    INSERT OR IGNORE.  WAL mode on the main DB keeps bar writes non-blocking.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS market_data_bars (
            symbol      TEXT    NOT NULL,
            interval    TEXT    NOT NULL,
            ts_utc      TEXT    NOT NULL,
            open        REAL    NOT NULL,
            high        REAL    NOT NULL,
            low         REAL    NOT NULL,
            close       REAL    NOT NULL,
            volume      REAL,
            source      TEXT    NOT NULL,
            fetched_at  TEXT    NOT NULL,
            PRIMARY KEY (symbol, interval, ts_utc)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_market_data_bars_symbol_interval_ts
            ON market_data_bars(symbol, interval, ts_utc)
        """
    )
    conn.commit()
    logger.info("Migration 024 applied — market_data_bars table created.")


def migration_025(conn: sqlite3.Connection) -> None:
    """
    025 — Health watchdog snapshots table.

    Records every poll of the /health endpoint made by
    engine/scripts/health_watchdog.py.  One row per 5-minute interval during
    trading hours.  Powers the intraday uptime calculation and Discord alerting
    on degradation transitions.

    reachable=0 means the engine did not respond (timeout / refused).  All
    health-field columns are NULL when reachable=0.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS health_snapshots (
            ts_utc           TEXT NOT NULL PRIMARY KEY,
            status           TEXT NOT NULL,
            reachable        INTEGER NOT NULL,
            llm_healthy      INTEGER,
            tv_mcp_healthy   INTEGER,
            ibkr_data        INTEGER,
            ibkr_exec        INTEGER,
            kill_switch      INTEGER,
            uptime_seconds   REAL,
            raw_json         TEXT,
            fetched_at       TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_health_snapshots_ts ON health_snapshots(ts_utc)")
    conn.commit()
    logger.info("Migration 025 applied — health_snapshots table created.")


def migration_026(conn: sqlite3.Connection) -> None:
    """
    026 — Trade reviews: automated post-trade LLM analysis.

    One row per closed trade (1:1 with paper_trades).  Populated asynchronously
    by TradeReviewService after every trade close.  Stores the LLM-generated
    grade, setup quality assessment, strengths/weaknesses arrays, rule
    violations, a narrative lesson, and improvement tags.

    review_status lifecycle: pending → complete | failed
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trade_reviews (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id         TEXT NOT NULL UNIQUE,
            symbol           TEXT NOT NULL,
            direction        TEXT NOT NULL,
            entry_time       TEXT,
            exit_time        TEXT,
            pnl_usd          REAL,
            pnl_pct          REAL,
            hold_minutes     REAL,
            entry_price      REAL,
            exit_price       REAL,
            stop_loss        REAL,
            take_profit      REAL,
            atr_value        REAL,
            rr_ratio         REAL,
            actual_r         REAL,
            regime           TEXT,
            conviction       REAL,
            bull_score       REAL,
            bear_score       REAL,
            pipeline_summary TEXT,
            grade            TEXT,
            setup_quality    TEXT,
            strengths        TEXT,
            weaknesses       TEXT,
            rule_violations  TEXT,
            lessons          TEXT,
            improvement_tags TEXT,
            llm_model        TEXT,
            review_status    TEXT NOT NULL DEFAULT 'pending',
            created_at       TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
            updated_at       TEXT NOT NULL DEFAULT (datetime('now', 'utc'))
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trade_reviews_trade_id ON trade_reviews(trade_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trade_reviews_grade ON trade_reviews(grade)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_trade_reviews_status ON trade_reviews(review_status)"
    )
    conn.commit()
    logger.info("Migration 026 applied — trade_reviews table created.")


def migration_027(conn: sqlite3.Connection) -> None:
    """
    027 — Multi-account paper testing: account_id columns.

    Adds account_id to paper_trades and pnl_snapshots so dual-emitted trades
    can be tagged per-config (A = production, B = challenger).

    Default 'A' keeps all existing rows valid without data migration.
    Only populates 'B' rows when ENABLE_PARALLEL_PAPER=1.

    Idempotent: uses try/except on duplicate column name.
    """
    for stmt in (
        "ALTER TABLE paper_trades ADD COLUMN account_id TEXT NOT NULL DEFAULT 'A'",
        "ALTER TABLE pnl_snapshots ADD COLUMN account_id TEXT NOT NULL DEFAULT 'A'",
    ):
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc).lower():
                raise
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_paper_trades_account "
        "ON paper_trades(account_id, exit_time)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_pnl_snapshots_account " "ON pnl_snapshots(account_id, date)"
    )
    conn.commit()
    logger.info(
        "Migration 027 applied — account_id columns added to paper_trades and pnl_snapshots."
    )


def migration_028(conn: sqlite3.Connection) -> None:
    """
    028 — Per-account kill switch state for parallel-paper testing.

    Adds the per_account_kill_state table so Account A and Account B can halt
    independently during parallel paper testing (ENABLE_PARALLEL_PAPER=1).

    The GLOBAL kill switch in system_state remains canonical and unchanged.
    This table is additive: when the global switch fires, both accounts halt
    regardless of their individual state.

    Default-inactive: all new rows start with active=0.  Only consulted when
    ENABLE_PARALLEL_PAPER=1 is set in the environment.

    trigger_metric enum values: 'max_daily_loss' | 'max_drawdown' | 'consecutive_loss'
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS per_account_kill_state (
            account_id      TEXT    PRIMARY KEY,
            active          INTEGER NOT NULL DEFAULT 0,
            triggered_at    TEXT,
            reason          TEXT,
            trigger_metric  TEXT,
            trigger_value   REAL,
            cleared_at      TEXT
        )
        """
    )
    conn.commit()
    logger.info("Migration 028 applied — per_account_kill_state table created.")


def migration_029(conn: sqlite3.Connection) -> None:
    """
    029 — realized_peak_equity column on pnl_snapshots.

    Adds a sibling column to the existing peak_equity column.  The existing
    peak_equity column (used by the safety-layer kill switch) is left
    UNTOUCHED so the -10% drawdown halt continues to use mark-to-market
    (MTM) peak — which correctly captures intraday exposure on open
    positions.

    realized_peak_equity tracks only CLOSED (realized) P&L.  It is used
    exclusively by the Phase 3 C5 readiness criterion to prevent phantom
    drawdowns caused by temporary open-position MTM swings from triggering
    a NO-GO verdict when no actual realized loss occurred.

    Backfill: existing rows receive realized_peak_equity = peak_equity as
    a best approximation (pre-fix history cannot be reconstructed precisely;
    the fix applies correctly to all future snapshots).

    Idempotent: uses try/except on duplicate-column-name error.
    """
    try:
        conn.execute("ALTER TABLE pnl_snapshots ADD COLUMN realized_peak_equity REAL DEFAULT NULL")
    except sqlite3.OperationalError as exc:
        if "duplicate column name" not in str(exc).lower():
            raise
        # Column already exists — idempotent
    conn.execute(
        "UPDATE pnl_snapshots SET realized_peak_equity = peak_equity "
        "WHERE realized_peak_equity IS NULL"
    )
    conn.commit()
    logger.info(
        "Migration 029 applied — realized_peak_equity column added to pnl_snapshots "
        "(backfilled from peak_equity; kill switch peak_equity unchanged)."
    )


def migration_030(conn: sqlite3.Connection) -> None:
    """
    030 — Idempotency key column on paper_trades.

    Adds ``idempotency_key TEXT NULL`` with a partial UNIQUE index so that
    duplicate paper-order submissions (same symbol+side+quantity+price within
    a 5-second window) can be detected and collapsed to a single row before
    INSERT.

    The column is nullable so that all existing rows (which carry no key)
    remain valid.  New rows written by ``insert_paper_trade`` / ``insert_trade``
    carry the SHA-256-derived 32-char hex key computed by
    ``database._helpers.compute_order_idempotency_key``.

    A partial UNIQUE index (WHERE idempotency_key IS NOT NULL) prevents NULL
    rows from blocking the constraint — SQLite treats each NULL as distinct
    even without the partial clause, but the explicit filter makes intent clear.

    Root cause addressed: 2026-05-09 (analysed 2026-05-11) — 3 rapid-fire
    /pipeline/run calls within 42 seconds produced 6 identical paper-trade
    rows (12-contract exposure from a 2-contract intent).

    Idempotent: skips gracefully if the column already exists.
    """
    try:
        conn.execute("ALTER TABLE paper_trades ADD COLUMN idempotency_key TEXT")
    except sqlite3.OperationalError as exc:
        if "duplicate column name" not in str(exc).lower():
            raise
        logger.debug("Migration 030: idempotency_key column already exists — skipping ALTER.")

    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_pt_idempotency_key
            ON paper_trades(idempotency_key)
            WHERE idempotency_key IS NOT NULL
        """
    )
    conn.commit()
    logger.info(
        "Migration 030 applied — idempotency_key column + partial UNIQUE index on paper_trades."
    )


def migration_031(conn: sqlite3.Connection) -> None:
    """
    031 — Bracket order IDs on paper_trades.

    Adds three columns so approved bracket submissions can be fully traced
    back from a paper_trades row without joining to JSON blobs or in-memory
    state.

    stop_order_id    — broker order ID of the STP child (TEXT, NULL when bracket
                       not used or STP placement failed)
    target_order_id  — broker order ID of the TP child  (TEXT, NULL when bracket
                       not used or TP omitted)
    bracket_status   — lifecycle label:
                         'attached'         : all three legs placed successfully
                         'partial'          : entry + STP placed, TP failed
                         'failed'           : STP placement failed, entry rolled back
                         'detached_manually': Matt manually cancelled children via TWS
                       NULL when ENABLE_BRACKET_ORDERS=0 (single-order path).

    All three columns are nullable for full backward compatibility with existing
    rows written before migration_031.

    Idempotent: skips gracefully if columns already exist.
    """
    for stmt in (
        "ALTER TABLE paper_trades ADD COLUMN stop_order_id TEXT",
        "ALTER TABLE paper_trades ADD COLUMN target_order_id TEXT",
        "ALTER TABLE paper_trades ADD COLUMN bracket_status TEXT",
    ):
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc).lower():
                raise
            logger.debug("Migration 031: column already exists — skipping: %s", stmt)
    conn.commit()
    logger.info(
        "Migration 031 applied — stop_order_id, target_order_id, bracket_status "
        "columns added to paper_trades."
    )


def migration_032(conn: sqlite3.Connection) -> None:
    """
    032 — NOT NULL constraint on paper_trades.idempotency_key.

    Hardens the dedup guard shipped in migration_030 (commit f3cc273) from a
    runtime check into a structural schema guarantee.  With this migration a
    caller that bypasses ``insert_paper_trade``'s computed key can no longer
    create a NULL-keyed row that would silently defeat the UNIQUE INDEX.

    Motivation
    ----------
    Root cause of the 2026-05-09 6× phantom-trade incident (analysed
    2026-05-11): the column was nullable, so any INSERT path that omitted
    idempotency_key produced a NULL row that the partial UNIQUE index
    (WHERE idempotency_key IS NOT NULL) ignored entirely — meaning the
    constraint provided zero protection for unanticipated callers.

    SQLite limitation
    -----------------
    SQLite cannot ALTER a column from nullable to NOT NULL in-place.  The
    canonical workaround (https://www.sqlite.org/lang_altertable.html):
      1. Backfill all NULL rows with computed keys
      2. CREATE TABLE paper_trades_new with the NOT NULL constraint
      3. INSERT INTO paper_trades_new SELECT * FROM paper_trades
      4. DROP paper_trades; RENAME paper_trades_new → paper_trades
      5. Recreate all indexes
    The whole operation runs inside a single transaction so the live DB is
    never left in a partial state.

    Backfill key formula
    --------------------
    For rows that have entry_time and entry_price/quantity available (all 16
    rows in the live DB as of 2026-05-21), we use the SAME SHA-256 formula as
    ``compute_order_idempotency_key``, but derived from the row's historical
    entry_time epoch (not the current clock).  This makes the backfill keys:
      - Deterministic (re-runnable)
      - Historically grounded (bucket reflects when the trade was entered)
      - Non-recomputable by a future call (the time bucket will have expired)

    For rows missing entry_time or entry_price (defensive only — no such rows
    exist in the live DB), a fallback key ``backfill-<id>-<symbol>`` is used.
    These fallback keys are intentionally non-standard; they carry the prefix
    "backfill-" so they can be identified in forensic queries.

    Collision handling during backfill
    -----------------------------------
    Two rows with the same symbol/side/qty/price in the same 5s bucket would
    compute the same key.  If a collision is detected during backfill, the
    later row (higher id) gets a suffix ``-<id>`` appended to its key to ensure
    uniqueness.  These suffixed keys are still 32+ chars but are not pure SHA-256
    digests; the suffix format is documented here so forensic queries can flag them.

    Idempotency
    -----------
    Checks ``PRAGMA table_info(paper_trades)`` for notnull=1 on idempotency_key
    before running.  Safe to call multiple times.
    """
    import hashlib
    import math
    from datetime import datetime

    # ── Idempotency check ─────────────────────────────────────────────────────
    col_info = {row[1]: row[3] for row in conn.execute("PRAGMA table_info(paper_trades)")}
    if col_info.get("idempotency_key") == 1:
        logger.info("Migration 032 skipped — idempotency_key already NOT NULL.")
        return

    # ── Step 1: Backfill NULL idempotency_key rows ────────────────────────────
    # Use the row's historical entry_time to derive the time bucket (same formula
    # as compute_order_idempotency_key, but with historical epoch instead of NOW).
    # This makes backfill keys deterministic and historically grounded.
    null_rows = conn.execute(
        "SELECT id, symbol, side, quantity, entry_price, entry_time "
        "FROM paper_trades WHERE idempotency_key IS NULL"
    ).fetchall()

    seen_keys: set = set()
    for row in null_rows:
        row_id, symbol, side, quantity, entry_price, entry_time = row

        # Compute the historical time bucket from entry_time
        backfill_key = None
        if entry_time and entry_price is not None and quantity is not None:
            try:
                # Parse ISO-8601; handle both +00:00 and Z suffixes
                ts_str = entry_time.replace("Z", "+00:00")
                # Remove microseconds suffix if present for fromisoformat compat
                if "." in ts_str and "+" in ts_str:
                    dot_pos = ts_str.index(".")
                    plus_pos = ts_str.index("+")
                    ts_str = ts_str[:dot_pos] + ts_str[plus_pos:]
                epoch = datetime.fromisoformat(ts_str).timestamp()
                bucket = int(math.floor(epoch / 5))
                qty_int = int(round(float(quantity)))
                price_rounded = round(float(entry_price), 2)
                raw = (
                    f"{str(symbol).upper()}|{str(side).lower()}|"
                    f"{qty_int}|{price_rounded:.2f}|{bucket}"
                )
                candidate = hashlib.sha256(raw.encode()).hexdigest()[:32]
                # Collision guard: if two historical rows map to the same key,
                # suffix the later one with -<id> to preserve uniqueness.
                if candidate in seen_keys:
                    candidate = f"{candidate}-{row_id}"
                seen_keys.add(candidate)
                backfill_key = candidate
            except Exception as exc:
                logger.warning(
                    "Migration 032: could not parse entry_time for id=%s (%s); "
                    "using fallback key.",
                    row_id,
                    exc,
                )

        if backfill_key is None:
            # Fallback for rows with missing fields — deterministic, identifiable
            backfill_key = f"backfill-{row_id}-{str(symbol).upper()}"
            if backfill_key in seen_keys:
                backfill_key = f"backfill-{row_id}-{str(symbol).upper()}-dup"
            seen_keys.add(backfill_key)

        conn.execute(
            "UPDATE paper_trades SET idempotency_key = ? WHERE id = ?",
            (backfill_key, row_id),
        )

    conn.commit()

    # ── Verify zero NULLs remain ──────────────────────────────────────────────
    remaining_nulls = conn.execute(
        "SELECT COUNT(*) FROM paper_trades WHERE idempotency_key IS NULL"
    ).fetchone()[0]
    if remaining_nulls != 0:
        raise RuntimeError(
            f"Migration 032: {remaining_nulls} NULL idempotency_key rows remain "
            "after backfill — aborting table-rebuild to prevent constraint failure."
        )

    # ── Step 2: Capture pre-migration row count ───────────────────────────────
    pre_count = conn.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0]

    # ── Step 3: Rebuild table with NOT NULL constraint ────────────────────────
    # The new DDL is identical to the existing paper_trades schema but with
    # idempotency_key TEXT NOT NULL (was TEXT).  All columns are preserved;
    # order is preserved to keep the INSERT INTO ... SELECT * round-trip valid.
    conn.execute(
        """
        CREATE TABLE paper_trades_new (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id            TEXT    NOT NULL UNIQUE,
            symbol              TEXT    NOT NULL,
            side                TEXT    NOT NULL,
            quantity            REAL    NOT NULL,
            entry_price         REAL    NOT NULL,
            exit_price          REAL,
            entry_time          TEXT    NOT NULL,
            exit_time           TEXT,
            pnl                 REAL,
            status              TEXT    NOT NULL DEFAULT 'open',
            strategy_params     TEXT,
            notes               TEXT    DEFAULT '',
            regime              TEXT,
            structure_position  TEXT,
            bias                TEXT,
            composite_score     REAL,
            stc_contrib         INTEGER,
            orb_contrib         INTEGER,
            vwap_contrib        INTEGER,
            risk_pct_used       REAL,
            stop_loss           REAL,
            take_profit         REAL,
            account_id          TEXT    NOT NULL DEFAULT 'A',
            idempotency_key     TEXT    NOT NULL,
            stop_order_id       TEXT,
            target_order_id     TEXT,
            bracket_status      TEXT
        )
        """
    )

    conn.execute("INSERT INTO paper_trades_new SELECT * FROM paper_trades")

    post_insert_count = conn.execute("SELECT COUNT(*) FROM paper_trades_new").fetchone()[0]
    if post_insert_count != pre_count:
        conn.execute("DROP TABLE paper_trades_new")
        conn.commit()
        raise RuntimeError(
            f"Migration 032: row count mismatch after INSERT INTO paper_trades_new "
            f"(expected {pre_count}, got {post_insert_count}) — aborting."
        )

    conn.execute("DROP TABLE paper_trades")
    conn.execute("ALTER TABLE paper_trades_new RENAME TO paper_trades")

    # ── Step 4: Recreate all indexes ──────────────────────────────────────────
    # Recreating in the same order as the original schema.
    # Note: sqlite_autoindex_paper_trades_1 (for trade_id UNIQUE) is implicitly
    # recreated by the CREATE TABLE DDL above — no explicit CREATE INDEX needed.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pt_symbol ON paper_trades(symbol)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pt_status ON paper_trades(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pt_entry_time ON paper_trades(entry_time)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_paper_trades_account "
        "ON paper_trades(account_id, exit_time)"
    )
    # The UNIQUE index on idempotency_key is now a full (non-partial) index because
    # the column is NOT NULL — every row carries a key, so the partial filter
    # (WHERE idempotency_key IS NOT NULL) is logically equivalent to no filter.
    # We keep the partial clause for semantic clarity and backward compatibility
    # with any query that references the index name.
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_pt_idempotency_key
            ON paper_trades(idempotency_key)
            WHERE idempotency_key IS NOT NULL
        """
    )

    conn.commit()

    # ── Final verification ────────────────────────────────────────────────────
    post_count = conn.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0]
    assert (
        post_count == pre_count
    ), f"Migration 032: final row count {post_count} != pre-migration {pre_count}"
    final_nulls = conn.execute(
        "SELECT COUNT(*) FROM paper_trades WHERE idempotency_key IS NULL"
    ).fetchone()[0]
    assert final_nulls == 0, f"Migration 032: {final_nulls} NULL keys remain after rebuild"

    logger.info(
        "Migration 032 applied — paper_trades.idempotency_key is now NOT NULL. "
        "Backfilled %d rows; pre=%d post=%d rows; 0 NULLs remaining.",
        len(null_rows),
        pre_count,
        post_count,
    )


def migration_023(conn: sqlite3.Connection) -> None:
    """
    023 — trading_patterns schema alignment.

    Adds missing columns to trading_patterns table to support both
    consolidator.py and patterns.py (AgentFeedbackTracker) logic.
    """
    columns_to_add = [
        ("pattern_type", "TEXT"),
        ("win_count", "INTEGER DEFAULT 0"),
        ("loss_count", "INTEGER DEFAULT 0"),
        ("avg_return", "REAL DEFAULT 0.0"),
        ("is_active", "INTEGER DEFAULT 1"),
    ]

    for col_name, col_type in columns_to_add:
        try:
            conn.execute(f"ALTER TABLE trading_patterns ADD COLUMN {col_name} {col_type}")
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc).lower():
                raise
            logger.debug(f"Migration 023: column {col_name} already exists in trading_patterns.")

    conn.commit()
    logger.info("Migration 023 applied — trading_patterns schema aligned.")


def migration_021(conn: sqlite3.Connection) -> None:
    """
    021 — paper_trades stop_loss / take_profit columns.

    ``insert_paper_trade`` always referenced these columns; migration 001's
    initial ``paper_trades`` DDL did not create them, breaking **fresh** DBs.
    Idempotent: skips if columns already exist (e.g. manually altered DBs).
    """
    for stmt in (
        "ALTER TABLE paper_trades ADD COLUMN stop_loss REAL",
        "ALTER TABLE paper_trades ADD COLUMN take_profit REAL",
    ):
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc).lower():
                raise
    conn.commit()
    logger.info("Migration 021 applied — paper_trades stop_loss/take_profit columns.")


def migration_033(conn: sqlite3.Connection) -> None:
    """
    033 — Agent memory.
    Adds agent_memory table for Phase 3.5 persistent working memory.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_memory (
            id          TEXT PRIMARY KEY,
            agent_name  TEXT NOT NULL,
            symbol      TEXT,
            topic       TEXT DEFAULT 'general',
            content     TEXT NOT NULL,
            metadata    TEXT DEFAULT '{}',
            created_at  TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_am_agent_name ON agent_memory(agent_name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_am_symbol     ON agent_memory(symbol)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_am_topic      ON agent_memory(topic)")
    conn.commit()


def migration_034(conn: sqlite3.Connection) -> None:
    """
    034 — FOMC History.
    Adds fomc_history table for Phase 6.5 news NLP.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS fomc_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            meeting_date TEXT NOT NULL UNIQUE,
            statement   TEXT NOT NULL,
            dot_plot    TEXT,
            analysis    TEXT,
            created_at  TEXT NOT NULL
        )
        """
    )
    conn.commit()


def migration_035(conn: sqlite3.Connection) -> None:
    """
    035 — Canary Strategies.
    Adds canary_strategies table for Phase 7.3 A/B canary framework.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS canary_strategies (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_file   TEXT NOT NULL UNIQUE,
            symbol          TEXT NOT NULL,
            interval        TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'active', -- active | passed | failed | retired
            baseline_pf     REAL NOT NULL,
            start_time      TEXT NOT NULL, -- ISO-8601 UTC
            end_time        TEXT NOT NULL, -- ISO-8601 UTC
            actual_end_time TEXT,          -- ISO-8601 UTC
            live_pf         REAL DEFAULT 0.0,
            num_trades      INTEGER DEFAULT 0,
            metadata        TEXT DEFAULT '{}',
            created_at      TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cs_status ON canary_strategies(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cs_symbol ON canary_strategies(symbol)")
    conn.commit()


def migration_036(conn: sqlite3.Connection) -> None:
    """
    036 — IBKR fills import.
    Raw execution fills from IB, keyed by exec_id for idempotent imports.
    Populated via POST /brokers/reconcile using the live IBGatewayManager.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ibkr_fills (
            exec_id     TEXT PRIMARY KEY,
            account     TEXT NOT NULL,
            symbol      TEXT NOT NULL,
            sec_type    TEXT NOT NULL DEFAULT 'FUT',
            expiry      TEXT NOT NULL DEFAULT '',
            side        TEXT NOT NULL,
            quantity    REAL NOT NULL,
            price       REAL NOT NULL,
            avg_price   REAL,
            commission  REAL,
            exchange    TEXT,
            currency    TEXT NOT NULL DEFAULT 'USD',
            fill_time   TEXT NOT NULL,
            order_id    INTEGER,
            imported_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ibkr_fills_account ON ibkr_fills(account)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ibkr_fills_symbol ON ibkr_fills(symbol)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ibkr_fills_fill_time ON ibkr_fills(fill_time)")
    conn.commit()


def migration_037(conn: sqlite3.Connection) -> None:
    """
    037 — ibkr_fills order provenance columns.

    Adds order_ref and parent_order_id so reconciled real IB fills can be
    matched back to JARVIS-originated orders. place_paper_order stamps an IB
    orderRef of JARVIS-<uuid> on every order; get_executions surfaces it into
    the reconciler. These columns let the execution-fidelity forward-test
    compare real fills against paper_trades intent and filter out DUP662235's
    pre-seeded demo-seed activity (which carries no JARVIS- orderRef).

    Idempotent: skips columns that already exist (manually-altered DBs).
    """
    for stmt in (
        "ALTER TABLE ibkr_fills ADD COLUMN order_ref TEXT",
        "ALTER TABLE ibkr_fills ADD COLUMN parent_order_id INTEGER",
    ):
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc).lower():
                raise
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ibkr_fills_order_ref ON ibkr_fills(order_ref)"
    )
    conn.commit()
    logger.info("Migration 037 applied — ibkr_fills order_ref/parent_order_id columns.")


def migration_038(conn: sqlite3.Connection) -> None:
    """
    038 — paper_trades.slippage_ticks column.

    Adds the slippage_ticks column that _load_closed_trades()
    (proactive_validation_router.py) and paper_trade_pairing.py already SELECT
    but which no migration ever created. Before this, that SELECT raised
    `sqlite3.OperationalError: no such column: slippage_ticks`, was swallowed,
    and the execution-fidelity validation silently saw zero closed trades —
    reporting INSUFFICIENT_DATA regardless of real fills. The column is
    populated on trade close from the matched real IB fill (NULL when no real
    fill is matched, e.g. simulated mode).

    Idempotent: skips the column if it already exists (manually-altered DBs).
    """
    try:
        conn.execute("ALTER TABLE paper_trades ADD COLUMN slippage_ticks REAL")
    except sqlite3.OperationalError as exc:
        if "duplicate column name" not in str(exc).lower():
            raise
    conn.commit()
    logger.info("Migration 038 applied — paper_trades.slippage_ticks column.")


def migration_039(conn: sqlite3.Connection) -> None:
    """
    039 — bar_quality_rejections table (observability for the write-time gate).

    Both contamination defenses (bars_repository._row_rejection sanity checks and
    bar_quality_gate.apply_gate) refuse implausible bars at save_bars but, before
    this, the rejection fact existed only as an ephemeral log line — nothing
    surfaced "the gate is working" to the dashboard. This table records one row
    per (batch, path, reason category) with a count, so /analytics/bar-quality
    can show per-symbol/source/reason rejection activity. Zero rows = clean data
    (the honest steady state), not a broken gate.

    path: 'sanity' (row-level _row_rejection) | 'gate' (apply_gate screen).
    reason: machine category (IB_SENTINEL, PRICE_BAND, NEIGHBOR_JUMP,
    RANGE_EXPLOSION, OHLC_LOGIC, NONFINITE, NONPOSITIVE, BLOCKED_SOURCE).

    Idempotent: CREATE TABLE / INDEX IF NOT EXISTS.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS bar_quality_rejections (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_utc    TEXT    NOT NULL,
            symbol    TEXT    NOT NULL,
            interval  TEXT    NOT NULL,
            source    TEXT    NOT NULL DEFAULT '',
            path      TEXT    NOT NULL,
            reason    TEXT    NOT NULL,
            detail    TEXT,
            count     INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_bqr_ts ON bar_quality_rejections(ts_utc DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_bqr_symbol_ts "
        "ON bar_quality_rejections(symbol, ts_utc DESC)"
    )
    conn.commit()
    logger.info("Migration 039 applied — bar_quality_rejections observability table.")


def migration_040(conn: sqlite3.Connection) -> None:
    """
    040 — MAE/MFE excursion columns on paper_trades.

    (Renumbered from 039 during the family-fdr-campaign integration: master had
    already shipped 039 as bar_quality_rejections, so this excursion migration
    takes the next free slot.)

    Adds four nullable REAL columns for post-trade excursion analytics:

        mae_pct  — Maximum Adverse Excursion as fraction of entry_price (>=0)
                   LONG:  (entry_price - min_low) / entry_price
                   SHORT: (max_high - entry_price) / entry_price

        mfe_pct  — Maximum Favorable Excursion as fraction of entry_price (>=0)
                   LONG:  (max_high - entry_price) / entry_price
                   SHORT: (entry_price - min_low) / entry_price

        mae_usd  — MAE in dollars (mae_pct * entry_price * multiplier * qty)

        mfe_usd  — MFE in dollars (mfe_pct * entry_price * multiplier * qty)

    All four are NULL for historical trades until the backfill callable
    (analytics.excursion_backfill.run_backfill) is invoked.  New trades
    are populated asynchronously after close by the wiring in
    routers.analytics_router.

    Idempotent: uses try/except on "duplicate column name" so the migration
    is safe on databases that were altered manually (pattern from migration_038).
    """
    for col in ("mae_pct", "mfe_pct", "mae_usd", "mfe_usd"):
        try:
            conn.execute(f"ALTER TABLE paper_trades ADD COLUMN {col} REAL")
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc).lower():
                raise
    conn.commit()
    logger.info("Migration 040 applied — mae_pct, mfe_pct, mae_usd, mfe_usd columns on paper_trades.")


def migration_041(conn: sqlite3.Connection) -> None:
    """
    041 — Tamper-evident decision-log audit chain columns on pending_trade_approvals.

    Adds two nullable TEXT columns that carry the SHA-256 hash chain over the
    pipeline decision snapshot (see engine/approval/audit_chain.py):

        prev_hash   — audit_hash of the immediately preceding decision row
                      (GENESIS_HASH for the first hashed row).
        audit_hash  — sha256(prev_hash + canonical_json(pipeline_snapshot)).

    Both are NULL for rows written before this migration; the chain verifier
    (DatabaseManager.verify_decision_audit_chain) starts at the first hashed row.
    Passive metadata only — hashing never gates an approval and sits outside the
    safety path.

    Idempotent: try/except on "duplicate column name" (pattern from migration_040).
    """
    for col in ("prev_hash", "audit_hash"):
        try:
            conn.execute(f"ALTER TABLE pending_trade_approvals ADD COLUMN {col} TEXT")
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc).lower():
                raise
    conn.commit()
    logger.info(
        "Migration 041 applied — prev_hash, audit_hash columns on pending_trade_approvals."
    )


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
    migration_019,  # version 19
    migration_020,  # version 20
    migration_021,  # version 21
    migration_022,  # version 22
    migration_023,  # version 23
    migration_024,  # version 24
    migration_025,  # version 25
    migration_026,  # version 26
    migration_027,  # version 27
    migration_028,  # version 28
    migration_029,  # version 29
    migration_030,  # version 30
    migration_031,  # version 31
    migration_032,  # version 32
    migration_033,  # version 33
    migration_034,  # version 34
    migration_035,  # version 35
    migration_036,  # version 36
    migration_037,  # version 37
    migration_038,  # version 38
    migration_039,  # version 39
    migration_040,  # version 40
    migration_041,  # version 41
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
    "Full pipeline JSON: full_pipeline_json column on decisions for stage-by-stage reasoning storage",
    "Supervisor decisions: supervisor_decisions table for Hermes-pattern notifier gating (ACK/REVIEW/ESCALATE/HOLD audit log)",
    "Paper trades: stop_loss and take_profit columns for insert_paper_trade / fresh DB compatibility",
    "MES session hypothesis: forward-recorder table for Corey bias + gamma levels daily snapshots + session outcomes",
    "Trading patterns alignment: adding pattern_type, win_count, loss_count, avg_return, and is_active columns.",
    "Market data bars: market_data_bars OHLCV persistence table for counterfactual + outlook sections.",
    "Health watchdog snapshots: health_snapshots table for 5-minute /health poll history and intraday uptime.",
    "Trade reviews: trade_reviews table for automated post-trade LLM analysis (grade A-F, strengths, weaknesses, lessons).",
    "Multi-account paper testing: account_id columns on paper_trades and pnl_snapshots for parallel A/B config comparison.",
    "Per-account kill switch state: per_account_kill_state table for independent halt per paper account (ENABLE_PARALLEL_PAPER=1 only).",
    "Realized peak equity: realized_peak_equity column on pnl_snapshots for Phase 3 C5 phantom-drawdown fix (kill switch peak_equity unchanged).",
    "Order dedup: idempotency_key column + partial UNIQUE index on paper_trades to prevent duplicate submissions within a 5-second window.",
    "Bracket order IDs: stop_order_id, target_order_id, bracket_status columns on paper_trades for atomic IB bracket traceability.",
    "NOT NULL constraint: idempotency_key promoted to NOT NULL on paper_trades; backfills historical NULLs with deterministic SHA-256 keys derived from entry_time bucket.",
    "Agent memory: agent_memory table for Phase 3.5 persistent working memory.",
    "FOMC history: fomc_history table for Phase 6.5 news NLP.",
    "Canary strategies: canary_strategies table for Phase 7.3 A/B canary framework.",
    "IBKR fills import: ibkr_fills table for raw execution fills from IB, keyed by exec_id.",
    "IBKR fills order provenance: order_ref + parent_order_id columns on ibkr_fills for JARVIS-tagged fill reconciliation (execution-fidelity forward-test).",
    "Paper trades slippage: slippage_ticks column on paper_trades (queried by execution-fidelity validation + paper_trade_pairing but never created); populated on close from matched real IB fill.",
    "Bar quality observability: bar_quality_rejections table recording bars rejected by the write-time bar-quality gate (symbol, ts_utc, reason) for the Trust Pane observability surface.",
    "MAE/MFE excursion: mae_pct, mfe_pct, mae_usd, mfe_usd columns on paper_trades for post-trade excursion analytics.",
    "Decision-log audit chain: prev_hash, audit_hash columns on pending_trade_approvals for tamper-evident SHA-256 chaining of pipeline decision snapshots.",
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
