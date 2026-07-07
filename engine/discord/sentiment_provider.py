# engine/discord/sentiment_provider.py
#
# SentimentProvider — keyword-based daily sentiment scoring from discord_corey_commentary
#
# Scores each message using bullish/bearish/caution keyword counts, stores results
# in discord_daily_sentiment table for fast cached lookup.
#
# Usage:
#   provider = SentimentProvider()
#   score = provider.get_sentiment(date.today())        # cached lookup
#   mult  = provider.get_regime_multiplier(date.today()) # (1.0 + 0.3 * score)
#
# CLI:
#   python -m discord.sentiment_provider           # show last 7 days
#   python -m discord.sentiment_provider --etl    # compute + store all dates

import logging
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Keyword lists
# ---------------------------------------------------------------------------

BULLISH_KEYWORDS = [
    "long",
    "buy",
    "support",
    "breakout",
    "squeeze",
    "auction higher",
    "accepting",
    "initiative buying",
    "demand zone",
    "above poc",
    "above val",
    "buyers",
    "bid",
    "strong",
    "bounce",
    "recovery",
    "upside",
]

BEARISH_KEYWORDS = [
    "short",
    "sell",
    "resistance",
    "breakdown",
    "distribution",
    "auction lower",
    "rejecting",
    "initiative selling",
    "supply zone",
    "below poc",
    "below vah",
    "sellers",
    "offer",
    "weak",
    "fade",
    "downside",
]

CAUTION_KEYWORDS = [
    "choppy",
    "balanced",
    "inside",
    "wait",
    "no trade",
    "avoid",
    "tight",
    "holiday",
    "news",
    "fomc",
    "cpi",
    "jobs",
    "chop",
    "sideways",
    "range bound",
    "unclear",
    "patience",
]

# ---------------------------------------------------------------------------
# Table DDL
# ---------------------------------------------------------------------------

