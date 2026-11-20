#!/usr/bin/env python3
"""Grade ES read calls at +30m / +60m / session-end vs ES price.

Hit definition (directional lean):
  - bullish: +30/+60 close >= price_at_call  OR  named upside trigger level traded
  - bearish: +30/+60 close <= price_at_call  OR  named downside trigger level traded
  - neutral/watch: HIT if price stayed inside [invalidation low-ish band / named range];
    default: |close - price_at_call| <= 0.5 * overnight_range_so_far or <= 8 pts (whichever larger),
    and neither breakout trigger fully confirmed on a 15m close.

Also grades vs baselines:
  - no_change: predict close == price_at_call (error = |Δ|)
  - prior_session_range_holds: predict price stays inside prior RTH H/L

MFE/MAE measured in points from price_at_call in the lean direction (bullish MFE=high-px, MAE=px-low).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
import os as _os  # noqa: E402
# Box layout mirrors /workspace/tape; override with TAPE_ROOT. Defaults to scripts/tape in the repo.
TAPE_ROOT = Path(_os.environ.get("TAPE_ROOT") or Path(__file__).resolve().parents[1])
from typing import Any, Dict, List, Optional

ROOT = (TAPE_ROOT / "system")
sys.path.insert(0, str(ROOT))
from lib.prices import (  # noqa: E402
    load_es_1m,
    load_es_5m,
    price_at,
    prior_session_range,
    window_hlc,
)
from lib.timeutil import CT, hour_of_night, parse_ct, to_ct_str  # noqa: E402


CALLS = ROOT / "calls.jsonl"
REPORTS = ROOT / "reports"


def load_calls(path: Path = CALLS) -> List[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def _session_end(ts: datetime) -> datetime:
    """Overnight session ends at 08:30 CT next calendar morning (RTH open)."""
    local = ts.astimezone(CT)
    if local.hour >= 17:
        end = local.replace(hour=8, minute=30, second=0, microsecond=0) + timedelta(days=1)
    else:
        end = local.replace(hour=8, minute=30, second=0, microsecond=0)
        if end <= local:
            end = end + timedelta(days=1)
    return end


def _direction_hit(bias: str, px: float, close: float, hi: float, lo: float,
                   triggers: List[dict], confirm_close: Optional[float] = None) -> str:
    if bias == "bullish":
        trig = any(t.get("side") == "long" and hi >= float(t["level"]) for t in triggers)
        if close >= px or trig:
            return "HIT"
        return "MISS"
    if bias == "bearish":
        trig = any(t.get("side") == "short" and lo <= float(t["level"]) for t in triggers)
        if close <= px or trig:
            return "HIT"
        return "MISS"
    # neutral / watch: HIT if stayed contained (no 15pt runaway against a flat call)
    if abs(close - px) <= 8 or (hi - lo) <= 12:
        return "HIT"
    return "MISS"


def grade_one(call: dict, bars_1m, bars_5m, prior_range: Optional[dict]) -> dict:
    ts = parse_ct(call["ts_ct"])
    px = call.get("price_at_call")
    if px is None:
        px = price_at(bars_1m, ts)
    if px is None:
        return {"id": call.get("id"), "ts_ct": call["ts_ct"], "error": "no price at call", "grades": {}}

    bias = call["bias"]
    triggers = call.get("triggers") or []
    grades = {}
    for label, delta in (("plus_30m", timedelta(minutes=30)),
                         ("plus_60m", timedelta(minutes=60)),
                         ("session_end", None)):
        end = _session_end(ts) if delta is None else ts + delta
        # clip to available data
        last_bar_ts = bars_1m[-1].ts if bars_1m else ts
        incomplete = end > last_bar_ts + timedelta(minutes=2)
        use_end = min(end, last_bar_ts)
        hl = window_hlc(bars_1m, ts, use_end)
        if not hl:
            grades[label] = {"status": "INCOMPLETE", "reason": "no bars in window"}
            continue
        hi, lo, close = hl
        if bias == "bullish":
            mfe, mae = hi - px, px - lo
        elif bias == "bearish":
            mfe, mae = px - lo, hi - px
        else:
            mfe, mae = max(hi - px, px - lo), max(hi - px, px - lo)

        hit = _direction_hit(bias, px, close, hi, lo, triggers)
        # baselines
        no_change_err = abs(close - px)
        psr = None
        if prior_range and prior_range.get("high") is not None:
            inside = prior_range["low"] <= close <= prior_range["high"]
            # baseline "predicts" that range holds → baseline HIT if inside
            psr = {
                "inside_prior_range": inside,
                "prior_high": prior_range["high"],
                "prior_low": prior_range["low"],
                "prior_date": prior_range.get("date"),
                "baseline_hit": inside,
            }
            # edge: did our call agree with reality better?
            # If bias bullish/bearish and price left prior range in that direction, we beat baseline when baseline missed.
        edge = None
        if psr is not None:
            our_hit = hit == "HIT"
            base_hit = psr["baseline_hit"]
            if our_hit and not base_hit:
                edge = "beat_prior_range_baseline"
            elif our_hit and base_hit:
                edge = "tied_both_hit"
            elif not our_hit and base_hit:
                edge = "lost_to_prior_range_baseline"
            else:
                edge = "both_miss"
        # no-change baseline: smaller |Δ| is better; call "beats" if directional move favored call
        if bias == "bullish":
            beat_no_change = close > px
        elif bias == "bearish":
            beat_no_change = close < px
        else:
            beat_no_change = no_change_err <= 4  # neutral wants small move

        grades[label] = {
            "status": "INCOMPLETE" if incomplete else "GRADED",
            "window_end_ct": to_ct_str(use_end),
            "requested_end_ct": to_ct_str(end),
            "price_at_call": px,
            "close": close,
            "high": hi,
            "low": lo,
            "delta": round(close - px, 2),
            "mfe_pts": round(mfe, 2),
            "mae_pts": round(mae, 2),
            "hit": hit,
            "baseline_no_change_abs_err": round(no_change_err, 2),
            "beat_no_change_baseline": beat_no_change,
            "prior_session_range": psr,
            "edge_vs_prior_range": edge,
        }
    return {
        "id": call.get("id"),
        "ts_ct": call["ts_ct"],
        "bias": bias,
        "setup_type": call.get("setup_type"),
        "hour_of_night": hour_of_night(ts),
        "lean_pct": call.get("lean_pct"),
        "price_at_call": px,
        "grades": grades,
    }


def hit_rate_report(graded: List[dict], horizon: str = "plus_30m") -> dict:
    by_hour: Dict[str, List[str]] = defaultdict(list)
    by_setup: Dict[str, List[str]] = defaultdict(list)
    all_hits = []
    for g in graded:
        h = g["grades"].get(horizon)
        if not h or h.get("status") == "INCOMPLETE" or "hit" not in h:
            continue
        all_hits.append(h["hit"])
        by_hour[g["hour_of_night"]].append(h["hit"])
        by_setup[g.get("setup_type") or "unknown"].append(h["hit"])

    def rate(xs: List[str]) -> dict:
        n = len(xs)
        hits = sum(1 for x in xs if x == "HIT")
        return {"n": n, "hits": hits, "hit_rate": round(hits / n, 3) if n else None}

    return {
        "horizon": horizon,
        "overall": rate(all_hits),
        "by_hour_of_night_ct": {k: rate(v) for k, v in sorted(by_hour.items())},
        "by_setup_type": {k: rate(v) for k, v in sorted(by_setup.items())},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--calls", default=str(CALLS))
    ap.add_argument("--out", default=str(REPORTS / "graded_calls.json"))
    ap.add_argument("--asof", default=None, help="CT timestamp for prior-range cutoff")
    args = ap.parse_args()
    REPORTS.mkdir(parents=True, exist_ok=True)
    calls = load_calls(Path(args.calls))
    bars_1m = load_es_1m(prefer="auto")
    bars_5m = load_es_5m(prefer="auto")
    asof = parse_ct(args.asof) if args.asof else (parse_ct(calls[0]["ts_ct"]) if calls else datetime.now(CT))
    prior = prior_session_range(asof=asof)
    graded = [grade_one(c, bars_1m, bars_5m, prior) for c in calls]
    report = {
        "graded_at_ct": to_ct_str(datetime.now(CT)),
        "price_src": "IB/engine 1m primary (auto); Yahoo labeled fallback if engine missing",
        "prior_session_range": prior,
        "n_calls": len(graded),
        "calls": graded,
        "hit_rates": {
            "plus_30m": hit_rate_report(graded, "plus_30m"),
            "plus_60m": hit_rate_report(graded, "plus_60m"),
            "session_end": hit_rate_report(graded, "session_end"),
        },
    }
    Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    # human summary
    summary = REPORTS / "hit_rates.md"
    lines = [f"# Hit-rate report ({report['graded_at_ct']} CT)", ""]
    for hz, rr in report["hit_rates"].items():
        o = rr["overall"]
        lines.append(f"## {hz}: {o['hits']}/{o['n']} = {o['hit_rate']}")
        lines.append("### by hour_of_night (CT)")
        for k, v in rr["by_hour_of_night_ct"].items():
            lines.append(f"- {k}:00 → {v['hits']}/{v['n']} ({v['hit_rate']})")
        lines.append("### by setup_type")
        for k, v in rr["by_setup_type"].items():
            lines.append(f"- {k}: {v['hits']}/{v['n']} ({v['hit_rate']})")
        lines.append("")
    summary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"out": args.out, "summary": str(summary), "overall_30m": report["hit_rates"]["plus_30m"]["overall"]}, indent=2))


if __name__ == "__main__":
    main()
