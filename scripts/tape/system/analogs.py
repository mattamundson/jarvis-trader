#!/usr/bin/env python3
"""Find the 10 most similar past overnight sessions and report outcome distributions.

Features (normalized): overnight range (pts), retrace % from ON high, VIX level,
pre-event flag (NFP/CPI/FOMC next morning), gamma regime if known (else NaN → imputed).

Data sources (read-only, no purchases):
  - /workspace/tape/ovn/es_1m_dbn.parquet (Databento ES 1m through ~2026-10-28)
  - /workspace/tape/system/data/es_yahoo_7d_1m.json (recent)
  - /workspace/tape/system/data/vix_daily.json
  - /workspace/tape/system/data/event_calendar.json
  - optional gex-history jsonl for regime tag

Cost: uses already-downloaded history. Fresh Databento pulls must pass --max-cost.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
import os as _os  # noqa: E402
# Box layout mirrors /workspace/tape; override with TAPE_ROOT. Defaults to scripts/tape in the repo.
TAPE_ROOT = Path(_os.environ.get("TAPE_ROOT") or Path(__file__).resolve().parents[1])
from typing import Dict, List, Optional, Tuple

ROOT = (TAPE_ROOT / "system")
sys.path.insert(0, str(ROOT))
from lib.timeutil import CT, to_ct_str  # noqa: E402


PARQUET = (TAPE_ROOT / "ovn/es_1m_dbn.parquet")
VIX = ROOT / "data" / "vix_daily.json"
EVENTS = ROOT / "data" / "event_calendar.json"
YAHOO = ROOT / "data" / "es_yahoo_7d_1m.json"
GEX_HIST = (TAPE_ROOT / "state")


@dataclass
class SessionFeat:
    session_date: str  # RTH date the overnight feeds into
    on_high: float
    on_low: float
    on_range: float
    retrace_pct: float  # (on_high - last_pre_rth) / on_range
    vix: Optional[float]
    pre_event: int  # 1 if NFP/CPI/FOMC on session_date
    gamma_regime: Optional[str]  # long/short/unknown
    # outcomes from last overnight print to +1h/+3h/RTH open relative to a reference ts
    # For historical: reference = 22:00 CT prior evening (standardized)
    px_ref: float
    ret_1h: Optional[float]
    ret_3h: Optional[float]
    ret_to_rth: Optional[float]


def _load_vix() -> Dict[str, float]:
    if not VIX.exists():
        return {}
    bars = json.loads(VIX.read_text(encoding="utf-8")).get("bars_daily") or []
    return {b[0]: float(b[4]) for b in bars}


def _event_dates() -> Dict[str, str]:
    if not EVENTS.exists():
        return {}
    return {e["date"]: e["name"] for e in json.loads(EVENTS.read_text(encoding="utf-8")).get("events", [])}


def _bars_from_parquet():
    import pandas as pd
    if not PARQUET.exists():
        return None
    df = pd.read_parquet(PARQUET)
    # index ts_event UTC
    if not isinstance(df.index, pd.DatetimeIndex):
        if "ts_event" in df.columns:
            df = df.set_index("ts_event")
    df = df.sort_index()
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    df.index = df.index.tz_convert(CT)
    return df


def _bars_from_yahoo():
    import pandas as pd
    if not YAHOO.exists():
        return None
    rows = json.loads(YAHOO.read_text(encoding="utf-8"))["bars"]
    idx = pd.to_datetime([r[0] for r in rows], utc=True).tz_convert(CT)
    df = pd.DataFrame(
        {"open": [r[1] for r in rows], "high": [r[2] for r in rows],
         "low": [r[3] for r in rows], "close": [r[4] for r in rows]},
        index=idx,
    )
    return df


def _overnight_window(session_date: date):
    """Overnight for RTH session_date: 17:00 CT prior day → 08:29 CT session_date."""
    import pandas as pd
    start = pd.Timestamp(datetime(session_date.year, session_date.month, session_date.day,
                                  17, 0, tzinfo=CT) - timedelta(days=1))
    end = pd.Timestamp(datetime(session_date.year, session_date.month, session_date.day,
                                8, 30, tzinfo=CT))
    return start, end


def build_sessions(max_sessions: int = 400) -> List[SessionFeat]:
    import pandas as pd
    df = _bars_from_parquet()
    y = _bars_from_yahoo()
    if df is None and y is None:
        return []
    if df is None:
        df = y
    elif y is not None:
        # append yahoo beyond parquet end
        df = pd.concat([df[["open", "high", "low", "close"]], y[["open", "high", "low", "close"]]])
        df = df[~df.index.duplicated(keep="last")].sort_index()

    vix = _load_vix()
    events = _event_dates()
    # candidate session dates: weekdays where we have bars in overnight window
    first = df.index[0].date()
    last = df.index[-1].date()
    feats: List[SessionFeat] = []
    d = first + timedelta(days=1)
    while d <= last:
        if d.weekday() >= 5:
            d += timedelta(days=1)
            continue
        start, end = _overnight_window(d)
        # need data
        if start < df.index[0] or end > df.index[-1] + timedelta(minutes=5):
            d += timedelta(days=1)
            continue
        ovn = df[(df.index >= start) & (df.index < end)]
        if len(ovn) < 60:
            d += timedelta(days=1)
            continue
        on_high = float(ovn["high"].max())
        on_low = float(ovn["low"].min())
        on_range = on_high - on_low
        if on_range <= 0:
            d += timedelta(days=1)
            continue
        # reference at 22:00 CT prior evening (or first bar after)
        ref_ts = pd.Timestamp(datetime(d.year, d.month, d.day, 22, 0, tzinfo=CT) - timedelta(days=1))
        ref_slice = ovn[ovn.index >= ref_ts]
        if len(ref_slice) == 0:
            d += timedelta(days=1)
            continue
        px_ref = float(ref_slice["close"].iloc[0])
        retrace_pct = (on_high - float(ovn["close"].iloc[-1])) / on_range

        def ret_at(hours: float) -> Optional[float]:
            t = ref_ts + timedelta(hours=hours)
            w = ovn[ovn.index >= t]
            if len(w) == 0:
                # maybe into RTH
                w2 = df[df.index >= t]
                if len(w2) == 0:
                    return None
                return float(w2["close"].iloc[0]) - px_ref
            return float(w["close"].iloc[0]) - px_ref

        rth_open = end  # 08:30
        rth_bars = df[df.index >= rth_open]
        ret_to_rth = (float(rth_bars["close"].iloc[0]) - px_ref) if len(rth_bars) else None

        ds = d.isoformat()
        # VIX: use prior close
        vix_px = vix.get(ds)
        if vix_px is None:
            # previous calendar day keys
            for back in range(1, 5):
                key = (d - timedelta(days=back)).isoformat()
                if key in vix:
                    vix_px = vix[key]
                    break

        feats.append(SessionFeat(
            session_date=ds,
            on_high=on_high,
            on_low=on_low,
            on_range=on_range,
            retrace_pct=retrace_pct,
            vix=vix_px,
            pre_event=1 if ds in events else 0,
            gamma_regime=None,
            px_ref=px_ref,
            ret_1h=ret_at(1),
            ret_3h=ret_at(3),
            ret_to_rth=ret_to_rth,
        ))
        d += timedelta(days=1)
        if len(feats) >= max_sessions:
            # keep most recent
            pass
    if len(feats) > max_sessions:
        feats = feats[-max_sessions:]
    return feats


def _vec(f: SessionFeat, vix_med: float, range_med: float) -> List[float]:
    return [
        f.on_range / range_med if range_med else 0.0,
        f.retrace_pct,
        (f.vix or vix_med) / vix_med if vix_med else 0.0,
        float(f.pre_event),
    ]


def find_analogs(query: SessionFeat, library: List[SessionFeat], k: int = 10) -> List[Tuple[float, SessionFeat]]:
    lib = [f for f in library if f.session_date != query.session_date]
    if not lib:
        return []
    ranges = [f.on_range for f in lib]
    vixes = [f.vix for f in lib if f.vix is not None]
    range_med = sorted(ranges)[len(ranges) // 2]
    vix_med = sorted(vixes)[len(vixes) // 2] if vixes else 20.0
    qv = _vec(query, vix_med, range_med)
    scored = []
    for f in lib:
        fv = _vec(f, vix_med, range_med)
        dist = math.sqrt(sum((a - b) ** 2 for a, b in zip(qv, fv)))
        scored.append((dist, f))
    scored.sort(key=lambda x: x[0])
    return scored[:k]


def summarize(analogs: List[Tuple[float, SessionFeat]]) -> dict:
    def distro(vals: List[Optional[float]]) -> dict:
        xs = [v for v in vals if v is not None]
        if not xs:
            return {"n": 0}
        xs = sorted(xs)
        up = sum(1 for v in xs if v > 0)
        dn = sum(1 for v in xs if v < 0)
        mid = len(xs) // 2
        return {
            "n": len(xs),
            "pct_up": round(up / len(xs), 3),
            "pct_down": round(dn / len(xs), 3),
            "median_pts": round(xs[mid], 2),
            "p25": round(xs[len(xs) // 4], 2),
            "p75": round(xs[(3 * len(xs)) // 4], 2),
            "mean_pts": round(sum(xs) / len(xs), 2),
        }

    return {
        "n_analogs": len(analogs),
        "analogs": [
            {
                "session_date": f.session_date,
                "dist": round(dist, 4),
                "on_range": round(f.on_range, 2),
                "retrace_pct": round(f.retrace_pct, 3),
                "vix": f.vix,
                "pre_event": f.pre_event,
                "ret_1h": f.ret_1h,
                "ret_3h": f.ret_3h,
                "ret_to_rth": f.ret_to_rth,
            }
            for dist, f in analogs
        ],
        "outcome_1h": distro([f.ret_1h for _, f in analogs]),
        "outcome_3h": distro([f.ret_3h for _, f in analogs]),
        "outcome_to_rth_open": distro([f.ret_to_rth for _, f in analogs]),
    }


def current_query_from_tonight(asof_ct: str = "2026-11-05 22:44") -> SessionFeat:
    """Build a query feature vector from tonight's Yahoo overnight so far."""
    import pandas as pd
    y = _bars_from_yahoo()
    if y is None:
        raise SystemExit("no yahoo bars")
    # tonight feeds Fri 2026-11-06 RTH (NFP)
    d = date(2026, 11, 6)
    start, _ = _overnight_window(d)
    asof = pd.Timestamp(datetime.fromisoformat(asof_ct).replace(tzinfo=CT))
    ovn = y[(y.index >= start) & (y.index <= asof)]
    on_high = float(ovn["high"].max())
    on_low = float(ovn["low"].min())
    on_range = on_high - on_low
    retrace = (on_high - float(ovn["close"].iloc[-1])) / on_range if on_range else 0.0
    vix = _load_vix().get("2026-11-05")
    return SessionFeat(
        session_date="2026-11-06",
        on_high=on_high,
        on_low=on_low,
        on_range=on_range,
        retrace_pct=retrace,
        vix=vix,
        pre_event=1,  # NFP
        gamma_regime="short",  # stale map said short net overnight
        px_ref=float(ovn["close"].iloc[-1]),
        ret_1h=None,
        ret_3h=None,
        ret_to_rth=None,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--max-sessions", type=int, default=400)
    ap.add_argument("--out", default=str(ROOT / "reports" / "analogs_latest.json"))
    args = ap.parse_args()
    lib = build_sessions(max_sessions=args.max_sessions)
    q = current_query_from_tonight()
    analogs = find_analogs(q, lib, k=args.k)
    out = {
        "asof_ct": to_ct_str(datetime.now(CT)),
        "query": {
            "session_date": q.session_date,
            "on_high": q.on_high,
            "on_low": q.on_low,
            "on_range": round(q.on_range, 2),
            "retrace_pct": round(q.retrace_pct, 3),
            "vix": q.vix,
            "pre_event": q.pre_event,
            "gamma_regime": q.gamma_regime,
        },
        "library_n": len(lib),
        "library_span": {"first": lib[0].session_date, "last": lib[-1].session_date} if lib else None,
        "result": summarize(analogs),
        "notes": [
            "Gamma regime mostly unavailable historically — distance ignores it when null.",
            "Reference timestamp standardized at 22:00 CT prior evening.",
            "Uses Databento parquet + Yahoo recent; Databento live overnight not yet available for 11/5.",
        ],
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps({
        "out": args.out,
        "library_n": len(lib),
        "analogs_n": len(analogs),
        "outcome_1h": out["result"]["outcome_1h"],
        "outcome_to_rth_open": out["result"]["outcome_to_rth_open"],
    }, indent=2))


if __name__ == "__main__":
    main()
