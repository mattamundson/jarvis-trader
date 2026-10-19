"""
MES session hypothesis forward-recorder (afternoon pass).

Runs at 15:15 CT each weekday, 15 minutes after RTH close. Reads the
``mes_session_hypothesis`` rows written by the morning pass that still
have a NULL ``outcome_recorded_at`` and fills in:

* ``high_price`` — session high (max of bars from 08:30 CT to 15:00 CT)
* ``low_price``  — session low
* ``close_price`` — 15:00 CT close (or last available bar)
* ``outcome_delta`` — signed return in points:
    * long hypothesis → close - open
    * short hypothesis → open - close
    * skip hypothesis → 0.0 (no position would have been taken)
* ``outcome_recorded_at`` — UTC ISO-8601 timestamp

Idempotent: rows with a non-NULL ``outcome_recorded_at`` are skipped. A
manual force-refresh is a direct UPDATE, never via this job, to keep the
outcome column an immutable audit trail of what the recorder saw on the
day of record.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

from experiments.es_read_engine import READ_SYMBOL, score_reads

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = str(Path(__file__).resolve().parents[1] / "data" / "jarvis_trader.db")


# ── Internal helpers ─────────────────────────────────────────────────────────


def _hlc_from_bars(bars: Any) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Return (high, low, close) from a pandas DataFrame of bars, or Nones."""
    if bars is None:
        return None, None, None
    try:
        if hasattr(bars, "empty") and bars.empty:
            return None, None, None
        high = float(bars["high"].max()) if "high" in bars else None
        low = float(bars["low"].min()) if "low" in bars else None
        close = float(bars["close"].iloc[-1]) if "close" in bars else None
        return high, low, close
    except Exception as exc:  # pragma: no cover — defensive only
        logger.warning("[MESOutcome] _hlc_from_bars failed: %s", exc)
        return None, None, None


def _compute_delta(side: Optional[str], open_price: Optional[float], close: Optional[float]) -> Optional[float]:
    """Compute signed return in points for the hypothesis.

    Returns None when open_price or close is missing. Returns 0.0 for a
    "skip" hypothesis — that's the meaningful value (no position taken).
    """
    if side == "skip":
        return 0.0
    if open_price is None or close is None:
        return None
    if side == "long":
        return float(close - open_price)
    if side == "short":
        return float(open_price - close)
    return None


async def _score_es_read(result: "OutcomeResult", for_date, db_path, data_manager, bars_fn) -> None:
    """Score the ES read row for the day. Its 5-minute scoring lives in es_read_engine."""
    try:
        summary = await score_reads(
            for_date=for_date, db_path=db_path, data_manager=data_manager, bars_fn=bars_fn
        )
        result.updated_rows += summary.get("updated_rows", 0)
        result.skipped_no_data += summary.get("skipped_no_data", 0)
        result.errors.extend(f"es_read:{e}" for e in summary.get("errors", []))
    except Exception as exc:  # pragma: no cover - scorer does not raise
        result.errors.append(f"es_read_failed:{type(exc).__name__}")


# ── Public entry point ────────────────────────────────────────────────────────


@dataclass
class OutcomeResult:
    updated_rows: int = 0
    skipped_existing: int = 0
    skipped_no_data: int = 0
    errors: list[str] = None

    def __post_init__(self) -> None:
        if self.errors is None:
            self.errors = []

    def to_dict(self) -> dict:
        return {
            "updated_rows": self.updated_rows,
            "skipped_existing": self.skipped_existing,
            "skipped_no_data": self.skipped_no_data,
            "errors": list(self.errors),
        }


