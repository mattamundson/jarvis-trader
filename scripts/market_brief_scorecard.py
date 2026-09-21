#!/usr/bin/env python3
"""Next-day market-brief scorecard (analysis-only).

Closes the loop the subscriber-style brief structurally cannot: it records each
published brief's probabilities, labels the realized outcome, and reports Brier /
hit rates so the brief becomes accountable over time.

Ledger: engine/data/market_brief_scorecard/brief_ledger.jsonl (append-only).
Outcome labels use the same strict partition as market_brief_base_rates:

    continuation = next_close >  signal_close
    failure      = next_close <= signal_close AND next_low < signal_low
    rotation     = next_close <= signal_close AND next_low >= signal_low

Safety: no broker, order routing, risk config, kill-switch, .env or symbol-gate change.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SAFETY = {"mode": "ANALYSIS_ONLY", "orders_enabled": False, "risk_config_touched": False}
MODEL_VERSION = "market-brief-scorecard-v1"
LEDGER = Path("engine/data/market_brief_scorecard/brief_ledger.jsonl")
CLASSES = ("continuation", "rotation", "failure")


@dataclass(frozen=True)
class Bar:
    date: str
    open: float
    high: float
    low: float
    close: float


def fetch_daily(symbol: str, lookback: str = "2y") -> list[Bar]:
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol, safe='')}"
           f"?range={lookback}&interval=1d&includePrePost=false")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 market-brief-scorecard"})
    with urllib.request.urlopen(req, timeout=25) as r:
        payload = json.loads(r.read().decode("utf-8"))
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
    return out


def validate_brief(rec: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    for k in ("date", "symbol", "continuation", "rotation", "failure"):
        if k not in rec:
            errs.append(f"missing field: {k}")
    if errs:
        return errs
    total = rec["continuation"] + rec["rotation"] + rec["failure"]
    if abs(total - 100.0) > 0.5:
        errs.append(f"probabilities must sum to 100 (got {total})")
    for k in CLASSES:
        if not (0.0 <= float(rec[k]) <= 100.0):
            errs.append(f"{k} out of range: {rec[k]}")
    return errs


def append_brief(rec: dict[str, Any], ledger: Path = LEDGER) -> dict[str, Any]:
    errs = validate_brief(rec)
    if errs:
        raise ValueError("; ".join(errs))
    entry = {
        "recorded_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "model_version": MODEL_VERSION,
        "safety": SAFETY,
        **{k: rec[k] for k in ("date", "symbol", "continuation", "rotation", "failure")},
        "signal_close": rec.get("signal_close"),
        "signal_low": rec.get("signal_low"),
        "state": rec.get("state"),
        "source": rec.get("source", "manual"),
    }
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")
    return entry


def read_ledger(ledger: Path = LEDGER) -> list[dict[str, Any]]:
    if not ledger.exists():
        return []
    out = []
    for line in ledger.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def label_partition(next_close: float, next_low: float, signal_close: float, signal_low: float) -> str:
    if next_close > signal_close:
        return "continuation"
    if next_low < signal_low:
        return "failure"
    return "rotation"


def score(entries: list[dict[str, Any]], lookback: str = "2y") -> dict[str, Any]:
    cache: dict[str, list[Bar]] = {}
    scored: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []

    for e in entries:
        sym = e.get("symbol", "ES=F")
        bars = cache.get(sym) or fetch_daily(sym, lookback)
        cache[sym] = bars
        by_date = {b.date: b for b in bars}
        sig = by_date.get(e["date"])
        idx = bars.index(sig) if sig else -1
        if idx < 0 or idx + 1 >= len(bars):
            pending.append({**e, "reason": "no realized next session yet"})
            continue
        sig_close = e.get("signal_close") if e.get("signal_close") is not None else sig.close
        sig_low = e.get("signal_low") if e.get("signal_low") is not None else sig.low
        nxt = bars[idx + 1]
        realized = label_partition(nxt.close, nxt.low, sig_close, sig_low)
        probs = {k: float(e[k]) / 100.0 for k in CLASSES}
        brier = sum((probs[k] - (1.0 if realized == k else 0.0)) ** 2 for k in CLASSES)
        d1 = 100.0 * (nxt.close - sig_close) / sig_close
        scored.append({
            "date": e["date"], "symbol": sym, "realized": realized,
            "predicted": {k: e[k] for k in CLASSES},
            "top_pick": max(CLASSES, key=lambda k: e[k]),
            "top_pick_correct": max(CLASSES, key=lambda k: e[k]) == realized,
            "brier": round(brier, 6),
            "next_close_pct": round(d1, 3),
        })

    n = len(scored)
    agg: dict[str, Any] = {"n_scored": n, "n_pending": len(pending)}
    if n:
        agg["mean_brier"] = round(sum(s["brier"] for s in scored) / n, 6)
        agg["top_pick_hit_rate"] = round(100.0 * sum(1 for s in scored if s["top_pick_correct"]) / n, 1)
        agg["realized_counts"] = {k: sum(1 for s in scored if s["realized"] == k) for k in CLASSES}
        base = {k: sum(1 for s in scored if s["realized"] == k) / n for k in CLASSES}
        agg["base_rates"] = {k: round(100.0 * v, 1) for k, v in base.items()}
        agg["brier_vs_base_rate"] = {
            k: round(sum((s["predicted"][k] / 100.0 - (1.0 if s["realized"] == k else 0.0)) ** 2 for s in scored) / n, 6)
            for k in CLASSES
        }
        # skill vs always predicting the base rate
        agg["brier_skill_score"] = {}
        for k in CLASSES:
            ref = sum((base[k] - (1.0 if s["realized"] == k else 0.0)) ** 2 for s in scored) / n
            model = agg["brier_vs_base_rate"][k]
            agg["brier_skill_score"][k] = round(1.0 - model / ref, 4) if ref > 0 else None

    return {
        "model_version": MODEL_VERSION, "safety": SAFETY,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "aggregate": agg, "scored": scored, "pending": pending,
        "limitations": [
            "Scores are only as honest as the ledger; missing briefs bias the sample.",
            "Small n early on: treat Brier/ skill numbers as directional until n is meaningful.",
            "Daily-bar outcome labels; no intraday touch scoring yet.",
        ],
    }


def render(result: dict[str, Any]) -> str:
    a = result["aggregate"]
    md = [
        "# Market Brief Scorecard", "",
        f"Generated: {result['generated_at']}  ·  model `{result['model_version']}`", "",
        "## Safety", "",
        "- `mode=ANALYSIS_ONLY` · `orders_enabled=false` · `risk_config_touched=false`", "",
        "## Aggregate", "",
        f"- Briefs scored: **{a['n_scored']}**  ·  pending (no outcome yet): **{a['n_pending']}**",
    ]
    if a["n_scored"]:
        md += [
            f"- Mean Brier (3-class): **{a['mean_brier']}**",
            f"- Top-pick hit rate: **{a['top_pick_hit_rate']}%**",
            f"- Realized counts: `{a['realized_counts']}`",
            f"- Realized base rates: `{a['base_rates']}`",
            "",
            "### Brier skill vs base-rate forecast (positive = better than always guessing the base rate)",
            "",
            "| Class | Model Brier | Base-rate Brier | Skill |",
            "|---|---:|---:|---:|",
        ]
        for k in CLASSES:
            md.append(f"| {k} | {a['brier_vs_base_rate'][k]} | — | {a['brier_skill_score'][k]} |")
        md += ["", "## Scored briefs", "",
               "| Date | Predicted (C/R/F) | Top pick | Realized | Hit | Brier | Next close |",
               "|---|---|---|---|---|---:|---:|"]
        for s in result["scored"]:
            p = s["predicted"]
            md.append(f"| {s['date']} | {p['continuation']}/{p['rotation']}/{p['failure']} | {s['top_pick']} | "
                      f"{s['realized']} | {'yes' if s['top_pick_correct'] else 'no'} | {s['brier']} | {s['next_close_pct']}% |")
    if result["pending"]:
        md += ["", "## Pending", ""]
        for p in result["pending"]:
            md.append(f"- {p['date']} {p.get('symbol')}: {p.get('reason')}")
    md += ["", "## Limitations", ""] + [f"- {x}" for x in result["limitations"]]
    md += ["", "## Machine payload", "", "```json", json.dumps(result, indent=2, sort_keys=True), "```", ""]
    return "\n".join(md)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--record", action="store_true", help="record a new brief into the ledger")
    ap.add_argument("--date"); ap.add_argument("--symbol", default="ES=F")
    ap.add_argument("--continuation", type=float); ap.add_argument("--rotation", type=float)
    ap.add_argument("--failure", type=float)
    ap.add_argument("--signal-close", type=float); ap.add_argument("--signal-low", type=float)
    ap.add_argument("--state")
    ap.add_argument("--ledger", default=str(LEDGER))
    ap.add_argument("--out-dir", default="docs/reports")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    ledger = Path(a.ledger)

    if a.record:
        for req in ("date", "continuation", "rotation", "failure"):
            if getattr(a, req) is None:
                ap.error(f"--{req} is required with --record")
        entry = append_brief({
            "date": a.date, "symbol": a.symbol, "continuation": a.continuation,
            "rotation": a.rotation, "failure": a.failure,
            "signal_close": a.signal_close, "signal_low": a.signal_low,
            "state": a.state, "source": "cli",
        }, ledger)
        if not a.quiet:
            print(json.dumps({"recorded": entry}, sort_keys=True))

    result = score(read_ledger(ledger))
    out = Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    (out / f"MARKET_BRIEF_SCORECARD_{stamp}.md").write_text(render(result), encoding="utf-8")
    (out / "MARKET_BRIEF_SCORECARD_LATEST.md").write_text(render(result), encoding="utf-8")
    (out / "MARKET_BRIEF_SCORECARD_LATEST.json").write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    if not a.quiet:
        print(json.dumps({"aggregate": result["aggregate"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
