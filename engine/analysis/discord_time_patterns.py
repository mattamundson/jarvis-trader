"""
Discord Signal Time Pattern Analysis
Finds optimal trading windows per symbol from discord_bot_signals data.
Usage: cd engine && python -m analysis.discord_time_patterns
"""

import json
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional


def _get_db_path() -> str:
    """
    Walk up from this file to find a jarvis_trader.db that contains the
    discord_bot_signals table.  We check every candidate rather than
    returning the first file found, because the engine/data/ copy is the
    live trading DB and does not have that table.
    """
    here = Path(__file__).resolve()
    candidates = []
    for parent in here.parents:
        candidate = parent / "data" / "jarvis_trader.db"
        if candidate.exists():
            candidates.append(candidate)

    for candidate in candidates:
        try:
            conn = sqlite3.connect(str(candidate))
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='discord_bot_signals'"
            ).fetchone()
            conn.close()
            if row:
                return str(candidate)
        except sqlite3.Error:
            continue

    raise FileNotFoundError(
        "Cannot find a jarvis_trader.db that contains the discord_bot_signals table. "
        f"Searched: {[str(c) for c in candidates]}"
    )


def _parse_timestamp(ts: str) -> Optional[datetime]:
    """Safely parse an ISO 8601 timestamp string, including timezone offsets."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        # Try stripping fractional seconds or unusual formats
        try:
            # Handle timestamps like "2023-07-15T09:30:00-04:00"
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None


def compute_time_patterns(symbol: str, db_path: str = None) -> dict:
    """
    Compute time-based win rate and gain patterns for a given symbol.

    Returns a dict with keys:
        symbol, total_signals,
        by_hour, by_day_of_week, by_month,
        optimal_hours, optimal_days, avoid_hours
    """
    if db_path is None:
        db_path = _get_db_path()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        cursor = conn.execute(
            "SELECT timestamp, win_rate, gain FROM discord_bot_signals WHERE symbol = ?",
            (symbol,),
        )
        rows = cursor.fetchall()
    finally:
        conn.close()

    if not rows:
        return {
            "symbol": symbol,
            "total_signals": 0,
            "by_hour": {},
            "by_day_of_week": {},
            "by_month": {},
            "optimal_hours": [],
            "optimal_days": [],
            "avoid_hours": [],
        }

    # Accumulators: {key: {"win_rate_sum": float, "gain_sum": float, "count": int}}
    hour_buckets: dict = defaultdict(lambda: {"win_rate_sum": 0.0, "gain_sum": 0.0, "count": 0})
    dow_buckets: dict = defaultdict(lambda: {"win_rate_sum": 0.0, "gain_sum": 0.0, "count": 0})
    month_buckets: dict = defaultdict(lambda: {"win_rate_sum": 0.0, "gain_sum": 0.0, "count": 0})

    total = 0
    skipped = 0

    for row in rows:
        dt = _parse_timestamp(row["timestamp"])
        if dt is None:
            skipped += 1
            continue

        wr = row["win_rate"] if row["win_rate"] is not None else 0.0
        gain = row["gain"] if row["gain"] is not None else 0.0

        hour = dt.hour
        dow = dt.weekday()  # 0=Monday … 6=Sunday
        month = dt.month  # 1-12

        for bucket, key in [(hour_buckets, hour), (dow_buckets, dow), (month_buckets, month)]:
            bucket[key]["win_rate_sum"] += wr
            bucket[key]["gain_sum"] += gain
            bucket[key]["count"] += 1

        total += 1

    def _summarise(buckets: dict) -> dict:
        result = {}
        for key, v in buckets.items():
            n = v["count"]
            result[key] = {
                "win_rate": round(v["win_rate_sum"] / n / 100.0, 4),  # normalise 0-100 → 0.0-1.0
                "avg_gain": round(v["gain_sum"] / n, 4),
                "count": n,
            }
        return result

    MIN_SIGNALS = 5

    by_hour = _summarise(hour_buckets)
    by_dow = _summarise(dow_buckets)
    by_month = _summarise(month_buckets)

    # Optimal hours: top-3 by win_rate where count >= MIN_SIGNALS
    qualified_hours = [(h, d) for h, d in by_hour.items() if d["count"] >= MIN_SIGNALS]
    qualified_hours.sort(key=lambda x: x[1]["win_rate"], reverse=True)
    optimal_hours = [h for h, _ in qualified_hours[:3]]
    avoid_hours = [h for h, _ in qualified_hours[-3:]] if len(qualified_hours) >= 3 else []
    # Reverse avoid list so worst is first
    avoid_hours = list(reversed(avoid_hours))

    # Optimal days: top entries by win_rate where count >= MIN_SIGNALS
    qualified_days = [(d, v) for d, v in by_dow.items() if v["count"] >= MIN_SIGNALS]
    qualified_days.sort(key=lambda x: x[1]["win_rate"], reverse=True)
    optimal_days = [d for d, _ in qualified_days]

    return {
        "symbol": symbol,
        "total_signals": total,
        "skipped_unparseable": skipped,
        "by_hour": by_hour,
        "by_day_of_week": by_dow,
        "by_month": by_month,
        "optimal_hours": optimal_hours,
        "optimal_days": optimal_days,
        "avoid_hours": avoid_hours,
    }


def compute_all_patterns(output_path: str = None) -> dict:
    """
    Run compute_time_patterns for every symbol found in discord_bot_signals.
    Saves results to data/discord_time_patterns.json (relative to project root)
    unless output_path is specified.

    Returns dict keyed by symbol.
    """
    db_path = _get_db_path()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute("SELECT DISTINCT symbol FROM discord_bot_signals ORDER BY symbol")
        symbols = [row["symbol"] for row in cursor.fetchall()]
    finally:
        conn.close()

    results: dict = {}
    for sym in symbols:
        print(f"  Processing {sym}...")
        results[sym] = compute_time_patterns(sym, db_path=db_path)

    # Determine output path
    if output_path is None:
        db_file = Path(db_path)
        output_file = db_file.parent / "discord_time_patterns.json"
    else:
        output_file = Path(output_path)

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2)
    print(f"\nSaved patterns to: {output_file}")

    return results


if __name__ == "__main__":
    print("Computing Discord signal time patterns for all symbols...")
    patterns = compute_all_patterns()

    DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    for sym, data in patterns.items():
        print(f"\n{sym}: {data['total_signals']} signals")
        print(f"  Optimal hours: {data['optimal_hours']}")
        optimal_day_names = [DAY_NAMES[d] for d in data["optimal_days"]]
        print(f"  Optimal days:  {optimal_day_names}")
        print(f"  Avoid hours:   {data['avoid_hours']}")

        # Show top hour details
        if data["by_hour"]:
            best_hours = sorted(
                data["by_hour"].items(),
                key=lambda x: x[1]["win_rate"],
                reverse=True,
            )[:3]
            for hour, stats in best_hours:
                print(
                    f"    Hour {hour:02d}:00 — WR {stats['win_rate']:.1%}, "
                    f"avg gain {stats['avg_gain']:.2f}, n={stats['count']}"
                )
