#!/usr/bin/env python3
"""Score today's ES session for trend-vs-balance (0DTE premium guidance).

Reads /workspace/tape/context/es-context-latest.md. Never invents numbers.
Point rules match backtest.score_row (holdout-validated). Stage-2 IB/open
points apply only when those fields are supplied.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, asdict, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import os as _os  # noqa: E402
# Box layout mirrors /workspace/tape; override with TAPE_ROOT. Defaults to scripts/tape in the repo.
TAPE_ROOT = Path(_os.environ.get("TAPE_ROOT") or Path(__file__).resolve().parents[2])

REGIME = Path(__file__).resolve().parent
CONTEXT = (TAPE_ROOT / "context/es-context-latest.md")
LOOKUP_PATH = REGIME / "reports" / "backtest_results.json"


@dataclass
class Inputs:
    session_date: str
    dow: Optional[int] = None
    vix_prior: Optional[float] = None
    vix9: Optional[float] = None
    vix_chg: Optional[float] = None
    ovn_range: Optional[float] = None
    avg_range_20: Optional[float] = None
    gap_in_range: Optional[int] = None
    gap_prior_range: Optional[float] = None
    is_event: int = 0
    is_nfp: int = 0
    opex: int = 0
    prior_was_trend: Optional[int] = None
    prior_was_balance: Optional[int] = None
    prior_nr4: Optional[int] = None
    prior_inside: Optional[int] = None
    gex_sign: Optional[int] = None
    gex_net_b: Optional[float] = None
    gex_age_min: Optional[int] = None
    gex_stale: bool = True
    implied_move: Optional[float] = None
    # stage-2 (optional)
    ib_range: Optional[float] = None
    open_type: Optional[str] = None
    otf_count: Optional[int] = None
    notes: List[str] = field(default_factory=list)


def _f(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        return float(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return None


def parse_context(text: str) -> Inputs:
    notes: List[str] = []
    # Only the "Last 5 RTH sessions" table — not NFP history tables later in the file.
    sec = re.search(r"## 1\) Last 5 RTH sessions(.*?)(?:\n## |\Z)", text, re.S)
    table_blob = sec.group(1) if sec else text
    rows = re.findall(
        r"\|\s*(\d{4}-\d{2}-\d{2})\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)",
        table_blob,
    )
    prior_high = prior_low = prior_close = None
    ranges = []
    if rows:
        last = rows[-1]
        prior_high, prior_low = _f(last[1]), _f(last[2])
        prior_close = _f(last[4]) or _f(last[3])
        for r in rows:
            h, l = _f(r[1]), _f(r[2])
            if h is not None and l is not None:
                ranges.append(h - l)
    avg_range_20 = sum(ranges) / len(ranges) if len(ranges) >= 5 else None
    if avg_range_20 is not None:
        notes.append(f"avg_range_20 proxied from last {len(ranges)} RTH sessions in context (not full 20d)")
    else:
        notes.append("avg_range_20 unavailable from context")

    onh = re.search(r"\|\s*ONH\s*\|\s*([\d.]+)", text)
    onl = re.search(r"\|\s*ONL\s*\|\s*([\d.]+)", text)
    ovn_range = (_f(onh.group(1)) - _f(onl.group(1))) if onh and onl else None

    vix = None
    m = re.search(r"VIX spot:\*\*\s*([\d.]+)", text)
    if m:
        vix = _f(m.group(1))
    vix9 = None
    m = re.search(r"VIX9D:\*\*\s*([\d.]+)", text)
    if m:
        vix9 = _f(m.group(1))

    vix_days = re.findall(
        r"(\d{4}-\d{2}-\d{2}):\s*[\d.]+ / [\d.]+ / [\d.]+ / ([\d.]+)", text
    )
    vix_chg = None
    if len(vix_days) >= 2:
        last_c, prev_c = _f(vix_days[-1][1]), _f(vix_days[-2][1])
        if last_c is not None and prev_c is not None:
            vix_chg = last_c - prev_c
            if vix is None:
                vix = last_c

    impl = None
    m = re.search(r"Implied ES move\*\*\s*\|\s*\*\*±([\d.]+)\s*pts", text)
    if not m:
        m = re.search(r"Implied ES move.*?±([\d.]+)", text)
    if m:
        impl = _f(m.group(1))

    gex_net = None
    m = re.search(r"Net GEX\s*\|\s*([+-]?[\d.]+)\s*B", text)
    if m:
        gex_net = _f(m.group(1))
    gex_age = None
    m = re.search(r"Snapshot age\s*\|\s*\*\*(\d+)\s*min", text)
    if m:
        gex_age = int(m.group(1))
    stale = True if gex_age is None else gex_age > 60
    if gex_age is not None:
        notes.append(f"GEX age {gex_age} min; {'STALE — overlay only, not in fitted points' if stale else 'fresh'}")

    is_nfp = 1 if re.search(r"\bNFP\b", text) else 0
    is_event = is_nfp
    if re.search(r"\bCPI\b", text) and "Implied" not in text[:200]:
        pass  # NFP context dominates today

    session_date = None
    if rows:
        last_d = date.fromisoformat(rows[-1][0])
        nd = last_d + timedelta(days=1)
        while nd.weekday() >= 5:
            nd += timedelta(days=1)
        session_date = nd.isoformat()

    last_px = None
    m = re.search(r"\|\s*Last\s*\|\s*([\d.]+)", text)
    if m:
        last_px = _f(m.group(1))
    gap_in_range = gap_prior_range = None
    if last_px is not None and prior_high is not None and prior_low is not None and prior_close is not None:
        gap_in_range = 1 if prior_low <= last_px <= prior_high else 0
        pr = prior_high - prior_low
        if pr > 0:
            gap_prior_range = abs(last_px - prior_close) / pr

    prior_was_trend = prior_was_balance = None
    if ranges and prior_high is not None and prior_low is not None and prior_close is not None:
        pr = prior_high - prior_low
        avg = avg_range_20 or pr
        pos = (prior_close - prior_low) / pr if pr > 0 else 0.5
        outer = pos <= 0.2 or pos >= 0.8
        wide = pr >= 1.2 * avg
        prior_was_trend = 1 if (outer and wide) else 0
        prior_was_balance = 1 if (0.25 <= pos <= 0.75 and pr < avg) else 0
        notes.append(
            f"prior heuristic range={pr:.1f} avg={avg:.1f} close_pos={pos:.2f} "
            f"trend={prior_was_trend} bal={prior_was_balance}"
        )

    opex = 0
    dow = None
    if session_date:
        d = date.fromisoformat(session_date)
        dow = d.weekday()
        if d.weekday() == 4 and 15 <= d.day <= 21:
            opex = 1

    # VIX>=25 note
    if vix is not None and vix >= 25:
        notes.append(
            "VIX>=25: holdout FAILED on our sample — no score points from this cut "
            "(Mechaniq: searched VIX gates overfit). Still a live risk flag for short premium."
        )

    return Inputs(
        session_date=session_date or "unknown",
        dow=dow,
        vix_prior=vix,
        vix9=vix9,
        vix_chg=vix_chg,
        ovn_range=ovn_range,
        avg_range_20=avg_range_20,
        gap_in_range=gap_in_range,
        gap_prior_range=gap_prior_range,
        is_event=is_event,
        is_nfp=is_nfp,
        opex=opex,
        prior_was_trend=prior_was_trend,
        prior_was_balance=prior_was_balance,
        gex_sign=(-1 if gex_net is not None and gex_net < 0 else 1 if gex_net and gex_net > 0 else None),
        gex_net_b=gex_net,
        gex_age_min=gex_age,
        gex_stale=stale,
        implied_move=impl,
        notes=notes,
    )


def compute_raw_score(inp: Inputs, stage2: bool = False) -> Tuple[int, List[dict], List[str]]:
    fired: List[dict] = []
    caveats = list(inp.notes)
    s = 0

    if inp.is_event:
        s += 2
        fired.append({"rule": "event_day", "pts": 2})
    if inp.is_nfp:
        # event already +2; NFP not double-counted in backtest score_row
        pass

    if inp.dow in (2, 3):
        s += 1
        fired.append({"rule": "wed_thu", "pts": 1, "value": inp.dow})
    if inp.dow == 0:
        s -= 2
        fired.append({"rule": "monday", "pts": -2})

    if inp.vix_prior is not None:
        vx = inp.vix_prior
        if vx < 15:
            s -= 1
            fired.append({"rule": "vix_lt_15", "pts": -1, "value": vx})
        elif 15 <= vx < 20:
            s += 1
            fired.append({"rule": "vix_15_20", "pts": 1, "value": vx})
        elif 20 <= vx < 25:
            s -= 1
            fired.append({"rule": "vix_20_25", "pts": -1, "value": vx})
        elif vx >= 25:
            caveats.append("VIX>=25 contributes 0 points (holdout failed)")

    ovn_atr = None
    if inp.ovn_range is not None and inp.avg_range_20:
        ovn_atr = inp.ovn_range / inp.avg_range_20
    else:
        caveats.append("ovn_atr unavailable")
    if ovn_atr is not None:
        if ovn_atr < 0.5:
            s -= 1
            fired.append({"rule": "quiet_overnight", "pts": -1, "value": round(ovn_atr, 2)})
        elif 0.5 <= ovn_atr < 0.75:
            s += 1
            fired.append({"rule": "mod_overnight", "pts": 1, "value": round(ovn_atr, 2)})

    if inp.opex:
        s -= 1
        fired.append({"rule": "opex", "pts": -1})
    if inp.vix_chg is not None and inp.vix_chg >= 2:
        s -= 1
        fired.append({"rule": "vix_spike", "pts": -1, "value": round(inp.vix_chg, 2)})
    if inp.gap_prior_range is not None and inp.gap_prior_range >= 0.5:
        s += 1
        fired.append({"rule": "wide_gap", "pts": 1, "value": round(inp.gap_prior_range, 2)})

    # GEX: live overlay only when fresh — not in fitted historical points
    if not inp.gex_stale and inp.gex_sign is not None:
        if inp.gex_sign < 0:
            s += 1
            fired.append({"rule": "fresh_short_gex_overlay", "pts": 1, "value": inp.gex_net_b})
            caveats.append("fresh short GEX overlay (+1) — thin hist sample; mechanistic prior only")
        else:
            s -= 1
            fired.append({"rule": "fresh_long_gex_overlay", "pts": -1, "value": inp.gex_net_b})
    elif inp.gex_net_b is not None:
        caveats.append(f"GEX {inp.gex_net_b}B age={inp.gex_age_min}m ignored in points (stale)")

    if inp.implied_move is not None and inp.avg_range_20:
        caveats.append(
            f"implied_move ±{inp.implied_move} vs avg_range~{inp.avg_range_20:.0f} "
            f"(ratio {inp.implied_move / inp.avg_range_20:.2f}) — not in point score (no hist straddles)"
        )

    if stage2:
        ib_atr = None
        if inp.ib_range is not None and inp.avg_range_20:
            ib_atr = inp.ib_range / inp.avg_range_20
        if ib_atr is not None:
            if ib_atr <= 0.35:
                s += 2
                fired.append({"rule": "narrow_ib", "pts": 2, "value": round(ib_atr, 2)})
            elif 0.50 < ib_atr <= 0.70:
                s -= 1
                fired.append({"rule": "midwide_ib", "pts": -1, "value": round(ib_atr, 2)})
        if inp.open_type == "open_drive":
            s -= 1
            fired.append({"rule": "open_drive", "pts": -1})
        elif inp.open_type == "open_auction":
            s += 1
            fired.append({"rule": "open_auction", "pts": 1})
        elif inp.open_type == "open_test_drive":
            s += 1
            fired.append({"rule": "open_test_drive", "pts": 1})
        if inp.otf_count is not None and inp.otf_count >= 2:
            s += 1
            fired.append({"rule": "otf_ge2", "pts": 1, "value": inp.otf_count})

    caveats.append(
        "Vilkov 0DTE: iron condors can be +gross / −net after realistic bid-ask. "
        "Day-type lean ≠ license to sell premium."
    )
    return s, fired, caveats


def raw_to_display(raw: int) -> int:
    if raw <= -2:
        return 0
    if raw <= 0:
        return 2
    if raw <= 2:
        return 5
    if raw <= 4:
        return 7
    return 10


def lookup_probs(display: int, results_path: Path = LOOKUP_PATH) -> dict:
    key = "low" if display <= 3 else ("mid" if display <= 6 else "high")
    if results_path.exists():
        try:
            res = json.loads(results_path.read_text(encoding="utf-8"))
            for b in (res.get("oos_score_preopen") or {}).get("buckets") or []:
                if b.get("bucket") == key and b.get("trend_rate") is not None:
                    return {
                        "trend_p": b["trend_rate"],
                        "balance_p": b.get("balance_rate"),
                        "mean_range_atr": b.get("mean_range_atr"),
                        "source": "oos_score_preopen",
                        "n": b.get("n"),
                    }
        except (json.JSONDecodeError, KeyError, TypeError):
            pass
    defaults = {
        "low": (0.36, 0.34),
        "mid": (0.32, 0.37),
        "high": (0.47, 0.26),
    }
    tr, bal = defaults[key]
    return {"trend_p": tr, "balance_p": bal, "source": "fallback", "n": None, "mean_range_atr": None}


def advice(display: int, trend_p: Optional[float], inp: Inputs) -> List[str]:
    lines = []
    if display >= 7:
        lines.append(
            "TREND lean: avoid selling naked premium. Prefer defined-risk long vol / sit out if unsure."
        )
    elif display <= 3:
        lines.append(
            "BALANCE lean: decay can favor defined-risk short premium — still size small; "
            "Vilkov says gross winners often die after costs."
        )
    else:
        lines.append(
            "MIXED: no strong pre-open edge. Prefer waiting for IB (09:30 CT stage-2) or staying flat."
        )
    if inp.is_event:
        lines.append("Event day: practitioner consensus is skip short 0DTE through the print.")
    if inp.vix_prior is not None and inp.vix_prior >= 25:
        lines.append(
            f"VIX {inp.vix_prior}: selling premium here carries fat left-tail risk even if the day balances."
        )
    if inp.gex_stale and inp.gex_net_b is not None and inp.gex_net_b < 0:
        lines.append("Stale short GEX: mechanistic trend bias, but age too high to count as a score input.")
    lines.append("Live legal? NO, size 0")
    return lines


def score_today(context_path: Path = CONTEXT, stage2: bool = False) -> dict:
    if not context_path.exists():
        return {"error": f"context missing: {context_path}", "Live legal?": "NO, size 0"}
    inp = parse_context(context_path.read_text(encoding="utf-8"))
    raw, fired, caveats = compute_raw_score(inp, stage2=stage2)
    display = raw_to_display(raw)
    probs = lookup_probs(display)
    ovn_atr = None
    if inp.ovn_range is not None and inp.avg_range_20:
        ovn_atr = round(inp.ovn_range / inp.avg_range_20, 3)
    return {
        "session_date": inp.session_date,
        "stage": "stage2_ib" if stage2 else "preopen",
        "inputs": {k: v for k, v in asdict(inp).items() if k != "notes"},
        "derived": {"ovn_atr": ovn_atr, "vix9_ratio": round(inp.vix9 / inp.vix_prior, 3) if inp.vix9 and inp.vix_prior else None},
        "raw_score": raw,
        "display_score_0_10": display,
        "fired_rules": fired,
        "trend_probability": probs.get("trend_p"),
        "balance_probability": probs.get("balance_p"),
        "mean_range_atr_lookup": probs.get("mean_range_atr"),
        "prob_source": probs.get("source"),
        "prob_n": probs.get("n"),
        "caveats": caveats,
        "advice": advice(display, probs.get("trend_p"), inp),
        "Live legal?": "NO, size 0",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--context", default=str(CONTEXT))
    ap.add_argument("--stage2", action="store_true")
    ap.add_argument("--out", default=str(REGIME / "reports" / "score_today.json"))
    args = ap.parse_args()
    out = score_today(Path(args.context), stage2=args.stage2)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