CREATE_SENTIMENT_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS discord_daily_sentiment (
    date TEXT NOT NULL,
    sentiment_score REAL NOT NULL,
    post_count INTEGER NOT NULL,
    source TEXT DEFAULT 'discord_corey_commentary',
    computed_at TEXT NOT NULL,
    PRIMARY KEY (date)
)
"""


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _get_db_path() -> str:
    """
    Resolve path to jarvis_trader.db at engine/data/jarvis_trader.db.
    Anchored at engine/ root (two levels up from this file), not walking
    all parents — the previous walk-up-until-found strategy would match
    the stray workspace-root data/jarvis_trader.db first on machines where
    both exist, causing a split-brain DB (2026-04-10 fix).
    """
    here = Path(__file__).resolve()
    engine_root = here.parent.parent  # engine/discord/sentiment_provider.py → engine/
    canonical = engine_root / "data" / "jarvis_trader.db"
    if canonical.exists():
        return str(canonical)
    raise FileNotFoundError(
        f"Cannot find canonical DB at {canonical} — check engine/data/ directory"
    )


def score_message(content: str) -> float:
    """
    Score a single message string using keyword matching.

    Algorithm:
        score = (bullish_count - bearish_count) /
                max(1, bullish_count + bearish_count + caution_count * 0.5)

    Returns 0.0 if no keywords are found.
    Result is clamped to [-1.0, 1.0].
    """
    text = content.lower()

    bullish_count = sum(1 for kw in BULLISH_KEYWORDS if kw in text)
    bearish_count = sum(1 for kw in BEARISH_KEYWORDS if kw in text)
    caution_count = sum(1 for kw in CAUTION_KEYWORDS if kw in text)

    total = bullish_count + bearish_count + caution_count
    if total == 0:
        return 0.0

    denominator = max(1, bullish_count + bearish_count + caution_count * 0.5)
    raw = (bullish_count - bearish_count) / denominator
    return max(-1.0, min(1.0, raw))


# ---------------------------------------------------------------------------
# SentimentProvider
# ---------------------------------------------------------------------------


class SentimentProvider:
    """
    Provides daily sentiment scores derived from discord_corey_commentary.

    Scores are cached in discord_daily_sentiment for fast repeated lookups.
    Use run_etl() to pre-populate the cache for a full date range.
    Use get_sentiment() for on-demand lookup with automatic fallback to
    live computation when the cache misses.
    """

    def __init__(self, db_path: str = None):
        """
        Args:
            db_path: Path to jarvis_trader.db. If None, auto-resolved via
                     _get_db_path() which walks parent directories.
        """
        if db_path is None:
            db_path = _get_db_path()
        self.db_path = db_path
        self._ensure_table()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_table(self) -> None:
        """Create discord_daily_sentiment table if it does not exist."""
        with self._connect() as conn:
            conn.execute(CREATE_SENTIMENT_TABLE_SQL)
            conn.commit()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute_daily_sentiment(self, trading_date: date) -> float:
        """
        Score all commentary messages from the given trading_date.

        Queries discord_corey_commentary WHERE DATE(timestamp) = trading_date,
        scores each row's content with score_message(), and returns the mean.

        Returns:
            Average sentiment score in [-1.0, 1.0].
            Returns 0.0 if no messages are found for the date.
        """
        date_str = trading_date.isoformat()
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT content
                    FROM discord_corey_commentary
                    WHERE DATE(timestamp) = ?
                    """,
                    (date_str,),
                ).fetchall()
        except sqlite3.Error as e:
            logger.error(f"[SentimentProvider] DB error querying {date_str}: {e}")
            return 0.0

        if not rows:
            return 0.0

        scores: List[float] = []
        for row in rows:
            content = row["content"]
            if not content:
                continue
            try:
                scores.append(score_message(content))
            except Exception as e:
                logger.warning(f"[SentimentProvider] score_message failed: {e}")

        if not scores:
            return 0.0

        return sum(scores) / len(scores)

    def get_sentiment(self, trading_date) -> float:
        """
        Returns sentiment score for a trading day.

        Checks discord_daily_sentiment table first (cache hit).
        Falls back to compute_daily_sentiment() if not found in cache.

        Args:
            trading_date: A date object or ISO-format string ('YYYY-MM-DD').

        Returns:
            Sentiment score in [-1.0, 1.0].
        """
        if isinstance(trading_date, str):
            trading_date = date.fromisoformat(trading_date)
        date_str = trading_date.isoformat()

        # Try cache first
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT sentiment_score FROM discord_daily_sentiment WHERE date = ?",
                    (date_str,),
                ).fetchone()
            if row is not None:
                return float(row["sentiment_score"])
        except sqlite3.Error as e:
            logger.warning(f"[SentimentProvider] Cache lookup failed for {date_str}: {e}")

        # Cache miss — compute live
        return self.compute_daily_sentiment(trading_date)

    def run_etl(self, start_date: date = None, end_date: date = None) -> None:
        """
        Compute and store daily sentiment scores for a date range.

        Idempotent — uses INSERT OR REPLACE so re-running overwrites stale values.

        Args:
            start_date: First date to process. Defaults to earliest date in
                        discord_corey_commentary.
            end_date:   Last date to process. Defaults to today.
        """
        self._ensure_table()

        # Resolve start_date
        if start_date is None:
            try:
                with self._connect() as conn:
                    row = conn.execute(
                        "SELECT MIN(DATE(timestamp)) FROM discord_corey_commentary"
                    ).fetchone()
                if row and row[0]:
                    start_date = date.fromisoformat(row[0])
                else:
                    logger.warning(
                        "[SentimentProvider] No rows in discord_corey_commentary — ETL skipped."
                    )
                    return
            except sqlite3.Error as e:
                logger.error(f"[SentimentProvider] Cannot determine start_date: {e}")
                return

        if end_date is None:
            end_date = date.today()

        # Collect all distinct dates that have commentary in range
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT DISTINCT DATE(timestamp) AS d
                    FROM discord_corey_commentary
                    WHERE DATE(timestamp) BETWEEN ? AND ?
                    ORDER BY d
                    """,
                    (start_date.isoformat(), end_date.isoformat()),
                ).fetchall()
        except sqlite3.Error as e:
            logger.error(f"[SentimentProvider] ETL date query failed: {e}")
            return

        dates_with_data = [row["d"] for row in rows if row["d"]]
        total = len(dates_with_data)
        logger.info(
            f"[SentimentProvider] ETL processing {total} dates from {start_date} to {end_date}"
        )

        processed = 0
        for date_str in dates_with_data:
            try:
                d = date.fromisoformat(date_str)
            except ValueError as e:
                logger.warning(f"[SentimentProvider] Bad date string '{date_str}': {e}")
                continue

            score = self.compute_daily_sentiment(d)
            post_count = self._count_posts_for_date(d)
            computed_at = datetime.utcnow().isoformat()

            try:
                with self._connect() as conn:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO discord_daily_sentiment
                            (date, sentiment_score, post_count, source, computed_at)
                        VALUES (?, ?, ?, 'discord_corey_commentary', ?)
                        """,
                        (date_str, score, post_count, computed_at),
                    )
                    conn.commit()
            except sqlite3.Error as e:
                logger.error(f"[SentimentProvider] Insert failed for {date_str}: {e}")
                continue

            processed += 1
            if processed % 50 == 0:
                logger.info(f"[SentimentProvider] ETL progress: {processed}/{total}")

        logger.info(f"[SentimentProvider] ETL complete: {processed}/{total} dates stored.")

    def _count_posts_for_date(self, trading_date: date) -> int:
        """Return number of commentary rows for the given date."""
        date_str = trading_date.isoformat()
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) FROM discord_corey_commentary WHERE DATE(timestamp) = ?",
                    (date_str,),
                ).fetchone()
            return int(row[0]) if row else 0
        except sqlite3.Error:
            return 0

    def get_regime_multiplier(self, trading_date) -> float:
        """
        Returns a regime confidence multiplier based on daily sentiment.

        Formula: 1.0 + 0.3 * sentiment_score
        Range:   [0.7, 1.3]

        A bullish day (+1.0 score) -> multiplier 1.3 (boost regime confidence).
        A bearish day (-1.0 score) -> multiplier 0.7 (reduce regime confidence).
        A neutral day (0.0 score)  -> multiplier 1.0 (no adjustment).

        Args:
            trading_date: A date object or ISO-format string ('YYYY-MM-DD').
        """
        if isinstance(trading_date, str):
            trading_date = date.fromisoformat(trading_date)
        score = self.get_sentiment(trading_date)
        return 1.0 + 0.3 * score


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    provider = SentimentProvider()

    if "--etl" in sys.argv:
        print("Running full sentiment ETL...")
        provider.run_etl()
        print("ETL complete.")
    else:
        # Print last 7 days of sentiment
        today = date.today()
        print("Last 7 trading days sentiment:")
        for i in range(7, 0, -1):
            d = today - timedelta(days=i)
            score = provider.get_sentiment(d)
            mult = provider.get_regime_multiplier(d)
            print(f"  {d}: score={score:+.3f}, multiplier={mult:.3f}")
