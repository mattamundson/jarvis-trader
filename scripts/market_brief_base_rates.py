#!/usr/bin/env python3
"""State-matched market-brief base rates (analysis-only).

Replaces narrative regime claims with measured, causal (no-lookahead) conditional
probabilities for ES, and emits a probability block the morning brief can publish.

Definitions used everywhere (a strict partition of next-session outcomes):

    continuation = next_close >  signal_close
    failure      = next_close <= signal_close AND next_low  < signal_low
    rotation     = next_close <= signal_close AND next_low  >= signal_low

Safety: no broker, order routing, risk config, kill-switch, .env or symbol-gate change.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import statistics
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SAFETY = {"mode": "ANALYSIS_ONLY", "orders_enabled": False, "risk_config_touched": False}
MODEL_VERSION = "market-brief-base-rates-v1"
DEFAULT_LOOKBACK = "5y"


@dataclass(frozen=True)
class Bar:
    date: str
    open: float
    high: float
    low: float
    close: float


@dataclass
class State:
    label: str
    n: int = 0
    p_continuation: float = 0.0
    p_rotation: float = 0.0
    p_failure: float = 0.0
    p_higher_high: float = 0.0
    p_gap_down: float = 0.0
    p_up_5d: float = 0.0
    median_5d: float = 0.0
    median_mae5: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)


def _fetch(url: str, timeout: int = 25) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 market-brief-base-rates"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_daily(symbol: str, lookback: str = DEFAULT_LOOKBACK) -> list[Bar]:
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol, safe='')}"
        f"?range={lookback}&interval=1d&includePrePost=false"
    )
    payload = _fetch(url)
    res = payload.get("chart", {}).get("result") or []
    if not res:
        raise RuntimeError(f"no chart result for {symbol}")
    node = res[0]
    q = (node.get("indicators", {}).get("quote") or [{}])[0]
    out: list[Bar] = []
    for i, ts in enumerate(node.get("timestamp") or []):
        try:
            o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        except (KeyError, IndexError):
            continue
        if None in (o, h, l, c):
            continue
        out.append(Bar(dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).date().isoformat(),
                       float(o), float(h), float(l), float(c)))
    if len(out) < 60:
        raise RuntimeError(f"too few bars for {symbol}: {len(out)}")
    return out


def classify_state(is_ath_close: bool, vix: float | None, accel5: float | None) -> str:
    """Bucket label for a signal day. Mirrors the states measured in the 2026-09-21 review."""
    if not is_ath_close:
        return "not_ath_close"
    low_vol = vix is not None and vix < 16.0
    if accel5 is None:
        return "ath_close_lowvol_unknown" if low_vol else "ath_close_hivol"
    if low_vol and accel5 > 2.0:
        return "ath_close_lowvol_accel_gt2"
    if low_vol and 0.0 <= accel5 <= 2.0:
        return "ath_close_lowvol_accel_0to2"
    if low_vol:
        return "ath_close_lowvol_other"
    return "ath_close_hivol"


def label_partition(next_close: float, next_low: float, signal_close: float, signal_low: float) -> str:
    if next_close > signal_close:
        return "continuation"
    if next_low < signal_low:
        return "failure"
    return "rotation"


def build_records(bars: list[Bar], vix_by_date: dict[str, float]) -> list[dict[str, Any]]:
    """Causal records: every field for day i uses only data available at day i's close."""
    run_max_close = -math.inf
    recs: list[dict[str, Any]] = []
    for i, b in enumerate(bars):
        accel5 = None if i < 5 else 100.0 * (b.close - bars[i - 5].close) / bars[i - 5].close
        is_ath = b.close > run_max_close
        run_max_close = max(run_max_close, b.close)
        recs.append({
            "i": i, "date": b.date, "close": b.close, "low": b.low, "open": b.open,
            "is_ath_close": is_ath, "accel5": accel5, "vix": vix_by_date.get(b.date),
            "state": classify_state(is_ath, vix_by_date.get(b.date), accel5),
        })
    return recs


