"""
Daily Discord intelligence digest generator.

Queries corey_session_bias, top bot signals, and discord_daily_sentiment
for a given date, and writes a structured JSON file.

Usage:
    python -m engine.discord.digest_generator --date 2026-05-05 --output data/discord-digests/2026-05-05.json
    python -m engine.discord.digest_generator  # defaults: yesterday, auto-resolved DB path
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
from datetime import date, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


def _default_db_path() -> str:
    # __file__ = engine/discord/digest_generator.py → up 3 levels → repo root
    engine_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    repo_root = os.path.dirname(engine_root)
    return os.path.join(repo_root, "data", "jarvis_trader.db")


def generate_digest(for_date: date, db_path: str) -> dict:
    """
    Build the daily digest dict for *for_date*.

    Returns a dict with: date, session_bias, sentiment_score, top_signals,
    corey_quote. Fields are None / [] when data is unavailable — callers must
    handle missing data gracefully.
    """
    date_str = for_date.isoformat()
    digest: dict = {
        "date": date_str,
        "session_bias": None,
        "sentiment_score": None,
        "sentiment_label": None,
        "top_signals": [],
        "corey_quote": None,
        "commentary_health": [],
    }

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row

        # Session bias (LLM-extracted by CoreyCommentaryProcessor)
        row = conn.execute(
            "SELECT * FROM corey_session_bias WHERE date = ?", (date_str,)
        ).fetchone()
        if row:
            digest["session_bias"] = {
                "session_type": row["session_type"],
                "directional_bias": row["directional_bias"],
                "conviction": row["conviction"],
                "ib_bias": row["ib_bias"],
                "data_quality": row["data_quality"],
                "message_count": row["message_count"],
            }
            digest["corey_quote"] = row["corey_quote"]

        # Daily sentiment score — table may not exist on older DBs
        try:
            sent_row = conn.execute(
                "SELECT sentiment_score FROM discord_daily_sentiment WHERE date = ?",
                (date_str,),
            ).fetchone()
            if sent_row:
                score = sent_row["sentiment_score"]
                digest["sentiment_score"] = score
                if score > 0.2:
                    digest["sentiment_label"] = "bullish"
                elif score < -0.2:
                    digest["sentiment_label"] = "bearish"
                else:
                    digest["sentiment_label"] = "neutral"
        except sqlite3.OperationalError:
            pass

        # Last 7 days of corey_session_bias as a pipeline health indicator.
        # Use this to quickly detect if the commentary processor has been
        # running (data_quality='fresh'/'stale') vs silently failing ('none').
        try:
            health_rows = conn.execute(
                """
                SELECT date, data_quality, directional_bias, conviction, message_count
                FROM corey_session_bias
                WHERE date >= DATE(?, '-7 days')
                ORDER BY date DESC
                """,
                (date_str,),
            ).fetchall()
            digest["commentary_health"] = [dict(row) for row in health_rows]
        except sqlite3.OperationalError:
            pass

        # Top 5 bot signals by win_rate for the day
        signals = conn.execute(
            """
            SELECT symbol, direction, signal_type, entry_price,
                   target1, target2, stop1, win_rate, rr, timestamp
            FROM discord_bot_signals
            WHERE DATE(timestamp) = ?
              AND signal_type = 'ENTRY'
              AND win_rate IS NOT NULL
            ORDER BY win_rate DESC
            LIMIT 5
            """,
            (date_str,),
        ).fetchall()
        digest["top_signals"] = [dict(row) for row in signals]

    return digest


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--date",
        default=None,
        help="YYYY-MM-DD (default: yesterday)",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="Path to SQLite DB (default: engine/data/jarvis_trader.db)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output JSON path (default: data/discord-digests/YYYY-MM-DD.json relative to repo root)",
    )
    args = parser.parse_args()

    for_date = date.fromisoformat(args.date) if args.date else date.today() - timedelta(days=1)
    db_path = args.db or _default_db_path()

    if args.output:
        output_path = Path(args.output)
    else:
        engine_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        repo_root = os.path.dirname(engine_root)
        output_path = Path(repo_root) / "data" / "discord-digests" / f"{for_date.isoformat()}.json"

    try:
        digest = generate_digest(for_date, db_path)
    except Exception as exc:
        logger.error("Digest generation failed for %s: %s", for_date, exc, exc_info=True)
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(digest, indent=2, default=str), encoding="utf-8")
    logger.info("Digest written to %s", output_path)

    # Log a one-line summary
    bias = digest.get("session_bias") or {}
    health_fresh = sum(
        1 for h in digest["commentary_health"] if h.get("data_quality") in ("fresh", "stale")
    )
    logger.info(
        "  %s | bias=%s conviction=%.2f | %d signals | sentiment=%s (%s) | health=%d/7d",
        for_date,
        bias.get("directional_bias", "n/a"),
        bias.get("conviction") or 0.0,
        len(digest["top_signals"]),
        f"{digest['sentiment_score']:.3f}" if digest["sentiment_score"] is not None else "n/a",
        digest["sentiment_label"] or "n/a",
        health_fresh,
    )
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