async def fill_outcomes(
    *,
    for_date: Optional[date] = None,
    db_path: str = DEFAULT_DB_PATH,
    data_manager: Any = None,
    bars_fn: Any = None,
    score_es_read: bool = True,
) -> OutcomeResult:
    """Fill outcome columns for hypothesis rows missing them.

    If ``for_date`` is None, targets all rows with NULL ``outcome_recorded_at``
    — normally this means today's row, but if yesterday's outcome job missed,
    it backfills automatically.

    ``bars_fn`` is an optional injection for testing: ``await bars_fn(symbol)``
    must return an object with ``high``/``low``/``close`` columns. In
    production we use ``data_manager.get_bars(symbol, timeframe='1h',
    lookback_days=1)``.
    """
    result = OutcomeResult()

    # Fetch pending rows
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        if for_date is not None:
            rows = conn.execute(
                "SELECT id, date, symbol, entry_hypothesis_side, open_price, "
                "outcome_recorded_at FROM mes_session_hypothesis "
                "WHERE date = ? AND symbol != ?",
                (for_date.isoformat(), READ_SYMBOL),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, date, symbol, entry_hypothesis_side, open_price, "
                "outcome_recorded_at FROM mes_session_hypothesis "
                "WHERE outcome_recorded_at IS NULL AND symbol != ?",
                (READ_SYMBOL,),
            ).fetchall()

    if score_es_read:
        await _score_es_read(result, for_date, db_path, data_manager, bars_fn)

    if not rows:
        logger.info("[MESOutcome] no rows need outcome fills")
        return result

    today_iso = (for_date or date.today()).isoformat()
    for row in rows:
        if row["outcome_recorded_at"]:
            result.skipped_existing += 1
            continue

        # Cross-day backfill guard: `lookback_days=1` returns bars for the
        # current session only, so assigning that close to an older row's
        # open yields a multi-day delta instead of the 1-day-hypothesis
        # delta we meant to record. Skip stale rows rather than mis-label
        # them; they stay NULL and are dropped from the hit-rate sample.
        if for_date is None and row["date"] != today_iso:
            logger.info(
                "[MESOutcome] skipping stale row %s/%s — cross-day close "
                "would distort outcome_delta; leaving NULL",
                row["date"], row["symbol"],
            )
            result.skipped_no_data += 1
            continue

        symbol = row["symbol"]
        side = row["entry_hypothesis_side"]
        open_price = row["open_price"]

        # Fetch bars — either via injected bars_fn (tests) or data_manager
        bars = None
        try:
            if bars_fn is not None:
                bars = await bars_fn(symbol)
            elif data_manager is not None:
                bars = await data_manager.get_bars(symbol, lookback_days=1, timeframe="1h")
        except Exception as exc:
            logger.warning("[MESOutcome] bars fetch failed for %s/%s: %s", row["date"], symbol, exc)
            result.errors.append(f"bars_failed:{row['date']}:{type(exc).__name__}")

        high, low, close = _hlc_from_bars(bars)
        if high is None and low is None and close is None:
            result.skipped_no_data += 1
            logger.info("[MESOutcome] no bars for %s/%s — will retry next run", row["date"], symbol)
            continue

        delta = _compute_delta(side, open_price, close)

        with sqlite3.connect(db_path) as conn:
            reason_row = conn.execute(
                "SELECT entry_hypothesis_reason FROM mes_session_hypothesis "
                "WHERE id = ?",
                (row["id"],),
            ).fetchone()
            conn.execute(
                """
                UPDATE mes_session_hypothesis
                   SET high_price = ?, low_price = ?, close_price = ?,
                       outcome_delta = ?, outcome_recorded_at = ?
                 WHERE id = ? AND outcome_recorded_at IS NULL
                """,
                (
                    high,
                    low,
                    close,
                    delta,
                    datetime.now(tz=timezone.utc).isoformat(),
                    row["id"],
                ),
            )
            conn.commit()
        result.updated_rows += 1
        logger.info(
            "[MESOutcome] filled %s/%s side=%s open=%s close=%s delta=%s",
            row["date"],
            symbol,
            side,
            open_price,
            close,
            delta,
        )

        # Fire-and-forget Discord embed so every outcome is visible same-day
        try:
            from notifications.discord_notifier import discord_mes_forward_outcome
            await discord_mes_forward_outcome(
                date_str=row["date"],
                side=side or "skip",
                reason=reason_row[0] if reason_row else "",
                open_price=open_price,
                close_price=close,
                outcome_delta=delta,
            )
        except Exception as exc:  # pragma: no cover — notifier must never block
            logger.warning("[MESOutcome] discord notify failed: %s", exc)

    return result


# ── CLI entry ────────────────────────────────────────────────────────────────


async def _cli_main(argv: list[str]) -> int:
    # Optional date arg: YYYY-MM-DD
    for_date = None
    if len(argv) > 1:
        for_date = date.fromisoformat(argv[1])
    result = await fill_outcomes(for_date=for_date)
    print(json.dumps(result.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(asyncio.run(_cli_main(sys.argv)))
