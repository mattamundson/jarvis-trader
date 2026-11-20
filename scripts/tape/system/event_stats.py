#!/usr/bin/env python3
"""ES first 5/15/30 minute move distributions around NFP / CPI / FOMC.

Uses Databento 1m parquet when the event morning is inside its span;
falls back to Yahoo 1m for recent events. Marks sample size on every bucket.

Release times (CT):
  NFP: 07:30
  CPI: 07:30
  FOMC statement: 13:00 (RTH) — measured from 13:00 CT
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
import os as _os  # noqa: E402
# Box layout mirrors /workspace/tape; override with TAPE_ROOT. Defaults to scripts/tape in the repo.
TAPE_ROOT = Path(_os.environ.get("TAPE_ROOT") or Path(__file__).resolve().parents[1])
from typing import Dict, List, Optional

ROOT = (TAPE_ROOT / "system")
sys.path.insert(0, str(ROOT))
from lib.timeutil import CT, to_ct_str  # noqa: E402


EVENTS = ROOT / "data" / "event_calendar.json"
PARQUET = (TAPE_ROOT / "ovn/es_1m_dbn.parquet")
YAHOO = ROOT / "data" / "es_yahoo_7d_1m.json"


def _load_df():
    import pandas as pd
    frames = []
    if PARQUET.exists():
        df = pd.read_parquet(PARQUET)
        if not isinstance(df.index, pd.DatetimeIndex):
            if "ts_event" in df.columns:
                df = df.set_index("ts_event")
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        df.index = df.index.tz_convert(CT)
        frames.append(df[["open", "high", "low", "close"]])
    if YAHOO.exists():
        rows = json.loads(YAHOO.read_text(encoding="utf-8"))["bars"]
        idx = pd.to_datetime([r[0] for r in rows], utc=True).tz_convert(CT)
        y = __import__("pandas").DataFrame(
            {"open": [r[1] for r in rows], "high": [r[2] for r in rows],
             "low": [r[3] for r in rows], "close": [r[4] for r in rows]},
            index=idx,
        )
        frames.append(y)
    if not frames:
        return None
    import pandas as pd
    df = pd.concat(frames)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df


def _move(df, release: datetime, minutes: int) -> Optional[dict]:
    import pandas as pd
    start = pd.Timestamp(release)
    end = start + timedelta(minutes=minutes)
    # pre close: last bar before release
    pre = df[df.index < start]
    win = df[(df.index >= start) & (df.index < end)]
    if len(pre) == 0 or len(win) == 0:
        return None
    px0 = float(pre["close"].iloc[-1])
    hi = float(win["high"].max())
    lo = float(win["low"].min())
    px1 = float(win["close"].iloc[-1])
    return {
        "px0": px0,
        "px1": px1,
        "delta": round(px1 - px0, 2),
        "range": round(hi - lo, 2),
        "mfe_up": round(hi - px0, 2),
        "mfe_dn": round(px0 - lo, 2),
    }


def _distro(rows: List[dict]) -> dict:
    if not rows:
        return {"n": 0}
    deltas = sorted(r["delta"] for r in rows)
    ranges = sorted(r["range"] for r in rows)
    up = sum(1 for d in deltas if d > 0)
    n = len(deltas)
    mid = n // 2
    return {
        "n": n,
        "pct_up": round(up / n, 3),
        "median_delta": deltas[mid],
        "mean_delta": round(sum(deltas) / n, 2),
        "p25_delta": deltas[n // 4],
        "p75_delta": deltas[(3 * n) // 4],
        "median_range": ranges[mid],
        "mean_range": round(sum(ranges) / n, 2),
        "max_abs_delta": max(abs(d) for d in deltas),
    }


def analyze(event_name: str) -> dict:
    cal = json.loads(EVENTS.read_text(encoding="utf-8"))["events"]
    df = _load_df()
    if df is None:
        return {"error": "no price history"}
    buckets = {"5m": [], "15m": [], "30m": []}
    details = []
    for e in cal:
        if e["name"] != event_name:
            continue
        # parse date + time_ct
        hh, mm = map(int, e.get("time_ct", "07:30").split(":"))
        y, m, d = map(int, e["date"].split("-"))
        release = datetime(y, m, d, hh, mm, tzinfo=CT)
        row = {"date": e["date"], "release_ct": release.isoformat()}
        ok = True
        for label, mins in (("5m", 5), ("15m", 15), ("30m", 30)):
            mv = _move(df, release, mins)
            row[label] = mv
            if mv is None:
                ok = False
            else:
                buckets[label].append(mv)
        if ok:
            details.append(row)
    return {
        "event": event_name,
        "sample_dates_used": [d["date"] for d in details],
        "n_events_in_calendar": sum(1 for e in cal if e["name"] == event_name),
        "n_with_price_data": len(details),
        "distributions": {k: _distro(v) for k, v in buckets.items()},
        "details": details[-12:],  # last dozen for inspection
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "reports" / "event_stats.json"))
    args = ap.parse_args()
    out = {
        "asof_ct": to_ct_str(datetime.now(CT)),
        "NFP": analyze("NFP"),
        "CPI": analyze("CPI"),
        "FOMC": analyze("FOMC"),
        "notes": [
            "Sample sizes are limited by on-box history (parquet through ~2026-10-28 + Yahoo 7d).",
            "Expand calendar + Databento backfill (cost-capped) to grow n.",
            "NFP rule in force Fri 11/6: no entry before first 5m close after 07:30 CT; one ticket max.",
        ],
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2), encoding="utf-8")
    summary = {k: {kk: out[k]["distributions"][kk].get("n") for kk in ("5m", "15m", "30m")}
               for k in ("NFP", "CPI", "FOMC") if "distributions" in out[k]}
    print(json.dumps({"out": args.out, "sample_sizes": summary}, indent=2))


if __name__ == "__main__":
    main()
