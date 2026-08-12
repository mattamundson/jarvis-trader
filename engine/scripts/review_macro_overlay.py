#!/usr/bin/env python3
"""Review the macro-trend overlay effect: telemetry x decisions x trade_outcomes.

Read-only. The overlay (ENABLE_MACRO_TREND_BIAS) appends a one-line macro bias to the
technical analyst's context at pipeline Stage 1 and records every injection to
engine/data/macro_overlay_telemetry.jsonl. Nothing yet grades whether that bias helps.

This joins each telemetry injection to:
  1. the DECISION the pipeline produced in that same run
     (decisions table in jarvis_trader.db) -- nearest-forward on (symbol, ts), and
  2. the trade OUTCOME, where one exists
     (trade_outcomes in agent_feedback.db) -- nearest-forward on (symbol, ts).

There is NO foreign key anywhere; all joins are temporal on (symbol, UTC timestamp).
telemetry.ts is stamped at Stage-1 injection; the matching decision is persisted at
run-end, so decision.ts >= telemetry.ts by the run duration (seconds-minutes).

IMPORTANT -- attribution is soft. The overlay is advisory context, never a mechanical
gate, so a regime state is a *treatment label* on the run, not an isolable driver.
Treat the output as directional, not causal.

Usage:
    python engine/scripts/review_macro_overlay.py [--data-dir DIR] [--tolerance-min N]

Defaults resolve DIR to <repo>/engine/data. Point --data-dir at a live checkout's
engine/data to review the running system's databases.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Hygiene rule mirrored from engine/analytics/outcome_hygiene.py: drop corrupt rows whose
# |pnl_usd| exceeds this (a known bad-data fingerprint) so they can't skew win-rate/avg-pnl.
MAX_ABS_PNL_USD = 5000.0


def parse_ts(s: str | None) -> datetime | None:
    """Tolerant ISO-8601 -> aware UTC datetime. Naive strings are assumed UTC."""
    if not s:
        return None
    s = s.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # last resort: trim fractional/tz noise and retry date+time
        try:
            dt = datetime.fromisoformat(s[:19])
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def load_telemetry(path: Path) -> list[dict]:
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        r["_ts"] = parse_ts(r.get("ts"))
        if r["_ts"] is not None:
            rows.append(r)
    rows.sort(key=lambda r: r["_ts"])
    return rows


def load_decisions(db: Path) -> dict[str, list[tuple[datetime, sqlite3.Row]]]:
    """symbol(upper) -> [(ts, row), ...] sorted ascending."""
    out: dict[str, list[tuple[datetime, sqlite3.Row]]] = defaultdict(list)
    if not db.exists():
        return out
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        for row in con.execute("SELECT symbol, timestamp, action, confidence FROM decisions"):
            ts = parse_ts(row["timestamp"])
            if ts is None or not row["symbol"]:
                continue
            out[row["symbol"].upper()].append((ts, row))
    finally:
        con.close()
    for sym in out:
        out[sym].sort(key=lambda t: t[0])
    return out


def load_outcomes(db: Path) -> dict[str, list[tuple[datetime, sqlite3.Row]]]:
    """symbol(upper) -> [(ts, row), ...] after hygiene, sorted ascending."""
    out: dict[str, list[tuple[datetime, sqlite3.Row]]] = defaultdict(list)
    if not db.exists():
        return out
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT trade_id, timestamp, symbol, direction, pnl_usd, outcome FROM trade_outcomes"
        ).fetchall()
    finally:
        con.close()
    seen = set()
    for row in rows:
        if row["trade_id"] in seen:  # trade_id is PK, but dedupe defensively
            continue
        seen.add(row["trade_id"])
        pnl = row["pnl_usd"]
        if pnl is not None and abs(pnl) > MAX_ABS_PNL_USD:  # outcome_hygiene rule
            continue
        ts = parse_ts(row["timestamp"])
        if ts is None or not row["symbol"]:
            continue
        out[row["symbol"].upper()].append((ts, row))
    for sym in out:
        out[sym].sort(key=lambda t: t[0])
    return out


def nearest_forward(series, ts, max_delta=None):
    """First (t, row) in ascending series with t >= ts (optionally within max_delta)."""
    for t, row in series:
        if t >= ts:
            if max_delta is not None and (t - ts) > max_delta:
                return None
            return (t, row)
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    default_data = Path(__file__).resolve().parents[1] / "data"
    ap.add_argument("--data-dir", type=Path, default=default_data,
                    help="dir holding jarvis_trader.db, agent_feedback.db, macro_overlay_telemetry.jsonl")
    ap.add_argument("--telemetry", type=Path, default=None, help="override telemetry path")
    ap.add_argument("--tolerance-min", type=float, default=10.0,
                    help="max minutes between telemetry.ts and the matched decision (default 10)")
    args = ap.parse_args()

    data_dir = args.data_dir
    tel_path = args.telemetry or (data_dir / "macro_overlay_telemetry.jsonl")
    tol = timedelta(minutes=args.tolerance_min)

    telemetry = load_telemetry(tel_path)
    decisions = load_decisions(data_dir / "jarvis_trader.db")
    outcomes = load_outcomes(data_dir / "agent_feedback.db")

    print("=" * 78)
    print("MACRO-TREND OVERLAY EFFECT REVIEW  (read-only, directional not causal)")
    print("=" * 78)
    print(f"data-dir       : {data_dir}")
    print(f"telemetry rows : {len(telemetry)}  ({tel_path.name})")
    if telemetry:
        print(f"telemetry span : {telemetry[0]['_ts'].isoformat()}  ->  {telemetry[-1]['_ts'].isoformat()}")
    print(f"decisions      : {sum(len(v) for v in decisions.values())} rows across {len(decisions)} symbols")
    print(f"trade_outcomes : {sum(len(v) for v in outcomes.values())} rows (post-hygiene) across {len(outcomes)} symbols")
    print(f"match tolerance: {args.tolerance_min:g} min (telemetry -> decision)")
    if not telemetry:
        print("\nNo telemetry yet -- nothing to review.")
        return 0

    # Per-state aggregates
    by_state_actions: dict[str, Counter] = defaultdict(Counter)
    by_state_conf: dict[str, list[float]] = defaultdict(list)
    by_state_symbols: dict[str, Counter] = defaultdict(Counter)
    matched = 0
    joined_outcomes = []  # (state, symbol, action, outcome_row)

    for r in telemetry:
        state = r.get("state", "UNKNOWN")
        sym = (r.get("symbol") or "").upper()
        by_state_symbols[state][sym] += 1
        hit = nearest_forward(decisions.get(sym, []), r["_ts"], tol)
        if not hit:
            by_state_actions[state]["<no-decision-match>"] += 1
            continue
        matched += 1
        _, drow = hit
        by_state_actions[state][drow["action"]] += 1
        if drow["confidence"] is not None:
            by_state_conf[state].append(float(drow["confidence"]))
        # decision -> outcome (open-ended forward, same symbol)
        orow = nearest_forward(outcomes.get(sym, []), hit[0], None)
        if orow:
            joined_outcomes.append((state, sym, drow["action"], orow[1]))

    print("\n" + "-" * 78)
    print(f"TELEMETRY -> DECISION JOIN   ({matched}/{len(telemetry)} injections matched a decision)")
    print("-" * 78)
    for state in sorted(by_state_actions):
        conf = by_state_conf[state]
        avg_conf = f"{sum(conf)/len(conf):.2f}" if conf else "n/a"
        syms = ", ".join(f"{s}x{n}" for s, n in by_state_symbols[state].most_common())
        print(f"\n[{state}]  injections={sum(by_state_symbols[state].values())}  avg_decision_confidence={avg_conf}")
        print(f"  symbols: {syms}")
        print("  decision actions:")
        for action, n in by_state_actions[state].most_common():
            print(f"    {action:<22} {n}")

    print("\n" + "-" * 78)
    print("DECISION -> OUTCOME JOIN  (P&L grade)")
    print("-" * 78)
    if not joined_outcomes:
        print("  0 injections map to a recorded trade outcome.")
        print("  -> Too few closed outcomes in the overlay era to grade P&L. The harness is")
        print("     wired and ready; re-run as trade_outcomes accrues.")
    else:
        wins = [o for *_ , o in joined_outcomes if (o["outcome"] or "").upper() == "WIN"]
        pnls = [o["pnl_usd"] for *_, o in joined_outcomes if o["pnl_usd"] is not None]
        print(f"  matched outcomes: {len(joined_outcomes)}")
        print(f"  win-rate        : {len(wins)}/{len(joined_outcomes)}")
        if pnls:
            print(f"  total pnl_usd   : {sum(pnls):+.2f}   avg {sum(pnls)/len(pnls):+.2f}")
        by_state_out = defaultdict(list)
        for state, _sym, _action, o in joined_outcomes:
            by_state_out[state].append(o)
        for state, outs in sorted(by_state_out.items()):
            w = sum(1 for o in outs if (o["outcome"] or "").upper() == "WIN")
            p = sum(o["pnl_usd"] or 0 for o in outs)
            print(f"    [{state}] n={len(outs)} wins={w} pnl_usd={p:+.2f}")

    print("\n" + "=" * 78)
    print("READ: this measures what the pipeline DECIDED under each injected regime state,")
    print("not a with/without counterfactual. The overlay only tints the technical analyst's")
    print("context, so treat correlations as directional. A clean A/B needs a shadow-log hook.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
