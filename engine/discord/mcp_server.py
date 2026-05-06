"""
Discord Intelligence MCP Server — READ-ONLY

Wraps Discord intelligence queries so Claude Code sessions can ask:
  "What did Corey say about MES today?"
  "Show me recent ES signals from the last 4 hours"

Tools (all read-only, no DB writes):
  get_session_bias       — Corey's structured session bias for a trading date
  get_recent_signals     — Recent Discord bot signals for a symbol
  get_daily_sentiment    — Keyword-based daily sentiment score
  search_commentary      — Full-text search Corey's raw commentary

Run as MCP server:
  python -m discord.mcp_server
  python engine/discord/mcp_server.py
"""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import date as date_type, datetime, timedelta, timezone

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _default_db_path() -> str:
    """engine/data/jarvis_trader.db — anchored at engine/ root."""
    engine_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(engine_root, "data", "jarvis_trader.db")


def _parse_date(s: str) -> date_type:
    """Parse ISO date string; default to today if empty."""
    return date_type.fromisoformat(s) if s else date_type.today()


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

mcp = FastMCP("discord-intelligence")


@mcp.tool()
async def get_session_bias(date: str = "") -> dict:
    """
    Get Corey's structured session bias for a trading date.

    Args:
        date: ISO date string YYYY-MM-DD. Defaults to today.

    Returns dict with: date, session_type, directional_bias, key_levels,
        ib_bias, specific_triggers, conviction, corey_quote,
        message_count, data_quality
    """
    from discord.commentary_processor import CoreyCommentaryProcessor  # noqa: PLC0415

    parsed = _parse_date(date)
    processor = CoreyCommentaryProcessor()
    bias = await processor.get_session_bias(parsed)
    return bias.to_dict()


@mcp.tool()
async def get_recent_signals(symbol: str, hours: int = 4) -> list[dict]:
    """
    Get recent Discord bot signals for a symbol.

    Args:
        symbol: Trading symbol (ES, CL, NQ, GC, etc.)
        hours: Lookback window in hours (default 4)

    Returns list of signal dicts with: symbol, direction, signal_type,
        entry_price, target1, target2, stop1, win_rate, timestamp
    """
    sym = symbol.upper()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    db_path = _default_db_path()

    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT symbol, direction, signal_type, entry_price,
                       target1, target2, stop1, win_rate, timestamp
                FROM discord_bot_signals
                WHERE symbol = ? AND timestamp >= ?
                ORDER BY timestamp DESC
                LIMIT 10
                """,
                (sym, cutoff),
            ).fetchall()
        return [dict(row) for row in rows]
    except Exception as exc:
        logger.warning("[get_recent_signals] DB error for %s: %s", symbol, exc)
        return []


@mcp.tool()
async def get_daily_sentiment(date: str = "") -> dict:
    """
    Get keyword-based daily sentiment score from Corey's commentary.

    Args:
        date: ISO date YYYY-MM-DD. Defaults to today.

    Returns dict with: date, sentiment_score (-1.0 to +1.0),
        regime_multiplier, interpretation (bullish/bearish/neutral)
    """
    from discord.sentiment_provider import SentimentProvider  # noqa: PLC0415

    parsed = _parse_date(date)
    provider = SentimentProvider()
    score = provider.get_sentiment(parsed)
    multiplier = provider.get_regime_multiplier(parsed)

    if score > 0.2:
        interpretation = "bullish"
    elif score < -0.2:
        interpretation = "bearish"
    else:
        interpretation = "neutral"

    return {
        "date": parsed.isoformat(),
        "sentiment_score": score,
        "regime_multiplier": multiplier,
        "interpretation": interpretation,
    }


@mcp.tool()
async def search_commentary(query: str, days: int = 7) -> list[dict]:
    """
    Full-text search Corey's raw commentary for a keyword or phrase.

    Args:
        query: Search string (case-insensitive)
        days: How many days back to search (default 7)

    Returns list of matching messages: timestamp, content, channel
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    db_path = _default_db_path()

    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            try:
                # FTS5 MATCH is 10–100× faster than LIKE on 280K+ rows.
                # Falls back to LIKE if the FTS table doesn't exist yet or
                # if the query contains FTS5 syntax that doesn't parse.
                rows = conn.execute(
                    """
                    SELECT c.timestamp, c.content, c.channel
                    FROM discord_corey_commentary c
                    JOIN discord_commentary_fts fts ON fts.rowid = c.id
                    WHERE discord_commentary_fts MATCH ?
                      AND c.timestamp >= ?
                    ORDER BY c.timestamp DESC
                    LIMIT 20
                    """,
                    (query, cutoff),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = conn.execute(
                    """
                    SELECT timestamp, content, channel
                    FROM discord_corey_commentary
                    WHERE content LIKE ? AND timestamp >= ?
                    ORDER BY timestamp DESC
                    LIMIT 20
                    """,
                    (f"%{query}%", cutoff),
                ).fetchall()
        return [dict(row) for row in rows]
    except Exception as exc:
        logger.warning("[search_commentary] DB error for %r: %s", query, exc)
        return []


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
