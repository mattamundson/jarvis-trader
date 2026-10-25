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
DEFAULT_SYMBOL = "ES=F"  # the base-rate table is ES-specific
DEFAULT_LOOKBACK = "5y"
WALKFORWARD_VERDICT = {
    "study": "market-brief-walkforward-v1",
    "n": 1197,
    "mean_brier_model": 0.594619,
    "mean_brier_base": 0.596765,
    "mean_brier_uniform": 0.666667,
    "paired_diff_base_minus_model": 0.002146,
    "paired_ci95": [-0.002225, 0.006517],
    "paired_t": 0.962,
    "model_beats_base": False,
    "verdict": "state conditioning has no measurable edge over the trailing base rate",
}


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


def _class_rates(counts: dict[str, int], n: int) -> tuple[float, float, float]:
    """Percentages that sum to exactly 100.0, via largest-remainder rounding.

    Rounding each class independently produces totals like 99.9, which contradicts the
    published contract that the probability block sums to 100 -- and a 99.9 total is
    itself a signal that something upstream is wrong.
    """
    keys = ("continuation", "rotation", "failure")
    if n <= 0:
        return 0.0, 0.0, 0.0
    exact = {k: 1000.0 * counts[k] / n for k in keys}   # in tenths of a percent
    base = {k: math.floor(exact[k]) for k in keys}
    residual = round(1000 - sum(base.values()))
    order = sorted(keys, key=lambda k: exact[k] - base[k], reverse=True)
    for i in range(residual):
        base[order[i % 3]] += 1
    return tuple(round(base[k] / 10.0, 1) for k in keys)  # type: ignore[return-value]


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
    s.p_continuation, s.p_rotation, s.p_failure = _class_rates(counts, n)
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
            s.p_continuation, s.p_rotation, s.p_failure = _class_rates(counts, n)
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
    base = table["__all__"]
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
        "published_state": "__all__",
        "matched_state": matched.label,
        "probability_source": {
            "primary": "trailing_unconditional_base_rate",
            "conditional_status": "provisional_no_measured_edge",
            "rationale": "No-lookahead walk-forward found no measurable Brier improvement from state conditioning over the trailing base rate.",
            "walkforward": WALKFORWARD_VERDICT,
        },
        "probabilities": {
            "continuation": base.p_continuation,
            "rotation": base.p_rotation,
            "failure": base.p_failure,
            "sum": round(base.p_continuation + base.p_rotation + base.p_failure, 1),
        },
        "context": {
            "p_higher_high": base.p_higher_high,
            "p_gap_down": base.p_gap_down,
            "p_up_5d": base.p_up_5d,
            "median_5d_pct": base.median_5d,
            "median_mae5_pct": base.median_mae5,
            "p_below_signal_low": base.raw.get("below_signal_low"),
        },
        "conditional_diagnostic": {
            "state": matched.label,
            "n": matched.n,
            "status": "provisional_no_measured_edge",
            "publish_as_edge": False,
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
        },
        "limitations": [
            "Daily bars; no true premarket/Globex conditioning yet.",
            "Single-instrument (ES); NQ/VIX cross-conditioning is a follow-up.",
            "Historical base rates are not a forecast; they are the reference distribution.",
            "State conditioning is shown only as a provisional diagnostic because walk-forward testing found no measurable edge over the base rate.",
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
        f"- Published state: `{payload['published_state']}`  (n={payload['states'][payload['published_state']]['n']})",
        f"- Matched state diagnostic: `{payload['matched_state']}`  (n={payload['states'][payload['matched_state']]['n']})",
        "",
        "## Published probability block (next session)",
        "",
        "Primary source: **trailing unconditional base rate**. The matched-state block is provisional only; the no-lookahead walk-forward did not prove incremental edge.",
        "",
        "| Outcome | Probability |",
        "|---|---:|",
        f"| Continuation (close higher) | **{pr['continuation']}%** |",
        f"| Rotation (down close, holds low) | **{pr['rotation']}%** |",
        f"| Failure (down close, breaks low) | **{pr['failure']}%** |",
        f"| Sum | {pr['sum']}% |",
        "",
        "## Conditional diagnostic (not published as edge)",
        "",
        f"- Status: `{payload['conditional_diagnostic']['status']}`",
        f"- State: `{payload['conditional_diagnostic']['state']}`  ·  n={payload['conditional_diagnostic']['n']}",
        f"- Walk-forward paired CI: `{payload['probability_source']['walkforward']['paired_ci95']}`; model_beats_base=`{payload['probability_source']['walkforward']['model_beats_base']}`",
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


DEFAULT_LEDGER = Path("engine/data/market_brief_scorecard/brief_ledger.jsonl")


def _ledger_rows(ledger: Path) -> list[dict]:
    """Tolerant read of the append-only ledger; malformed lines are ignored."""
    if not ledger.exists():
        return []
    rows = []
    for line in ledger.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


SETTLE_HOUR = 15     # CME equity-index futures settle 15:00 CT
SETTLE_MARGIN_MIN = 15  # bars can finalise just after settlement


def _us_central_utc_offset_hours(d: dt.date) -> int:
    """UTC offset for US Central on `d`: -5 during CDT, -6 during CST.

    Dependency-free on purpose. `zoneinfo` needs a tz database, which this Windows box
    does not ship (`ZoneInfoNotFoundError`) even though a Linux CI runner would -- so a
    guard built on it works in CI and fails in the scheduled job, the worst split. US DST
    runs from 02:00 local on the 2nd Sunday in March to 02:00 local on the 1st Sunday in
    November, which is all the precision a settlement boundary needs.
    """
    mar = dt.date(d.year, 3, 1)
    second_sun_mar = mar + dt.timedelta(days=(6 - mar.weekday()) % 7 + 7)
    nov = dt.date(d.year, 11, 1)
    first_sun_nov = nov + dt.timedelta(days=(6 - nov.weekday()) % 7)
    return -5 if second_sun_mar <= d < first_sun_nov else -6


def session_complete(bar_date: str, now: dt.datetime | None = None) -> bool:
    """False when `bar_date`'s CME session is still trading.

    The equity-index futures session dated D runs from 17:00 CT on D-1 to 15:00 CT on D
    (a Monday session starts Sunday 17:00 CT). A bar fetched before settlement is
    *partial*, and pre-registering it records probabilities for a state the session never
    actually held -- silently corrupting the calibration sample the ledger exists to build.

    Live example: Monday 20:40 CT fetches a bar dated Tuesday, because Tuesday's session
    opened Monday 17:00 CT. Without this guard that partial bar is recorded as "today".
    """
    try:
        d = dt.date.fromisoformat(str(bar_date))
    except (TypeError, ValueError):
        return False
    n = now or dt.datetime.now(dt.timezone.utc)
    if n.tzinfo is None:
        n = n.replace(tzinfo=dt.timezone.utc)
    offset = _us_central_utc_offset_hours(d)
    settle = (dt.datetime(d.year, d.month, d.day, SETTLE_HOUR, SETTLE_MARGIN_MIN,
                          tzinfo=dt.timezone.utc)
              - dt.timedelta(hours=offset))
    return n.astimezone(dt.timezone.utc) >= settle


def record_daily(payload: dict[str, Any], ledger: Path, symbol: str = DEFAULT_SYMBOL,
                 force: bool = False) -> tuple[str, dict[str, Any]]:
    """Pre-register today's measured probabilities into the scorecard ledger.

    Calibration needs (predicted, realised) pairs. Waiting for a rare setup to recur
    produces a trickle of samples; recording the matched-state probabilities every
    session builds the sample at one row per day.

    Idempotent on (date, symbol): a second run on the same session is a no-op unless
    force=True, so a re-run (or a manual fire racing the scheduler) cannot duplicate a
    row and silently double-weight that day in the Brier aggregate.

    Returns (status, entry) where status is "recorded" | "exists" | "skipped".
    """
    today = payload.get("today") or {}
    date = today.get("date")
    probs = payload.get("probabilities") or {}
    if not date or not probs:
        return "skipped", {"reason": "payload has no date/probabilities"}
    if not force and not session_complete(str(date)):
        return "incomplete_session", {"date": date, "reason": "session has not settled yet"}

    for row in _ledger_rows(ledger):
        if row.get("date") == date and row.get("symbol") == symbol and not force:
            return "exists", row

    entry = {
        "recorded_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "model_version": MODEL_VERSION,
        "safety": SAFETY,
        "date": date,
        "symbol": symbol,
        "continuation": probs.get("continuation"),
        "rotation": probs.get("rotation"),
        "failure": probs.get("failure"),
        "signal_close": today.get("close"),
        "signal_low": today.get("low"),
        "state": today.get("state"),
        "source": "base_rates_daily_preregistration",
    }
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")
    return "recorded", entry


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lookback", default=DEFAULT_LOOKBACK)
    ap.add_argument("--out-dir", default="docs/reports")
    ap.add_argument("--json-out", default=None)
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--record", action="store_true",
                    help="Pre-register today's probabilities into the scorecard ledger")
    ap.add_argument("--ledger", default=str(DEFAULT_LEDGER))
    ap.add_argument("--symbol", default="ES=F")
    ap.add_argument("--force", action="store_true",
                    help="Re-record even if this session is already in the ledger")
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

    record_status = None
    if a.record:
        record_status, _entry = record_daily(payload, Path(a.ledger), a.symbol, a.force)
        payload["record_status"] = record_status

    if not a.quiet:
        result = {"report": str(md_path), "published_state": payload["published_state"],
                  "diagnostic_state": payload["matched_state"],
                  "probabilities": payload["probabilities"],
                  "n": payload["states"][payload["published_state"]]["n"]}
        if record_status is not None:
            result["record_status"] = record_status
        print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
