#!/usr/bin/env python3
"""Pre-read checklist header. Missing items listed at top.

Reads sibling context file if present:
  /workspace/tape/context/es-context-latest.md
Does not duplicate the context builder — only consumes it + local state.

Price: IB/engine primary (price-latest, /analyze/bars, /prices/snapshot, flow-latest).
Yahoo only as labeled fallback when IB/engine unreachable or age > 2 min.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
import os as _os  # noqa: E402
# Box layout mirrors /workspace/tape; override with TAPE_ROOT. Defaults to scripts/tape in the repo.
TAPE_ROOT = Path(_os.environ.get("TAPE_ROOT") or Path(__file__).resolve().parents[1])
from typing import Any, Dict, List, Optional

ROOT = (TAPE_ROOT / "system")
sys.path.insert(0, str(ROOT))
from lib.prices import (  # noqa: E402
    live_price_quote,
    load_es_1m,
    nq_vs_es,
    prior_n_sessions,
)
from lib.timeutil import CT, to_ct_str  # noqa: E402


CONTEXT_MD = (TAPE_ROOT / "context/es-context-latest.md")
GEX_PATH = (TAPE_ROOT / "state/gex-latest.json")
VIX_PATH = ROOT / "data" / "vix_daily.json"
EVENTS_PATH = ROOT / "data" / "event_calendar.json"
STALE_GAMMA_MIN = 60


def _gamma() -> dict:
    if not GEX_PATH.exists():
        return {"missing": True, "stale": True, "age_min": None, "raw": None}
    g = json.loads(GEX_PATH.read_text(encoding="utf-8"))
    asof = g.get("asof_ct") or g.get("pulled_ct")
    age = None
    stale = True
    if asof:
        try:
            dt = datetime.strptime(asof.strip()[:16], "%Y-%m-%d %H:%M").replace(tzinfo=CT)
            age = (datetime.now(CT) - dt).total_seconds() / 60.0
            stale = age > STALE_GAMMA_MIN
        except Exception:
            pass
    return {
        "missing": False,
        "stale": stale,
        "age_min": round(age, 1) if age is not None else None,
        "asof_ct": asof,
        "spot": g.get("spot"),
        "net_gex": g.get("net_gex"),
        "call_wall": g.get("call_wall"),
        "put_wall": g.get("put_wall"),
        "flip": g.get("flip"),
        "flip_status": g.get("flip_status"),
        "source": g.get("source"),
        "levels_usable": not stale,
    }


def _vix() -> dict:
    if not VIX_PATH.exists():
        return {"missing": True}
    v = json.loads(VIX_PATH.read_text(encoding="utf-8"))
    bars = v.get("bars_daily") or []
    if not bars:
        return {"missing": True}
    last = bars[-1]
    return {"missing": False, "date": last[0], "close": last[4], "high": last[2], "low": last[3], "src": v.get("src")}


def _events(asof: datetime) -> dict:
    if not EVENTS_PATH.exists():
        return {"missing": True, "upcoming": []}
    cal = json.loads(EVENTS_PATH.read_text(encoding="utf-8"))
    upcoming = []
    today = asof.astimezone(CT).date().isoformat()
    for e in cal.get("events", []):
        if e["date"] >= today:
            upcoming.append(e)
    return {"missing": False, "upcoming": upcoming[:5], "today": [e for e in cal.get("events", []) if e["date"] == today]}


def _expected_move_stub(vix_close: Optional[float], spot: Optional[float]) -> dict:
    """Rough 1-day expected move ≈ spot * (vix/100) / sqrt(252). Not options-derived."""
    if vix_close is None or spot is None:
        return {"missing": True, "note": "need VIX + spot"}
    em = spot * (vix_close / 100.0) / (252 ** 0.5)
    return {
        "missing": False,
        "method": "spot*(VIX/100)/sqrt(252) — NOT options straddle; replace when SPX expected move available",
        "pts": round(em, 2),
        "vix": vix_close,
        "spot": spot,
    }


def build(asof: Optional[datetime] = None) -> dict:
    asof = asof or datetime.now(CT)
    missing: List[str] = []
    sessions = prior_n_sessions(5, asof=asof)
    if len(sessions) < 5:
        missing.append(f"prior_5_sessions (have {len(sessions)})")
    g = _gamma()
    if g["missing"]:
        missing.append("gamma")
    elif g["stale"]:
        missing.append(f"gamma_fresh (age_min={g['age_min']}, STALE>{STALE_GAMMA_MIN} — levels EXCLUDED)")
    v = _vix()
    if v["missing"]:
        missing.append("vix")
    ev = _events(asof)
    if ev["missing"]:
        missing.append("event_calendar")
    nq = nq_vs_es()
    if nq.get("missing"):
        missing.append("nq_vs_es")
    quote = live_price_quote(asof)
    spot = quote.get("last")
    if spot is None:
        missing.append("es_price")
        # last-ditch: any ES 1m bar
        bars = load_es_1m(prefer="auto")
        if bars:
            spot = bars[-1].c
            quote = {
                **quote,
                "last": spot,
                "src": quote.get("src") or "load_es_1m(auto)",
                "missing": False,
            }
    em = _expected_move_stub(v.get("close") if not v.get("missing") else None, spot or g.get("spot"))
    if em["missing"]:
        missing.append("expected_move")

    context_present = CONTEXT_MD.exists() and CONTEXT_MD.stat().st_size > 0
    if not context_present:
        missing.append("context_file (/workspace/tape/context/es-context-latest.md) — sibling task")

    return {
        "asof_ct": to_ct_str(asof),
        "missing": missing,
        "prior_5_sessions": sessions,
        "vix": v,
        "expected_move": em,
        "gamma": g,
        "events": ev,
        "nq_vs_es": nq,
        "es_last": spot,
        "price_quote": quote,
        "context_file": str(CONTEXT_MD) if context_present else None,
        "rules": {
            "gamma_stale_min": STALE_GAMMA_MIN,
            "stale_gamma_levels_excluded": True,
            "price_stale_max_min": 2.0,
            "price_primary": "IB/engine (price-latest, /analyze/bars, /prices/snapshot, flow-latest)",
            "price_fallback": "Yahoo labeled when IB/engine unreachable or age>2m",
        },
    }


def render(header: dict) -> str:
    lines = []
    lines.append(f"# PRE-READ CHECKLIST  {header['asof_ct']} CT")
    lines.append("")
    if header["missing"]:
        lines.append("## MISSING / STALE (fix these first)")
        for m in header["missing"]:
            lines.append(f"- {m}")
        lines.append("")
    else:
        lines.append("## MISSING / STALE: none")
        lines.append("")

    q = header.get("price_quote") or {}
    age = q.get("age_min")
    age_s = f"{age} min" if age is not None else "n/a"
    lines.append(f"## Price source: {q.get('src', 'unknown')}  |  age: {age_s}  |  last={q.get('last')}  |  asof={q.get('asof_ct')}")
    lines.append("")

    lines.append("## Prior 5 sessions (RTH preferred)")
    for s in header["prior_5_sessions"]:
        lines.append(f"- {s['date']}: H={s['high']} L={s['low']} C={s.get('close')} ({s['src']})")
    lines.append("")
    v = header["vix"]
    if not v.get("missing"):
        lines.append(f"## VIX  close={v['close']}  date={v['date']}  ({v.get('src')})")
    em = header["expected_move"]
    if not em.get("missing"):
        lines.append(f"## Expected move (rough)  ~{em['pts']} pts  [{em['method']}]")
    lines.append("")
    g = header["gamma"]
    if not g.get("missing"):
        flag = "STALE — LEVELS EXCLUDED" if g["stale"] else "OK"
        lines.append(f"## Gamma  {flag}  age_min={g['age_min']}  asof={g.get('asof_ct')}")
        lines.append(f"- net_gex={g.get('net_gex')} spot={g.get('spot')} source={g.get('source')}")
        if g.get("levels_usable"):
            lines.append(f"- call_wall={g.get('call_wall')} put_wall={g.get('put_wall')} flip={g.get('flip')}")
        else:
            lines.append("- levels omitted (stale)")
    lines.append("")
    ev = header["events"]
    if not ev.get("missing"):
        lines.append("## Event calendar")
        if ev.get("today"):
            for e in ev["today"]:
                lines.append(f"- TODAY {e['date']} {e.get('time_ct','')} {e['name']}")
        for e in ev.get("upcoming") or []:
            lines.append(f"- {e['date']} {e.get('time_ct','')} {e['name']}")
    lines.append("")
    nq = header["nq_vs_es"]
    if not nq.get("missing"):
        lines.append("## NQ vs ES (approx last 60x1m)")
        lines.append(f"- ES {nq['es_last']} ({nq['es_ret_1h_pct']}%)  NQ {nq['nq_last']} ({nq['nq_ret_1h_pct']}%)")
        lines.append(f"- NQ outperforming: {nq['nq_outperforming']}  ({nq['src']})")
    lines.append("")
    lines.append("Live legal? NO, size 0")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "reports" / "checklist_latest.md"))
    args = ap.parse_args()
    h = build()
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    text = render(h)
    Path(args.out).write_text(text, encoding="utf-8")
    if args.json:
        print(json.dumps(h, indent=2, default=str))
    else:
        print(text)


if __name__ == "__main__":
    main()
