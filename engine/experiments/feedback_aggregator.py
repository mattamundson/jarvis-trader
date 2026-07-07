"""MES forward-recorder feedback aggregator.

Reads ``mes_session_hypothesis`` rows written by ``mes_session_recorder``
(morning pass) + ``mes_session_outcome`` (afternoon pass) and exposes
two small query helpers:

    get_recent_hit_rate(n=10, max_age_days=7) -> tuple[Optional[float], int]
        Hit rate = fraction of non-skip hypotheses where outcome_delta > 0.
        Returns (None, 0) on empty history — caller should NOT treat this
        as a real 0.0 hit rate.

    get_last_session_hypothesis() -> Optional[dict]
        Most recent hypothesis row (any symbol, any state). Returns the
        raw recorded values — caller decides whether a NULL
        outcome_recorded_at means "pending" or "ignore".

Design notes
------------
* "skip" hypotheses are EXCLUDED from hit-rate math. A skip is "we took
  no position", so it neither hit nor missed — folding it in either
  direction would bias the metric.
* ``max_age_days`` defaults to 7. Outcomes older than that are excluded
  because the regime may have shifted. If fewer than ``n`` fresh
  outcomes exist, we compute over whatever is available and return the
  sample count so the caller can weight the signal appropriately.
* No writes. No side effects. Callable from any layer.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = str(Path(__file__).resolve().parents[1] / "data" / "jarvis_trader.db")


def _table_exists(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name='mes_session_hypothesis'"
    ).fetchone()
    return row is not None


def get_recent_hit_rate(
    n: int = 10,
    max_age_days: int = 7,
    db_path: str = DEFAULT_DB_PATH,
    today: Optional[date] = None,
) -> tuple[Optional[float], int]:
    """Return ``(hit_rate, num_samples)`` over the last ``n`` non-skip outcomes.

    ``hit_rate`` is None when no qualifying rows exist — a real 0.0
    means "every bet lost" and should not be confused with "no data".
    ``num_samples`` is the count of rows actually used in the fraction.
    """
    cutoff = (today or date.today()) - timedelta(days=max_age_days)

    try:
        with sqlite3.connect(db_path) as conn:
            if not _table_exists(conn):
                logger.info("[FeedbackAggregator] hypothesis table missing — returning None")
                return None, 0
            rows = conn.execute(
                """
                SELECT entry_hypothesis_side, outcome_delta
                  FROM mes_session_hypothesis
                 WHERE outcome_recorded_at IS NOT NULL
                   AND entry_hypothesis_side IN ('long', 'short')
                   AND date >= ?
                 ORDER BY date DESC
                 LIMIT ?
                """,
                (cutoff.isoformat(), n),
            ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("[FeedbackAggregator] SQL error reading hypotheses: %s", exc)
        return None, 0

    if not rows:
        return None, 0

    hits = 0
    samples = 0
    for _side, delta in rows:
        if delta is None:
            continue
        samples += 1
        if delta > 0:
            hits += 1

    if samples == 0:
        return None, 0

    return hits / samples, samples


def get_last_session_hypothesis(
    db_path: str = DEFAULT_DB_PATH,
) -> Optional[dict]:
    """Return the most recently recorded hypothesis row as a dict, or None.

    Includes pending rows (no outcome yet) — the caller decides how to
    treat ``outcome_recorded_at=None``.
    """
    try:
        with sqlite3.connect(db_path) as conn:
            if not _table_exists(conn):
                return None
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT date, symbol, entry_hypothesis_side,
                       entry_hypothesis_reason, open_price, close_price,
                       outcome_delta, outcome_recorded_at
                  FROM mes_session_hypothesis
                 ORDER BY date DESC
                 LIMIT 1
                """
            ).fetchone()
    except sqlite3.Error as exc:
        logger.warning("[FeedbackAggregator] SQL error reading last hypothesis: %s", exc)
        return None

    return dict(row) if row is not None else None
