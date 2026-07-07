"""
Corey auction-analyst extract viewer — JARVIS TRADER.

Read-only view of the Corey #market-updates session-bias extracts the analyst
has produced over the last N days, straight from the corey_session_bias cache.
For each day it also checks whether #market-updates commentary now exists, so a
stale/absent cache row that should be re-extracted (the backfill bug class) is
visible at a glance rather than silently reading as "neutral".

Usage (from engine/):
  .venv/Scripts/python -m scripts.corey_extracts_view            # last 21 days
  .venv/Scripts/python -m scripts.corey_extracts_view --days 30
  .venv/Scripts/python -m scripts.corey_extracts_view --days 21 --json out.json

This does NOT call the LLM. To re-extract a day flagged NEEDS-EXTRACT, request
it through the engine (discord-jarvis MCP get_session_bias, or the daily import),
which holds the API key.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ENGINE_DIR / "data" / "jarvis_trader.db"
TATHEDOG_AUTHOR_ID = "564449478174703646"


def _count_commentary(conn: sqlite3.Connection, day: str) -> int:
    """Market-updates message count for a date (mirrors CoreyCommentaryProcessor)."""
    try:
        row = conn.execute(
            """
            SELECT COUNT(*) FROM discord_corey_commentary
            WHERE DATE(timestamp) = ?
              AND (channel = 'market-updates'
                   OR (channel = 'general' AND author_id = ?))
            """,
            (day, TATHEDOG_AUTHOR_ID),
        ).fetchone()
        return int(row[0] or 0)
    except sqlite3.DatabaseError:
        return 0


def collect(days: int) -> list[dict]:
    today = date.today()
    rows: list[dict] = []
    with sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        for i in range(days):
            d = today - timedelta(days=i)
            ds = d.isoformat()
            cached = conn.execute(
                "SELECT directional_bias, conviction, session_type, data_quality, "
                "message_count, corey_quote FROM corey_session_bias WHERE date = ?",
                (ds,),
            ).fetchone()
            live_msgs = _count_commentary(conn, ds)
            weekend = d.weekday() >= 5

            if cached is None:
                status = "NEEDS-EXTRACT" if live_msgs > 0 else ("weekend" if weekend else "no-data")
                rows.append(
                    {
                        "date": ds,
                        "weekday": d.strftime("%a"),
                        "bias": "-",
                        "conviction": None,
                        "session_type": "-",
                        "data_quality": "absent",
                        "message_count": 0,
                        "commentary_now": live_msgs,
                        "status": status,
                        "quote": "",
                    }
                )
                continue

            dq = cached["data_quality"]
            mc = int(cached["message_count"])
            # A none/msgs=0 row that now has commentary is the stale-backfill case.
            if dq == "none" and mc == 0 and live_msgs > 0:
                status = "NEEDS-EXTRACT"
            elif dq == "none":
                status = "weekend" if weekend else "no-data"
            elif cached["directional_bias"] != "neutral":
                status = "DIRECTIONAL"
            else:
                status = "neutral"

            rows.append(
                {
                    "date": ds,
                    "weekday": d.strftime("%a"),
                    "bias": cached["directional_bias"],
                    "conviction": round(float(cached["conviction"]), 2),
                    "session_type": cached["session_type"],
                    "data_quality": dq,
                    "message_count": mc,
                    "commentary_now": live_msgs,
                    "status": status,
                    "quote": (cached["corey_quote"] or "")[:64],
                }
            )
    return rows


def render(rows: list[dict]) -> str:
    out = []
    out.append("=" * 100)
    out.append(f"COREY AUCTION ANALYST — session-bias extracts (last {len(rows)} days)")
    out.append("=" * 100)
    out.append(
        f"{'DATE':<12}{'DAY':<5}{'BIAS':<9}{'CONV':<6}{'SESSION':<11}{'QUAL':<7}{'MSG':<5}{'STATUS':<14}QUOTE"
    )
    out.append("-" * 100)
    for r in rows:
        conv = f"{r['conviction']:.2f}" if r["conviction"] is not None else "-"
        out.append(
            f"{r['date']:<12}{r['weekday']:<5}{r['bias']:<9}{conv:<6}"
            f"{r['session_type']:<11}{r['data_quality']:<7}{r['message_count']:<5}"
            f"{r['status']:<14}{r['quote']}"
        )
    out.append("-" * 100)
    directional = [r for r in rows if r["status"] == "DIRECTIONAL"]
    needs = [r for r in rows if r["status"] == "NEEDS-EXTRACT"]
    neutral = [r for r in rows if r["status"] == "neutral"]
    nodata = [r for r in rows if r["status"] in ("no-data", "weekend")]
    out.append(
        f"Summary: {len(directional)} directional, {len(neutral)} genuine-neutral, "
        f"{len(nodata)} no-data/weekend, {len(needs)} NEEDS-EXTRACT (commentary present, cache stale)."
    )
    if directional:
        bull = sum(1 for r in directional if r["bias"] == "bullish")
        bear = sum(1 for r in directional if r["bias"] == "bearish")
        out.append(f"  Directional breakdown: {bull} bullish, {bear} bearish.")
    if needs:
        out.append(
            "  Re-extract via engine (MCP get_session_bias / daily import): "
            + ", ".join(r["date"] for r in needs)
        )
    out.append("=" * 100)
    return "\n".join(out)


def main() -> int:
    p = argparse.ArgumentParser(description="Corey auction-analyst extract viewer")
    p.add_argument("--days", type=int, default=21, help="lookback window (default 21)")
    p.add_argument("--json", help="also write the raw rows to this JSON path")
    args = p.parse_args()

    if not DB_PATH.exists():
        print(f"ERROR: db not found at {DB_PATH}", file=sys.stderr)
        return 1

    rows = collect(args.days)
    print(render(rows))
    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=2))
        print(f"\nrows written to {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