def summarize(recs: list[dict[str, Any]], bars: list[Bar], state: str) -> State:
    rows = [r for r in recs if r["state"] == state and r["i"] + 5 < len(bars)]
    s = State(label=state, n=len(rows))
    if not rows:
        return s
    counts = {"continuation": 0, "rotation": 0, "failure": 0}
    high_high = downstream_low = gap_down = up5 = 0
    d5s: list[float] = []
    mae5s: list[float] = []
    for r in rows:
        i = r["i"]
        nxt = bars[i + 1]
        lab = label_partition(nxt.close, nxt.low, r["close"], r["low"])
        counts[lab] += 1
        if nxt.high > bars[i].high:
            high_high += 1
        if nxt.low < r["low"]:
            downstream_low += 1
        if nxt.open < r["open"]:
            gap_down += 1
        c5 = bars[i + 5].close
        d5s.append(100.0 * (c5 - r["close"]) / r["close"])
        if c5 > r["close"]:
            up5 += 1
        mae5s.append(100.0 * (min(x.low for x in bars[i + 1:i + 6]) - r["close"]) / r["close"])
    n = len(rows)
    s.p_continuation = round(100.0 * counts["continuation"] / n, 1)
    s.p_rotation = round(100.0 * counts["rotation"] / n, 1)
    s.p_failure = round(100.0 * counts["failure"] / n, 1)
    s.p_higher_high = round(100.0 * high_high / n, 1)
    s.p_gap_down = round(100.0 * gap_down / n, 1)
    s.p_up_5d = round(100.0 * up5 / n, 1)
    s.median_5d = round(statistics.median(d5s), 2)
    s.median_mae5 = round(statistics.median(mae5s), 2)
    s.raw = {"below_signal_low": round(100.0 * downstream_low / n, 1)}
    return s


def analyze(lookback: str = DEFAULT_LOOKBACK) -> dict[str, Any]:
    es = fetch_daily("ES=F", lookback)
    vix = {b.date: b.close for b in fetch_daily("^VIX", lookback)}
    recs = build_records(es, vix)
    today = recs[-1]

    states = ["__all__", "not_ath_close", "ath_close_hivol", "ath_close_lowvol_accel_0to2",
              "ath_close_lowvol_accel_gt2"]
    table: dict[str, State] = {}
    for st in states:
        if st == "__all__":
            rows = [r for r in recs if r["i"] + 5 < len(es)]
            s = State(label="all_days")
            counts = {"continuation": 0, "rotation": 0, "failure": 0}
            hh = dl = gd = u5 = 0
            d5s, mae5s = [], []
            for r in rows:
                i = r["i"]; nxt = es[i + 1]
                counts[label_partition(nxt.close, nxt.low, r["close"], r["low"])] += 1
                hh += nxt.high > es[i].high
                dl += nxt.low < r["low"]
                gd += nxt.open < r["open"]
                c5 = es[i + 5].close
                d5s.append(100.0 * (c5 - r["close"]) / r["close"])
                u5 += c5 > r["close"]
                mae5s.append(100.0 * (min(x.low for x in es[i + 1:i + 6]) - r["close"]) / r["close"])
            n = len(rows)
            s.n = n
            s.p_continuation = round(100.0 * counts["continuation"] / n, 1)
            s.p_rotation = round(100.0 * counts["rotation"] / n, 1)
            s.p_failure = round(100.0 * counts["failure"] / n, 1)
            s.p_higher_high = round(100.0 * hh / n, 1)
            s.p_gap_down = round(100.0 * gd / n, 1)
            s.p_up_5d = round(100.0 * u5 / n, 1)
            s.median_5d = round(statistics.median(d5s), 2)
            s.median_mae5 = round(statistics.median(mae5s), 2)
            s.raw = {"below_signal_low": round(100.0 * dl / n, 1)}
            table[st] = s
        else:
            table[st] = summarize(recs, es, st)

    matched = table.get(today["state"]) or table["__all__"]
    return {
        "model_version": MODEL_VERSION,
        "safety": SAFETY,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "instrument": "ES=F",
        "lookback": lookback,
        "bars": len(es),
        "span": [es[0].date, es[-1].date],
        "today": {
            "date": today["date"], "close": today["close"], "low": today["low"],
            "is_ath_close": today["is_ath_close"], "vix": today["vix"],
            "accel5_pct": round(today["accel5"], 2) if today["accel5"] is not None else None,
            "state": today["state"],
        },
        "states": {k: {**v.__dict__} for k, v in table.items()},
        "matched_state": matched.label,
        "probabilities": {
            "continuation": matched.p_continuation,
            "rotation": matched.p_rotation,
            "failure": matched.p_failure,
            "sum": round(matched.p_continuation + matched.p_rotation + matched.p_failure, 1),
        },
        "context": {
            "p_higher_high": matched.p_higher_high,
            "p_gap_down": matched.p_gap_down,
            "p_up_5d": matched.p_up_5d,
            "median_5d_pct": matched.median_5d,
            "median_mae5_pct": matched.median_mae5,
            "p_below_signal_low": matched.raw.get("below_signal_low"),
        },
        "limitations": [
            "Daily bars; no true premarket/Globex conditioning yet.",
            "Single-instrument (ES); NQ/VIX cross-conditioning is a follow-up.",
            "Historical base rates are not a forecast; they are the reference distribution.",
        ],
    }


