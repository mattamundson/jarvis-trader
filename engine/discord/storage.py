import logging
import sqlite3

from .models import BotSignal, CoreyAlert, CoreyCommentary, IBReport

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
"""


def init_tables(db_path: str) -> None:
    """Create Discord tables if they don't exist."""
    with sqlite3.connect(db_path) as conn:
        conn.executescript(CREATE_TABLES_SQL)
        conn.commit()
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
        return conn.execute("SELECT changes()").fetchone()[0] > 0
    except sqlite3.Error as e:
        logger.error(f"Error inserting bot signal {signal.message_id}: {e}")
        return False


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
        return conn.execute("SELECT changes()").fetchone()[0] > 0
    except sqlite3.Error as e:
        logger.error(f"Error inserting IB report {report.message_id}: {e}")
        return False


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
        return conn.execute("SELECT changes()").fetchone()[0] > 0
    except sqlite3.Error as e:
        logger.error(f"Error inserting commentary {commentary.message_id}: {e}")
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
        return stats
