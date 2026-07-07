import logging
import sqlite3
from typing import Optional

from . import storage_questdb as _qdb
from .models import Bookmark, BotSignal, CoreyAlert, CoreyCommentary, IBReport

logger = logging.getLogger(__name__)

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS discord_bot_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT UNIQUE NOT NULL,
    timestamp TEXT NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT,
    direction TEXT,
    signal_type TEXT,
    entry_price REAL,
    target1 REAL,
    target2 REAL,
    stop1 REAL,
    stop2 REAL,
    win_rate REAL,
    wins INTEGER,
    losses INTEGER,
    mfe REAL,
    mae REAL,
    rr REAL,
    gain REAL,
    draw REAL,
    net REAL,
    last_price REAL,
    raw_description TEXT,
    source_channel TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_bot_signals_symbol_ts
  ON discord_bot_signals(symbol, timestamp DESC);

CREATE TABLE IF NOT EXISTS discord_ib_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT UNIQUE NOT NULL,
    timestamp TEXT NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT,
    ib_open REAL,
    ib_high REAL,
    ib_low REAL,
    ib_close REAL,
    ib_range REAL,
    ibu50 REAL,
    ibu100 REAL,
    ibd50 REAL,
    ibd100 REAL,
    auction_context TEXT,
    trade_plan TEXT,
    raw_content TEXT,
    source_channel TEXT DEFAULT 'indicator-alerts',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS discord_corey_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT UNIQUE NOT NULL,
    timestamp TEXT NOT NULL,
    content TEXT NOT NULL,
    symbol TEXT,
    direction TEXT,
    price REAL,
    source_channel TEXT DEFAULT 'trade-alerts',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS discord_corey_commentary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT UNIQUE NOT NULL,
    timestamp TEXT NOT NULL,
    content TEXT NOT NULL,
    channel TEXT NOT NULL,
    author_id TEXT DEFAULT '564449478174703646',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS discord_bookmarks (
    message_id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL,
    posted_at TEXT NOT NULL,
    url TEXT NOT NULL,
    domain TEXT,
    source_type TEXT,
    embed_title TEXT,
    embed_description TEXT,
    content TEXT,
    author_id TEXT,
    author_name TEXT,
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    attachment_urls TEXT
);
CREATE INDEX IF NOT EXISTS idx_bookmarks_posted ON discord_bookmarks(posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_bookmarks_domain ON discord_bookmarks(domain);
CREATE INDEX IF NOT EXISTS idx_bookmarks_source_type ON discord_bookmarks(source_type);

CREATE TABLE IF NOT EXISTS discord_daily_sentiment (
    date TEXT NOT NULL PRIMARY KEY,
    sentiment_score REAL NOT NULL,
    post_count INTEGER NOT NULL,
    source TEXT DEFAULT 'discord_corey_commentary',
    computed_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS discord_commentary_fts
USING fts5(content, timestamp, channel);

CREATE TRIGGER IF NOT EXISTS discord_commentary_fts_ai
AFTER INSERT ON discord_corey_commentary BEGIN
    INSERT INTO discord_commentary_fts(rowid, content, timestamp, channel)
    VALUES (new.id, new.content, new.timestamp, new.channel);
END;

CREATE TRIGGER IF NOT EXISTS discord_commentary_fts_ad
AFTER DELETE ON discord_corey_commentary BEGIN
    INSERT INTO discord_commentary_fts(discord_commentary_fts, rowid, content, timestamp, channel)
    VALUES ('delete', old.id, old.content, old.timestamp, old.channel);
END;

-- AFTER UPDATE trigger: keep FTS in lock-step if discord_corey_commentary rows
-- are ever updated (no current update path exists, but adding this trigger
-- prevents silent FTS drift if an edit-message feature is added later).
CREATE TRIGGER IF NOT EXISTS discord_commentary_fts_au
AFTER UPDATE ON discord_corey_commentary BEGIN
    INSERT INTO discord_commentary_fts(discord_commentary_fts, rowid, content, timestamp, channel)
    VALUES ('delete', old.id, old.content, old.timestamp, old.channel);
    INSERT INTO discord_commentary_fts(rowid, content, timestamp, channel)
    VALUES (new.id, new.content, new.timestamp, new.channel);
END;
"""

# Columns added post-Phase-B (Workstream A, 2026-04-20) and post-Path-B
# (2026-05-20, attachment_urls). ALTER handles pre-existing DBs; CREATE TABLE
# above handles fresh ones. Both paths converge on the same shape.
_BOOKMARK_MIGRATION_COLUMNS = [
    ("content", "TEXT"),
    ("author_id", "TEXT"),
    ("author_name", "TEXT"),
    ("attachment_urls", "TEXT"),
]


def init_tables(db_path: str) -> None:
    """Create Discord tables if they don't exist, then run in-place migrations.

    Migration path for `discord_bookmarks`: CREATE TABLE IF NOT EXISTS leaves pre-Phase-B
    tables alone, so new columns (content, author_id, author_name) must be ADDed. We
    catch OperationalError per column so a fully-migrated DB is a no-op.
    """
    conn = sqlite3.connect(db_path)
    try:
        mode = conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]
        if mode != "wal":
            logger.warning(
                "WAL mode not activated for %s (got %r) — concurrent writer lock contention possible",
                db_path,
                mode,
            )
        conn.executescript(CREATE_TABLES_SQL)
        existing_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(discord_bookmarks)").fetchall()
        }
        for col, coltype in _BOOKMARK_MIGRATION_COLUMNS:
            if col not in existing_cols:
                try:
                    conn.execute(f"ALTER TABLE discord_bookmarks ADD COLUMN {col} {coltype}")
                except sqlite3.OperationalError as e:
                    # Racing a concurrent init is fine — the column now exists.
                    if "duplicate column name" not in str(e).lower():
                        raise
        # Bootstrap FTS index for existing databases that had rows before the
        # virtual table was added (CREATE TRIGGER only fires on new inserts).
        try:
            fts_count = conn.execute("SELECT COUNT(*) FROM discord_commentary_fts").fetchone()[0]
            if fts_count == 0:
                src_count = conn.execute(
                    "SELECT COUNT(*) FROM discord_corey_commentary"
                ).fetchone()[0]
                if src_count > 0:
                    conn.execute(
                        """
                        INSERT INTO discord_commentary_fts(rowid, content, timestamp, channel)
                        SELECT id, content, timestamp, channel FROM discord_corey_commentary
                        """
                    )
                    logger.info("Bootstrapped discord_commentary_fts with %d rows", src_count)
        except sqlite3.OperationalError:
            pass  # FTS5 unavailable in this SQLite build — LIKE fallback still works

        conn.commit()
    finally:
        conn.close()  # `with sqlite3.connect(...)` only commits, never closes — Windows holds file lock otherwise
    logger.info(f"Discord tables initialized in {db_path}")


def insert_bot_signal(conn: sqlite3.Connection, signal: BotSignal) -> bool:
    """Insert a bot signal. Returns True if inserted, False if duplicate."""
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO discord_bot_signals
            (message_id, timestamp, symbol, timeframe, direction, signal_type,
             entry_price, target1, target2, stop1, stop2, win_rate, wins, losses,
             mfe, mae, rr, gain, draw, net, last_price, raw_description, source_channel)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                signal.message_id,
                signal.timestamp,
                signal.symbol,
                signal.timeframe,
                signal.direction,
                signal.signal_type,
                signal.entry_price,
                signal.target1,
                signal.target2,
                signal.stop1,
                signal.stop2,
                signal.win_rate,
                signal.wins,
                signal.losses,
                signal.mfe,
                signal.mae,
                signal.rr,
                signal.gain,
                signal.draw,
                signal.net,
                signal.last_price,
                signal.raw_description,
                signal.source_channel,
            ),
        )
        inserted = conn.execute("SELECT changes()").fetchone()[0] > 0
    except sqlite3.Error as e:
        logger.error(f"Error inserting bot signal {signal.message_id}: {e}")
        return False
    # Dual-write to QuestDB shadow (non-blocking; errors logged, not raised)
    try:
        _qdb.insert_bot_signal_ts(signal)
    except Exception as exc:  # pragma: no cover — _qdb functions never raise, but belt+suspenders
        logger.warning(
            "QuestDB dual-write hook failed for bot signal %s: %s", signal.message_id, exc
        )
    return inserted


def insert_ib_report(conn: sqlite3.Connection, report: IBReport) -> bool:
    """Insert an IB report. Returns True if inserted, False if duplicate."""
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO discord_ib_reports
            (message_id, timestamp, symbol, timeframe, ib_open, ib_high, ib_low,
             ib_close, ib_range, ibu50, ibu100, ibd50, ibd100, auction_context,
             trade_plan, raw_content, source_channel)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                report.message_id,
                report.timestamp,
                report.symbol,
                report.timeframe,
                report.ib_open,
                report.ib_high,
                report.ib_low,
                report.ib_close,
                report.ib_range,
                report.ibu50,
                report.ibu100,
                report.ibd50,
                report.ibd100,
                report.auction_context,
                report.trade_plan,
                report.raw_content,
                report.source_channel,
            ),
        )
        inserted = conn.execute("SELECT changes()").fetchone()[0] > 0
    except sqlite3.Error as e:
        logger.error(f"Error inserting IB report {report.message_id}: {e}")
        return False
    # Dual-write to QuestDB shadow (non-blocking; errors logged, not raised)
    try:
        _qdb.insert_ib_report_ts(report)
    except Exception as exc:  # pragma: no cover
        logger.warning(
            "QuestDB dual-write hook failed for IB report %s: %s", report.message_id, exc
        )
    return inserted


def insert_corey_alert(conn: sqlite3.Connection, alert: CoreyAlert) -> bool:
    """Insert a Corey alert. Returns True if inserted, False if duplicate."""
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO discord_corey_alerts
            (message_id, timestamp, content, symbol, direction, price, source_channel)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            (
                alert.message_id,
                alert.timestamp,
                alert.content,
                alert.symbol,
                alert.direction,
                alert.price,
                alert.source_channel,
            ),
        )
        return conn.execute("SELECT changes()").fetchone()[0] > 0
    except sqlite3.Error as e:
        logger.error(f"Error inserting Corey alert {alert.message_id}: {e}")
        return False


def insert_corey_commentary(conn: sqlite3.Connection, commentary: CoreyCommentary) -> bool:
    """Insert Corey commentary. Returns True if inserted, False if duplicate."""
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO discord_corey_commentary
            (message_id, timestamp, content, channel, author_id)
            VALUES (?, ?, ?, ?, ?)
        """,
            (
                commentary.message_id,
                commentary.timestamp,
                commentary.content,
                commentary.channel,
                commentary.author_id,
            ),
        )
        inserted = conn.execute("SELECT changes()").fetchone()[0] > 0
    except sqlite3.Error as e:
        logger.error(f"Error inserting commentary {commentary.message_id}: {e}")
        return False
    # Dual-write to QuestDB shadow (non-blocking; errors logged, not raised)
    try:
        _qdb.insert_corey_commentary_ts(commentary)
    except Exception as exc:  # pragma: no cover
        logger.warning(
            "QuestDB dual-write hook failed for commentary %s: %s", commentary.message_id, exc
        )
    return inserted


def insert_bookmark(conn: sqlite3.Connection, bookmark: Bookmark) -> bool:
    """Insert a bookmark. Returns True if inserted, False if duplicate (message_id PK)."""
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO discord_bookmarks
            (message_id, channel_id, posted_at, url, domain, source_type,
             embed_title, embed_description, content, author_id, author_name,
             attachment_urls)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                bookmark.message_id,
                bookmark.channel_id,
                bookmark.posted_at,
                bookmark.url,
                bookmark.domain,
                bookmark.source_type,
                bookmark.embed_title,
                bookmark.embed_description,
                bookmark.content,
                bookmark.author_id,
                bookmark.author_name,
                bookmark.attachment_urls,
            ),
        )
        return conn.execute("SELECT changes()").fetchone()[0] > 0
    except sqlite3.Error as e:
        logger.error(f"Error inserting bookmark {bookmark.message_id}: {e}")
        return False


