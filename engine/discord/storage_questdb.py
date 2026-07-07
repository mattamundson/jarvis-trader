"""QuestDB shadow-write layer for Discord time-series tables.

This module is a SCAFFOLD — it does not replace the SQLite primary path.
When ENABLE_QUESTDB_DUAL_WRITE=1, new Discord ingest writes also land in
QuestDB for time-range aggregate workloads (10-100x faster than SQLite).
Reads remain on SQLite until a future cut-over PR flips the flag.

Design contract:
  - All public insert_* functions are NO-OPs when dual-write is disabled.
  - On any QuestDB error: log WARNING, return None, never raise.
  - The SQLite write path is never blocked or delayed by this module.

QuestDB HTTP exec endpoint: http://{QUESTDB_HOST}:{QUESTDB_PORT}/exec
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy client cache — one httpx.Client per process
# ---------------------------------------------------------------------------
_client: Optional[object] = None  # httpx.Client, typed as object to avoid import at module level

# DDL for each shadow table (timestamp column is the designated TS, partitioned by DAY).
_DDL_BOT_SIGNALS = """
CREATE TABLE IF NOT EXISTS discord_bot_signals_ts (
    ts TIMESTAMP,
    message_id SYMBOL,
    symbol SYMBOL,
    timeframe SYMBOL,
    direction SYMBOL,
    signal_type SYMBOL,
    entry_price DOUBLE,
    target1 DOUBLE,
    target2 DOUBLE,
    stop1 DOUBLE,
    stop2 DOUBLE,
    win_rate DOUBLE,
    wins INT,
    losses INT,
    mfe DOUBLE,
    mae DOUBLE,
    rr DOUBLE,
    gain DOUBLE,
    draw DOUBLE,
    net DOUBLE,
    last_price DOUBLE,
    source_channel SYMBOL
) timestamp(ts) PARTITION BY DAY;
"""

_DDL_COREY_COMMENTARY = """
CREATE TABLE IF NOT EXISTS discord_corey_commentary_ts (
    ts TIMESTAMP,
    message_id SYMBOL,
    content STRING,
    channel SYMBOL,
    author_id SYMBOL
) timestamp(ts) PARTITION BY DAY;
"""

_DDL_IB_REPORTS = """
CREATE TABLE IF NOT EXISTS discord_ib_reports_ts (
    ts TIMESTAMP,
    message_id SYMBOL,
    symbol SYMBOL,
    timeframe SYMBOL,
    ib_open DOUBLE,
    ib_high DOUBLE,
    ib_low DOUBLE,
    ib_close DOUBLE,
    ib_range DOUBLE,
    ibu50 DOUBLE,
    ibu100 DOUBLE,
    ibd50 DOUBLE,
    ibd100 DOUBLE,
    auction_context SYMBOL,
    source_channel SYMBOL
) timestamp(ts) PARTITION BY DAY;
"""

_DDL_DAILY_SENTIMENT = """
CREATE TABLE IF NOT EXISTS discord_daily_sentiment_ts (
    ts TIMESTAMP,
    date_key SYMBOL,
    sentiment_score DOUBLE,
    post_count INT,
    source SYMBOL,
    computed_at TIMESTAMP
) timestamp(ts) PARTITION BY DAY;
"""

# Track which tables have been ensured this process lifetime to avoid
# redundant DDL calls on every insert.
_tables_ensured: set[str] = set()


# ---------------------------------------------------------------------------
# Public feature-flag helper
# ---------------------------------------------------------------------------


def is_questdb_dual_write_enabled() -> bool:
    """Return True when ENABLE_QUESTDB_DUAL_WRITE env var is set to '1'.

    Reads the environment fresh on every call so the flag can be toggled
    without restarting the process (useful in tests via monkeypatch).
    """
    return os.environ.get("ENABLE_QUESTDB_DUAL_WRITE", "0").strip() == "1"


# ---------------------------------------------------------------------------
# Lazy httpx client
# ---------------------------------------------------------------------------


def _get_questdb_client():
    """Return a cached httpx.Client configured for the QuestDB exec endpoint.

    Lazy-initialised on first use so the import cost is zero when dual-write
    is disabled.  The client is intentionally not thread-safe across the lazy
    init, but that is acceptable: worst case two clients are created and one
    is GC'd.
    """
    global _client
    if _client is None:
        import httpx  # lazy import — not installed as new dep, already in venv

        host = os.environ.get("QUESTDB_HOST", "localhost")
        port = os.environ.get("QUESTDB_PORT", "9000")
        base_url = f"http://{host}:{port}"
        _client = httpx.Client(base_url=base_url, timeout=5.0)
        logger.debug("QuestDB httpx client initialised at %s", base_url)
    return _client


# ---------------------------------------------------------------------------
# DDL helper
# ---------------------------------------------------------------------------


def _ensure_table_exists(client, table_name: str, table_sql: str) -> None:
    """Run DDL idempotently via QuestDB /exec endpoint.

    Cached per process so repeated inserts do not re-run DDL.
    Errors are logged as WARNING and swallowed — the SQLite path is unaffected.
    """
    if table_name in _tables_ensured:
        return
    try:
        resp = client.get("/exec", params={"query": table_sql.strip()})
        resp.raise_for_status()
        _tables_ensured.add(table_name)
        logger.debug("QuestDB table ensured: %s", table_name)
    except Exception as exc:
        logger.warning("QuestDB DDL failed for %s: %s", table_name, exc)


# ---------------------------------------------------------------------------
# SQL escaping helper
# ---------------------------------------------------------------------------


def _esc(value) -> str:
    """Escape a value for embedding in a QuestDB SQL literal.

    QuestDB does not support parameterised queries over the HTTP exec endpoint,
    so we build inline SQL.  String values are single-quoted with internal
    single-quotes escaped.  None becomes NULL.  Numbers are converted directly.
    """
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    # String — escape single quotes, wrap in quotes
    escaped = str(value).replace("'", "''")
    return f"'{escaped}'"


def _ts_literal(iso_str: Optional[str]) -> str:
    """Convert an ISO-8601 string to a QuestDB timestamp literal, or NULL."""
    if not iso_str:
        return "NULL"
    # QuestDB accepts 'YYYY-MM-DDTHH:MM:SS.SSSZ' format directly
    cleaned = iso_str.replace("Z", "").strip()
    # Normalise to microsecond precision QuestDB expects
    if "." not in cleaned:
        cleaned = cleaned + ".000000"
    return f"'{cleaned}'"


# ---------------------------------------------------------------------------
# Public insert functions — shadow of storage.py insert_* functions
# ---------------------------------------------------------------------------


def insert_bot_signal_ts(signal) -> None:
    """Shadow-write a BotSignal to discord_bot_signals_ts in QuestDB.

    NO-OP when dual-write is disabled.  Returns None always (never raises).
    """
    if not is_questdb_dual_write_enabled():
        logger.debug("QuestDB dual-write disabled; skipping insert_bot_signal_ts")
        return
    try:
        client = _get_questdb_client()
        _ensure_table_exists(client, "discord_bot_signals_ts", _DDL_BOT_SIGNALS)
        sql = (
            "INSERT INTO discord_bot_signals_ts "
            "(ts, message_id, symbol, timeframe, direction, signal_type, "
            "entry_price, target1, target2, stop1, stop2, win_rate, wins, losses, "
            "mfe, mae, rr, gain, draw, net, last_price, source_channel) "
            f"VALUES ("
            f"{_ts_literal(signal.timestamp)}, "
            f"{_esc(signal.message_id)}, "
            f"{_esc(signal.symbol)}, "
            f"{_esc(signal.timeframe)}, "
            f"{_esc(signal.direction)}, "
            f"{_esc(signal.signal_type)}, "
            f"{_esc(signal.entry_price)}, "
            f"{_esc(signal.target1)}, "
            f"{_esc(signal.target2)}, "
            f"{_esc(signal.stop1)}, "
            f"{_esc(signal.stop2)}, "
            f"{_esc(signal.win_rate)}, "
            f"{_esc(signal.wins)}, "
            f"{_esc(signal.losses)}, "
            f"{_esc(signal.mfe)}, "
            f"{_esc(signal.mae)}, "
            f"{_esc(signal.rr)}, "
            f"{_esc(signal.gain)}, "
            f"{_esc(signal.draw)}, "
            f"{_esc(signal.net)}, "
            f"{_esc(signal.last_price)}, "
            f"{_esc(signal.source_channel)}"
            ");"
        )
        resp = client.get("/exec", params={"query": sql})
        resp.raise_for_status()
        logger.debug("QuestDB: inserted bot signal %s", signal.message_id)
    except Exception as exc:
        logger.warning(
            "QuestDB insert_bot_signal_ts failed for message_id=%s: %s",
            getattr(signal, "message_id", "?"),
            exc,
        )


def insert_corey_commentary_ts(commentary) -> None:
    """Shadow-write a CoreyCommentary to discord_corey_commentary_ts in QuestDB.

    NO-OP when dual-write is disabled.  Returns None always (never raises).
    """
    if not is_questdb_dual_write_enabled():
        logger.debug("QuestDB dual-write disabled; skipping insert_corey_commentary_ts")
        return
    try:
        client = _get_questdb_client()
        _ensure_table_exists(client, "discord_corey_commentary_ts", _DDL_COREY_COMMENTARY)
        sql = (
            "INSERT INTO discord_corey_commentary_ts "
            "(ts, message_id, content, channel, author_id) "
            f"VALUES ("
            f"{_ts_literal(commentary.timestamp)}, "
            f"{_esc(commentary.message_id)}, "
            f"{_esc(commentary.content)}, "
            f"{_esc(commentary.channel)}, "
            f"{_esc(commentary.author_id)}"
            ");"
        )
        resp = client.get("/exec", params={"query": sql})
        resp.raise_for_status()
        logger.debug("QuestDB: inserted corey commentary %s", commentary.message_id)
    except Exception as exc:
        logger.warning(
            "QuestDB insert_corey_commentary_ts failed for message_id=%s: %s",
            getattr(commentary, "message_id", "?"),
            exc,
        )


def insert_ib_report_ts(report) -> None:
    """Shadow-write an IBReport to discord_ib_reports_ts in QuestDB.

    NO-OP when dual-write is disabled.  Returns None always (never raises).
    """
    if not is_questdb_dual_write_enabled():
        logger.debug("QuestDB dual-write disabled; skipping insert_ib_report_ts")
        return
    try:
        client = _get_questdb_client()
        _ensure_table_exists(client, "discord_ib_reports_ts", _DDL_IB_REPORTS)
        sql = (
            "INSERT INTO discord_ib_reports_ts "
            "(ts, message_id, symbol, timeframe, ib_open, ib_high, ib_low, "
            "ib_close, ib_range, ibu50, ibu100, ibd50, ibd100, auction_context, source_channel) "
            f"VALUES ("
            f"{_ts_literal(report.timestamp)}, "
            f"{_esc(report.message_id)}, "
            f"{_esc(report.symbol)}, "
            f"{_esc(report.timeframe)}, "
            f"{_esc(report.ib_open)}, "
            f"{_esc(report.ib_high)}, "
            f"{_esc(report.ib_low)}, "
            f"{_esc(report.ib_close)}, "
            f"{_esc(report.ib_range)}, "
            f"{_esc(report.ibu50)}, "
            f"{_esc(report.ibu100)}, "
            f"{_esc(report.ibd50)}, "
            f"{_esc(report.ibd100)}, "
            f"{_esc(report.auction_context)}, "
            f"{_esc(report.source_channel)}"
            ");"
        )
        resp = client.get("/exec", params={"query": sql})
        resp.raise_for_status()
        logger.debug("QuestDB: inserted IB report %s", report.message_id)
    except Exception as exc:
        logger.warning(
            "QuestDB insert_ib_report_ts failed for message_id=%s: %s",
            getattr(report, "message_id", "?"),
            exc,
        )


def insert_daily_sentiment_ts(
    date_key: str, sentiment_score: float, post_count: int, source: str, computed_at: str
) -> None:
    """Shadow-write a daily sentiment row to discord_daily_sentiment_ts in QuestDB.

    NO-OP when dual-write is disabled.  Returns None always (never raises).
    """
    if not is_questdb_dual_write_enabled():
        logger.debug("QuestDB dual-write disabled; skipping insert_daily_sentiment_ts")
        return
    try:
        client = _get_questdb_client()
        _ensure_table_exists(client, "discord_daily_sentiment_ts", _DDL_DAILY_SENTIMENT)
        # ts is the start of the date (midnight UTC)
        ts_value = f"{date_key}T00:00:00.000000" if date_key else None
        sql = (
            "INSERT INTO discord_daily_sentiment_ts "
            "(ts, date_key, sentiment_score, post_count, source, computed_at) "
            f"VALUES ("
            f"{_ts_literal(ts_value)}, "
            f"{_esc(date_key)}, "
            f"{_esc(sentiment_score)}, "
            f"{_esc(post_count)}, "
            f"{_esc(source)}, "
            f"{_ts_literal(computed_at)}"
            ");"
        )
        resp = client.get("/exec", params={"query": sql})
        resp.raise_for_status()
        logger.debug("QuestDB: inserted daily sentiment for %s", date_key)
    except Exception as exc:
        logger.warning(
            "QuestDB insert_daily_sentiment_ts failed for date=%s: %s",
            date_key,
            exc,
        )


# ---------------------------------------------------------------------------
# Client reset helper (for testing)
# ---------------------------------------------------------------------------


def _reset_client() -> None:
    """Reset the cached httpx client and table-ensured set.  Test use only."""
    global _client, _tables_ensured
    if _client is not None:
        try:
            _client.close()
        except Exception:
            pass
        _client = None
    _tables_ensured = set()