def render(payload: dict[str, Any]) -> str:
    t = payload["today"]; pr = payload["probabilities"]; cx = payload["context"]
    md = [
        "# Market Brief — Measured Base Rates",
        "",
        f"Generated: {payload['generated_at']}  ·  model `{payload['model_version']}`",
        "",
        "## Safety",
        "",
        "- `mode=ANALYSIS_ONLY` · `orders_enabled=false` · `risk_config_touched=false`",
        "- No broker, order routing, risk config, kill-switch, .env or symbol-gate change.",
        "",
        "## Today's state",
        "",
        f"- Date: `{t['date']}`  ·  ES close `{t['close']:.2f}`  ·  low `{t['low']:.2f}`",
        f"- New ATH close: `{t['is_ath_close']}`  ·  VIX `{t['vix']}`  ·  5d accel `{t['accel5_pct']}%`",
        f"- Matched state: `{payload['matched_state']}`  (n={payload['states'][payload['matched_state']]['n']})",
        "",
        "## Probability block (next session)",
        "",
        "| Outcome | Probability |",
        "|---|---:|",
        f"| Continuation (close higher) | **{pr['continuation']}%** |",
        f"| Rotation (down close, holds low) | **{pr['rotation']}%** |",
        f"| Failure (down close, breaks low) | **{pr['failure']}%** |",
        f"| Sum | {pr['sum']}% |",
        "",
        "## Context",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| P(higher high next session) | {cx['p_higher_high']}% |",
        f"| P(gaps below today's open) | {cx['p_gap_down']}% |",
        f"| P(trades below today's low) | {cx['p_below_signal_low']}% |",
        f"| P(up 5 sessions) | {cx['p_up_5d']}% |",
        f"| Median 5-session return | {cx['median_5d_pct']}% |",
        f"| Median 5-session adverse excursion | {cx['median_mae5_pct']}% |",
        "",
        "## State table (causal, no lookahead)",
        "",
        "| State | n | Cont. | Rot. | Fail. | P(higher high) | P(gap down) | P(up 5d) | med 5d | med MAE5 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for v in payload["states"].values():
        md.append(f"| {v['label']} | {v['n']} | {v['p_continuation']} | {v['p_rotation']} | {v['p_failure']} | "
                  f"{v['p_higher_high']} | {v['p_gap_down']} | {v['p_up_5d']} | {v['median_5d']} | {v['median_mae5']} |")
    md += ["", "## Limitations", ""] + [f"- {x}" for x in payload["limitations"]] + ["", "## Machine payload", "", "```json",
          json.dumps(payload, indent=2, sort_keys=True), "```", ""]
    return "\n".join(md)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lookback", default=DEFAULT_LOOKBACK)
    ap.add_argument("--out-dir", default="docs/reports")
    ap.add_argument("--json-out", default=None)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    payload = analyze(a.lookback)
    out = Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    md_path = out / f"MARKET_BRIEF_BASE_RATES_{stamp}.md"
    md_path.write_text(render(payload), encoding="utf-8")
    (out / "MARKET_BRIEF_BASE_RATES_LATEST.md").write_text(render(payload), encoding="utf-8")
    (out / "MARKET_BRIEF_BASE_RATES_LATEST.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    if a.json_out:
        Path(a.json_out).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    if not a.quiet:
        print(json.dumps({"report": str(md_path), "state": payload["matched_state"],
                          "probabilities": payload["probabilities"],
                          "n": payload["states"][payload["matched_state"]]["n"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