def update_bookmark_context(
    conn: sqlite3.Connection,
    message_id: str,
    content: Optional[str],
    author_id: Optional[str],
    author_name: Optional[str],
) -> bool:
    """Backfill content/author on a row that was inserted pre-Workstream-A.

    Returns True if the row existed and was updated, False if no such message_id.
    INSERT OR IGNORE in the import path cannot overwrite existing rows, so this
    helper is called separately by the CLI to populate the new columns on the
    371 pre-existing bookmarks.
    """
    try:
        conn.execute(
            """
            UPDATE discord_bookmarks
               SET content = ?, author_id = ?, author_name = ?
             WHERE message_id = ?
            """,
            (content, author_id, author_name, message_id),
        )
        return conn.execute("SELECT changes()").fetchone()[0] > 0
    except sqlite3.Error as e:
        logger.error(f"Error updating bookmark context {message_id}: {e}")
        return False


def get_stats(db_path: str) -> dict:
    """Return import statistics for all Discord tables."""
    with sqlite3.connect(db_path) as conn:
        stats = {}
        for table in [
            "discord_bot_signals",
            "discord_ib_reports",
            "discord_corey_alerts",
            "discord_corey_commentary",
        ]:
            row = conn.execute(
                f"SELECT COUNT(*), MIN(timestamp), MAX(timestamp) FROM {table}"
            ).fetchone()
            stats[table] = {"count": row[0], "earliest": row[1], "latest": row[2]}
        # Per-symbol breakdown for bot signals
        symbols = conn.execute(
            "SELECT symbol, COUNT(*) FROM discord_bot_signals GROUP BY symbol ORDER BY COUNT(*) DESC"
        ).fetchall()
        stats["bot_signals_by_symbol"] = {row[0]: row[1] for row in symbols}
        # Bookmarks use posted_at (not timestamp), handle separately
        bm_row = conn.execute(
            "SELECT COUNT(*), MIN(posted_at), MAX(posted_at) FROM discord_bookmarks"
        ).fetchone()
        stats["discord_bookmarks"] = {
            "count": bm_row[0],
            "earliest": bm_row[1],
            "latest": bm_row[2],
        }
        bm_sources = conn.execute(
            "SELECT source_type, COUNT(*) FROM discord_bookmarks GROUP BY source_type ORDER BY COUNT(*) DESC"
        ).fetchall()
        stats["bookmarks_by_source_type"] = {row[0] or "unknown": row[1] for row in bm_sources}
        return stats
