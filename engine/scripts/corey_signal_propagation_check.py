"""
Corey signal-propagation guardrail — JARVIS TRADER.

Catches a *silent* regression in the path that carries the Corey auction-analyst
read into recorded trade outcomes. The corey IC (information coefficient) can only
recover once new futures trades fire while the session bias is fresh + directional
AND that directional read is snapshotted into trade_outcomes.corey_signal. If the
snapshot quietly reverts to 0.0 on directional days, IC never recovers and nothing
errors — exactly the failure class this check exists to surface.

Logic (deliberately conservative, to avoid false alarms):
  * Only futures symbols Corey covers are eligible: MES / MNQ / MCL / MGC.
  * A trade is "eligible" only if, for its local trade date, the corey_session_bias
    cache is data_quality='fresh' AND directional_bias != 'neutral' — i.e. the day
    genuinely had a directional read the snapshot *should* have captured.
  * Pre-go-live trades (before --since) are reported as historical "scars" but never
    flagged — they fired under the old stale-no-data cache bug (fixed 2026-06-26).
  * A single 0.0 is NOT flagged: a morning trade can legitimately snapshot a
    still-neutral bias before the 14:30 scrape lands the directional read. We flag
    only a SUSTAINED failure: >= MIN_ELIGIBLE eligible trades, ALL zero.

Exit codes (notify-on-fail contract): 2 = regression finding, 0 = healthy, 1 = error.

Usage (from engine/):
  .venv/Scripts/python -m scripts.corey_signal_propagation_check
  .venv/Scripts/python -m scripts.corey_signal_propagation_check --days 30 --since 2026-06-26
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent.parent
TRADER_DB = ENGINE_DIR / "data" / "jarvis_trader.db"  # corey_session_bias
FEEDBACK_DB = ENGINE_DIR / "data" / "agent_feedback.db"  # trade_outcomes

# Symbols the Corey auction analyst covers (futures sentiment, per rules/jarvis-trader.md).
COREY_FUTURES = {"MES", "MNQ", "MCL", "MGC"}

# Twice-daily scrape + stale-no-data cache fix went live this date; trades before it
# fired under the old bug and are scars, not regressions.
DEFAULT_SINCE = "2026-06-26"

# Need this many eligible (fresh-directional-day) futures trades all-zero before we
# call it a regression — robust to single-trade morning-before-scrape timing noise.
MIN_ELIGIBLE = 3

ZERO_EPS = 1e-9


def _local_date(ts: str) -> str | None:
    """Convert a stored ISO trade timestamp (UTC offset) to the machine-local date."""
    try:
        dt = datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone()  # to local tz
    return dt.date().isoformat()


def collect(days: int, since: str, feedback_db=None, trader_db=None) -> dict:
    feedback_db = Path(feedback_db) if feedback_db is not None else FEEDBACK_DB
    trader_db = Path(trader_db) if trader_db is not None else TRADER_DB
    if not feedback_db.exists():
        raise FileNotFoundError(f"feedback db not found: {feedback_db}")
    if not trader_db.exists():
        raise FileNotFoundError(f"trader db not found: {trader_db}")

    fb = sqlite3.connect(f"file:{feedback_db}?mode=ro", uri=True)
    fb.row_factory = sqlite3.Row
    tr = sqlite3.connect(f"file:{trader_db}?mode=ro", uri=True)
    tr.row_factory = sqlite3.Row

    qmarks = ",".join("?" * len(COREY_FUTURES))
    trades = fb.execute(
        f"""
        SELECT trade_id, timestamp, symbol, corey_signal
        FROM trade_outcomes
        WHERE symbol IN ({qmarks})
          AND DATE(timestamp) >= DATE('now', ?)
        ORDER BY timestamp ASC
        """,
        (*sorted(COREY_FUTURES), f"-{days} day"),
    ).fetchall()

    rows: list[dict] = []
    for t in trades:
        ld = _local_date(t["timestamp"])
        bias = None
        if ld is not None:
            bias = tr.execute(
                "SELECT directional_bias, data_quality, conviction "
                "FROM corey_session_bias WHERE date = ?",
                (ld,),
            ).fetchone()

        sig = float(t["corey_signal"] or 0.0)
        is_zero = abs(sig) < ZERO_EPS
        fresh_directional = bool(
            bias and bias["data_quality"] == "fresh" and bias["directional_bias"] != "neutral"
        )
        eligible = fresh_directional and ld is not None
        post_cutoff = ld is not None and ld >= since

        if not eligible:
            verdict = "n/a"  # day wasn't directional -> 0.0 is fine
        elif not is_zero:
            verdict = "ok"  # directional day, signal captured
        elif post_cutoff:
            verdict = "MISS"  # directional day, zero, post-fix -> counts toward regression
        else:
            verdict = "scar"  # directional day, zero, but pre-fix bug era

        rows.append(
            {
                "date": ld or "?",
                "symbol": t["symbol"],
                "corey_signal": round(sig, 4),
                "bias": bias["directional_bias"] if bias else "-",
                "dq": bias["data_quality"] if bias else "absent",
                "verdict": verdict,
            }
        )

    eligible_post = [r for r in rows if r["verdict"] in ("ok", "MISS")]
    misses = [r for r in eligible_post if r["verdict"] == "MISS"]
    nonzero = [r for r in eligible_post if r["verdict"] == "ok"]
    regression = len(eligible_post) >= MIN_ELIGIBLE and len(nonzero) == 0

    return {
        "rows": rows,
        "eligible_post": eligible_post,
        "misses": misses,
        "nonzero": nonzero,
        "regression": regression,
        "since": since,
        "days": days,
    }


def render(res: dict) -> str:
    out = []
    out.append("=" * 84)
    out.append(
        f"COREY SIGNAL-PROPAGATION CHECK  (last {res['days']}d, go-live cutoff {res['since']})"
    )
    out.append("=" * 84)
    if not res["rows"]:
        out.append("No futures (MES/MNQ/MCL/MGC) trade_outcomes in window — nothing to check yet.")
        out.append("=" * 84)
        return "\n".join(out)

    out.append(f"{'DATE':<12}{'SYM':<5}{'COREY_SIG':<11}{'BIAS':<9}{'DQ':<8}VERDICT")
    out.append("-" * 84)
    for r in res["rows"]:
        out.append(
            f"{r['date']:<12}{r['symbol']:<5}{r['corey_signal']:<11}"
            f"{r['bias']:<9}{r['dq']:<8}{r['verdict']}"
        )
    out.append("-" * 84)
    ep = res["eligible_post"]
    out.append(
        f"Post-go-live eligible (fresh-directional-day futures trades): {len(ep)}  "
        f"| captured non-zero: {len(res['nonzero'])}  | zero (MISS): {len(res['misses'])}"
    )
    scars = [r for r in res["rows"] if r["verdict"] == "scar"]
    if scars:
        out.append(f"Pre-go-live scars (old cache bug, not flagged): {len(scars)}")
    if res["regression"]:
        out.append(
            f"REGRESSION: {len(ep)} directional-day futures trades since {res['since']}, "
            f"ALL recorded corey_signal=0.0 — the directional read is not reaching "
            f"trade_outcomes. corey IC cannot recover. Investigate the pipeline -> "
            f"CoreyAuctionAnalystAgent -> record_outcome path."
        )
    elif len(ep) < MIN_ELIGIBLE:
        out.append(
            f"HEALTHY (insufficient signal): only {len(ep)} eligible trade(s) since "
            f"go-live; need >= {MIN_ELIGIBLE} before a regression call. Building."
        )
    else:
        out.append("HEALTHY: directional reads are reaching trade_outcomes.")
    out.append("=" * 84)
    return "\n".join(out)


def main() -> int:
    p = argparse.ArgumentParser(description="Corey signal-propagation guardrail")
    p.add_argument("--days", type=int, default=30, help="lookback window (default 30)")
    p.add_argument(
        "--since", default=DEFAULT_SINCE, help="go-live cutoff; trades before it are scars"
    )
    args = p.parse_args()

    try:
        res = collect(args.days, args.since)
    except Exception as exc:  # noqa: BLE001 — worker boundary; report + exit 1
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(render(res))
    return 2 if res["regression"] else 0


if __name__ == "__main__":
    sys.exit(main())
