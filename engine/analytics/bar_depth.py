"""Bar-depth / data-coverage health per symbol × interval (read-only).

Surfaces the data-coverage picture that ``scripts/bar_quality_fp_audit.py`` only
exposed on the CLI: for each (symbol, interval) in ``market_data_bars`` — how many
rows, the calendar span, gap structure, and the contaminated fraction under the
SAME bar-quality predicate the write-time gate enforces
(``data.bar_quality_gate.screen_bars``).

The numeric core is pure and I/O-free (``span_days``, ``gap_stats``,
``contaminated_pct``, ``pair_depth``) so it is trivially testable; ``compute_bar_depth``
is the thin DB orchestrator with an injectable ``screen_fn`` for tests.
"""

from __future__ import annotations

import sqlite3
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence

_DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "jarvis_trader.db"

# Same column order bars_repository.save_bars() persists; ts_utc at index 2.
_COLS = "symbol,interval,ts_utc,open,high,low,close,volume,source,fetched_at"
_TS_IDX = 2


# ── Pure timestamp / coverage helpers ─────────────────────────────────────────


def _parse_ts(ts: object) -> Optional[datetime]:
    """Parse an ISO-8601 string or epoch (s/ms) into a tz-aware UTC datetime."""
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        v = float(ts)
        if v > 1e11:  # milliseconds
            v /= 1000.0
        try:
            return datetime.fromtimestamp(v, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    s = str(ts).strip()
    if not s:
        return None
    iso = s.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        try:  # epoch-as-string fallback
            v = float(s)
            if v > 1e11:
                v /= 1000.0
            return datetime.fromtimestamp(v, tz=timezone.utc)
        except ValueError:
            return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _sorted_parsed(timestamps: Iterable[object]) -> list[datetime]:
    return sorted(d for d in (_parse_ts(t) for t in timestamps) if d is not None)


def span_days(timestamps: Iterable[object]) -> float:
    """Calendar span (days) from the earliest to the latest valid timestamp."""
    parsed = _sorted_parsed(timestamps)
    if len(parsed) < 2:
        return 0.0
    return round((parsed[-1] - parsed[0]).total_seconds() / 86_400.0, 4)


def gap_stats(timestamps: Iterable[object]) -> tuple[int, float]:
    """Return ``(gap_count, max_gap_hours)``.

    ``gap_count`` = consecutive bars spaced more than 2× the *median* spacing.
    Keying off the median makes this interval-agnostic and robust to routine
    session boundaries (the median tracks the normal step), so it flags genuine
    holes rather than every overnight/weekend gap.
    """
    parsed = _sorted_parsed(timestamps)
    if len(parsed) < 2:
        return 0, 0.0
    deltas = [(parsed[i] - parsed[i - 1]).total_seconds() for i in range(1, len(parsed))]
    median = statistics.median(deltas)
    threshold = max(median * 2.0, 1.0)
    gap_count = sum(1 for d in deltas if d > threshold)
    max_gap_hours = round(max(deltas) / 3600.0, 4)
    return gap_count, max_gap_hours


def contaminated_pct(row_count: int, reject_count: int) -> float:
    """Percent of rows the bar-quality predicate would reject (0–100)."""
    if row_count <= 0:
        return 0.0
    return round(100.0 * reject_count / row_count, 4)


def pair_depth(
    symbol: str,
    interval: str,
    timestamps: Sequence[object],
    row_count: int,
    reject_count: int,
) -> dict:
    """Build one coverage record for a (symbol, interval). Pure given its inputs."""
    parsed = _sorted_parsed(timestamps)
    gap_count, max_gap_hours = gap_stats(timestamps)
    return {
        "symbol": symbol,
        "interval": interval,
        "rows": row_count,
        "first_ts": parsed[0].isoformat() if parsed else None,
        "last_ts": parsed[-1].isoformat() if parsed else None,
        "span_days": span_days(timestamps),
        "gap_count": gap_count,
        "max_gap_hours": max_gap_hours,
        "contaminated_pct": contaminated_pct(row_count, reject_count),
        "enforce_safe": reject_count == 0,
    }


# ── DB orchestrator ───────────────────────────────────────────────────────────


def compute_bar_depth(
    db_path: Optional[str] = None,
    screen_fn: Optional[Callable[[Sequence], list]] = None,
) -> dict:
    """Read ``market_data_bars`` and return per-pair coverage + a summary.

    ``screen_fn`` defaults to the live bar-quality predicate; tests inject a stub.
    Returns ``{"pairs": [...], "summary": {...}, "timestamp": iso}``.
    """
    if screen_fn is None:
        from data.bar_quality_gate import screen_bars as screen_fn  # lazy: avoid import cost

    path = db_path or str(_DEFAULT_DB)
    conn = sqlite3.connect(path)
    conn.row_factory = None
    pairs: list[dict] = []
    total_rows = 0
    total_rejects = 0
    try:
        distinct = list(conn.execute("SELECT DISTINCT symbol, interval FROM market_data_bars"))
        for sym, iv in distinct:
            rows = list(
                conn.execute(
                    f"SELECT {_COLS} FROM market_data_bars "
                    "WHERE symbol=? AND interval=? ORDER BY ts_utc",
                    (sym, iv),
                )
            )
            rejects = screen_fn(rows)
            timestamps = [r[_TS_IDX] for r in rows]
            total_rows += len(rows)
            total_rejects += len(rejects)
            pairs.append(pair_depth(sym, iv, timestamps, len(rows), len(rejects)))
    finally:
        conn.close()

    pairs.sort(key=lambda p: (p["symbol"], p["interval"]))
    summary = {
        "pair_count": len(pairs),
        "symbol_count": len({p["symbol"] for p in pairs}),
        "total_rows": total_rows,
        "total_rejects": total_rejects,
        "contaminated_pct": contaminated_pct(total_rows, total_rejects),
    }
    return {
        "pairs": pairs,
        "summary": summary,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
