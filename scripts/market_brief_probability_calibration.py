#!/usr/bin/env python3
"""Read-only market-brief probability calibration discovery.

This script is intentionally dependency-light and analysis-only. It does not touch
broker state, engine runtime config, risk settings, kill switches, env files, or
symbol routing.

It builds a first-pass daily calibration dataset for the morning brief's
continuation / rotation / failure framing using public Yahoo chart bars.
Daily bars are not a full substitute for true premarket/Globex minute data; the
report labels this limitation explicitly.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import statistics
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SYMBOLS = ("SPY", "QQQ", "^VIX", "ES=F", "NQ=F", "MES=F")
REPORT_DIR = Path("docs/reports")
DATASET_DIR = Path("engine/data/market_brief_calibration")
MODEL_VERSION = "market-brief-daily-calibration-discovery-v1"
ANALYSIS_ONLY = {
    "mode": "ANALYSIS_ONLY",
    "orders_enabled": False,
    "risk_config_touched": False,
}


@dataclass(frozen=True)
class Bar:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None


@dataclass(frozen=True)
class CalibrationRow:
    date: str
    regime: str
    continuation_probability: float
    rotation_probability: float
    failure_probability: float
    label: str
    spy_gap_pct: float
    qqq_gap_pct: float
    vix_change_pct: float
    es_gap_pct: float | None
    nq_gap_pct: float | None
    spy_open_to_close_pct: float
    qqq_open_to_close_pct: float
    es_open_to_close_pct: float | None
    nq_open_to_close_pct: float | None
    source_quality: str


def _fetch_json(url: str, timeout: int = 20) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 market-brief-calibration"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_yahoo_daily(symbol: str, days: int) -> list[Bar]:
    period2 = int(time.time())
    period1 = period2 - days * 86400
    encoded = urllib.parse.quote(symbol, safe="")
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}"
        f"?period1={period1}&period2={period2}&interval=1d&includePrePost=false&events=history"
    )
    payload = _fetch_json(url)
    result = payload.get("chart", {}).get("result") or []
    if not result:
        raise RuntimeError(f"Yahoo returned no chart result for {symbol}")
    node = result[0]
    timestamps = node.get("timestamp") or []
    quote = (node.get("indicators", {}).get("quote") or [{}])[0]
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []
    bars: list[Bar] = []
    for idx, ts in enumerate(timestamps):
        try:
            o = opens[idx]
            h = highs[idx]
            l = lows[idx]
            c = closes[idx]
        except IndexError:
            continue
        if o is None or h is None or l is None or c is None:
            continue
        date = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).date().isoformat()
        volume = volumes[idx] if idx < len(volumes) else None
        bars.append(Bar(date=date, open=float(o), high=float(h), low=float(l), close=float(c), volume=volume))
    if len(bars) < 30:
        raise RuntimeError(f"Yahoo returned too few valid bars for {symbol}: {len(bars)}")
    return bars


def pct(numerator: float, denominator: float) -> float:
    if denominator == 0 or not math.isfinite(denominator):
        return 0.0
    return 100.0 * numerator / denominator


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def normalize_probs(continuation_raw: float, rotation_raw: float, failure_raw: float) -> tuple[float, float, float]:
    vals = [max(0.01, continuation_raw), max(0.01, rotation_raw), max(0.01, failure_raw)]
    total = sum(vals)
    return tuple(round(100.0 * v / total, 4) for v in vals)  # type: ignore[return-value]


def score_daily_state(
    spy_gap_pct: float,
    qqq_gap_pct: float,
    vix_change_pct: float,
    es_gap_pct: float | None,
    nq_gap_pct: float | None,
) -> tuple[str, float, float, float]:
    """Return regime and continuation/rotation/failure probabilities.

    This is a daily reconstruction proxy for the machine brief's heuristic, not a
    calibrated model. It intentionally uses simple, auditable inputs.
    """
    equity_pressure = (spy_gap_pct + qqq_gap_pct) / 2.0
    futures_values = [x for x in (es_gap_pct, nq_gap_pct) if x is not None]
    futures_pressure = statistics.mean(futures_values) if futures_values else equity_pressure
    vix_pressure = vix_change_pct

    risk_off_score = 0.0
    risk_off_score += clamp(-equity_pressure / 1.25, -1.0, 1.0) * 0.45
    risk_off_score += clamp(vix_pressure / 8.0, -1.0, 1.0) * 0.35
    risk_off_score += clamp(-futures_pressure / 1.0, -1.0, 1.0) * 0.20

    risk_on_score = 0.0
    risk_on_score += clamp(equity_pressure / 1.25, -1.0, 1.0) * 0.45
    risk_on_score += clamp(-vix_pressure / 8.0, -1.0, 1.0) * 0.35
    risk_on_score += clamp(futures_pressure / 1.0, -1.0, 1.0) * 0.20

    if risk_off_score >= 0.25:
        regime = "risk_off"
        trend_alignment = clamp(risk_off_score, 0.0, 1.0)
    elif risk_on_score >= 0.25:
        regime = "risk_on"
        trend_alignment = clamp(risk_on_score, 0.0, 1.0)
    else:
        regime = "balanced"
        trend_alignment = 0.0

    vol_alignment = clamp(abs(vix_pressure) / 8.0, 0.0, 1.0)
    source_alignment = clamp((abs(equity_pressure) + abs(futures_pressure)) / 2.0, 0.0, 1.0)
    continuation_raw = 0.30 + 0.40 * trend_alignment + 0.20 * vol_alignment + 0.10 * source_alignment
    rotation_raw = 0.45 - 0.25 * trend_alignment + 0.10 * (1.0 - vol_alignment)
    failure_raw = 0.25 - 0.10 * trend_alignment + 0.10 * max(0.0, vol_alignment - source_alignment)
    if regime == "balanced":
        continuation_raw, rotation_raw, failure_raw = 0.25, 0.55, 0.20
    return (regime, *normalize_probs(continuation_raw, rotation_raw, failure_raw))


def label_outcome(
    regime: str,
    spy_open_to_close_pct: float,
    qqq_open_to_close_pct: float,
    es_open_to_close_pct: float | None,
    nq_open_to_close_pct: float | None,
) -> str:
    equity_move = (spy_open_to_close_pct + qqq_open_to_close_pct) / 2.0
    futures_values = [x for x in (es_open_to_close_pct, nq_open_to_close_pct) if x is not None]
    futures_move = statistics.mean(futures_values) if futures_values else equity_move
    composite_move = 0.70 * equity_move + 0.30 * futures_move

    if abs(composite_move) < 0.20:
        return "rotation"
    if regime == "risk_off":
        if composite_move <= -0.35:
            return "continuation"
        if composite_move >= 0.35:
            return "failure"
        return "rotation"
    if regime == "risk_on":
        if composite_move >= 0.35:
            return "continuation"
        if composite_move <= -0.35:
            return "failure"
        return "rotation"
    # Balanced briefs are expected to rotate; strong trend day is continuation of
    # the day session, but not of a directional premarket thesis.
    if abs(composite_move) >= 0.75:
        return "failure"
    return "rotation"


def build_rows(symbol_bars: dict[str, list[Bar]]) -> list[CalibrationRow]:
    by_symbol = {sym: {bar.date: bar for bar in bars} for sym, bars in symbol_bars.items()}
    spy_dates = sorted(by_symbol["SPY"])
    rows: list[CalibrationRow] = []
    for date in spy_dates[1:]:
        prev_idx = spy_dates.index(date) - 1
        prev_date = spy_dates[prev_idx]
        required = ["SPY", "QQQ", "^VIX"]
        if not all(date in by_symbol[s] and prev_date in by_symbol[s] for s in required):
            continue
        spy = by_symbol["SPY"][date]
        qqq = by_symbol["QQQ"][date]
        vix = by_symbol["^VIX"][date]
        spy_prev = by_symbol["SPY"][prev_date]
        qqq_prev = by_symbol["QQQ"][prev_date]
        vix_prev = by_symbol["^VIX"][prev_date]

        es = by_symbol.get("ES=F", {}).get(date)
        es_prev = by_symbol.get("ES=F", {}).get(prev_date)
        nq = by_symbol.get("NQ=F", {}).get(date)
        nq_prev = by_symbol.get("NQ=F", {}).get(prev_date)

        spy_gap = pct(spy.open - spy_prev.close, spy_prev.close)
        qqq_gap = pct(qqq.open - qqq_prev.close, qqq_prev.close)
        vix_change = pct(vix.close - vix_prev.close, vix_prev.close)
        es_gap = pct(es.open - es_prev.close, es_prev.close) if es and es_prev else None
        nq_gap = pct(nq.open - nq_prev.close, nq_prev.close) if nq and nq_prev else None
        regime, cont, rot, fail = score_daily_state(spy_gap, qqq_gap, vix_change, es_gap, nq_gap)

        spy_oc = pct(spy.close - spy.open, spy.open)
        qqq_oc = pct(qqq.close - qqq.open, qqq.open)
        es_oc = pct(es.close - es.open, es.open) if es else None
        nq_oc = pct(nq.close - nq.open, nq.open) if nq else None
        label = label_outcome(regime, spy_oc, qqq_oc, es_oc, nq_oc)
        source_quality = "daily_proxy" if es and nq else "daily_proxy_missing_futures"
        rows.append(
            CalibrationRow(
                date=date,
                regime=regime,
                continuation_probability=cont,
                rotation_probability=rot,
                failure_probability=fail,
                label=label,
                spy_gap_pct=round(spy_gap, 4),
                qqq_gap_pct=round(qqq_gap, 4),
                vix_change_pct=round(vix_change, 4),
                es_gap_pct=round(es_gap, 4) if es_gap is not None else None,
                nq_gap_pct=round(nq_gap, 4) if nq_gap is not None else None,
                spy_open_to_close_pct=round(spy_oc, 4),
                qqq_open_to_close_pct=round(qqq_oc, 4),
                es_open_to_close_pct=round(es_oc, 4) if es_oc is not None else None,
                nq_open_to_close_pct=round(nq_oc, 4) if nq_oc is not None else None,
                source_quality=source_quality,
            )
        )
    return rows


def brier_score(rows: list[CalibrationRow]) -> dict[str, float]:
    if not rows:
        return {"continuation": math.nan, "rotation": math.nan, "failure": math.nan, "macro_avg": math.nan}
    sums = {"continuation": 0.0, "rotation": 0.0, "failure": 0.0}
    for row in rows:
        probs = {
            "continuation": row.continuation_probability / 100.0,
            "rotation": row.rotation_probability / 100.0,
            "failure": row.failure_probability / 100.0,
        }
        for klass in sums:
            actual = 1.0 if row.label == klass else 0.0
            sums[klass] += (probs[klass] - actual) ** 2
    out = {klass: round(value / len(rows), 6) for klass, value in sums.items()}
    out["macro_avg"] = round(sum(out.values()) / 3.0, 6)
    return out


def reliability_bins(rows: list[CalibrationRow], klass: str, bins: int = 5) -> list[dict[str, Any]]:
    buckets: list[list[tuple[float, int]]] = [[] for _ in range(bins)]
    for row in rows:
        probability = getattr(row, f"{klass}_probability") / 100.0
        idx = min(bins - 1, int(probability * bins))
        buckets[idx].append((probability, 1 if row.label == klass else 0))
    out: list[dict[str, Any]] = []
    for idx, bucket in enumerate(buckets):
        if bucket:
            out.append(
                {
                    "bin": idx + 1,
                    "range": [round(idx / bins, 2), round((idx + 1) / bins, 2)],
                    "n": len(bucket),
                    "avg_predicted": round(statistics.mean(p for p, _ in bucket), 4),
                    "observed_rate": round(statistics.mean(a for _, a in bucket), 4),
                }
            )
        else:
            out.append({"bin": idx + 1, "range": [round(idx / bins, 2), round((idx + 1) / bins, 2)], "n": 0})
    return out


def row_to_dict(row: CalibrationRow) -> dict[str, Any]:
    return row.__dict__.copy()


def write_dataset(rows: list[CalibrationRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(row_to_dict(rows[0]).keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow(row_to_dict(row))


def render_report(rows: list[CalibrationRow], source_counts: dict[str, int], dataset_path: Path) -> tuple[dict[str, Any], str]:
    labels = {klass: sum(1 for row in rows if row.label == klass) for klass in ("continuation", "rotation", "failure")}
    regimes = {klass: sum(1 for row in rows if row.regime == klass) for klass in ("risk_off", "risk_on", "balanced")}
    brier = brier_score(rows)
    payload = {
        "model_version": MODEL_VERSION,
        "safety": ANALYSIS_ONLY,
        "sample_count": len(rows),
        "date_start": rows[0].date if rows else None,
        "date_end": rows[-1].date if rows else None,
        "source_counts": source_counts,
        "label_counts": labels,
        "regime_counts": regimes,
        "brier_score": brier,
        "reliability": {klass: reliability_bins(rows, klass) for klass in ("continuation", "rotation", "failure")},
        "dataset_path": str(dataset_path).replace("\\", "/"),
        "limitations": [
            "Daily bars are a proxy; this is not true premarket/Globex calibration.",
            "Macro-event names/counts are not included in v1 discovery rows.",
            "No live trading, risk config, kill switch, or broker state is touched.",
            "Use this to judge feasibility/base rates before fitting any calibration layer.",
        ],
    }
    md = [
        "# Market Brief Probability Calibration Discovery",
        "",
        f"Generated: {dt.datetime.now(dt.timezone.utc).isoformat()}",
        f"Model version: `{MODEL_VERSION}`",
        "",
        "## Verdict",
        "",
    ]
    if len(rows) >= 250:
        md.append("Dataset is large enough for a first reliability/base-rate read, but still daily-proxy only.")
    else:
        md.append("Dataset is too small for calibration; collect more history before fitting probabilities.")
    md.extend(
        [
            "",
            "## Safety",
            "",
            "- `mode=ANALYSIS_ONLY`",
            "- `orders_enabled=false`",
            "- `risk_config_touched=false`",
            "- No engine/risk/kill-switch/env/broker/symbol-gate state was changed.",
            "",
            "## Dataset",
            "",
            f"- Rows: `{len(rows)}`",
            f"- Date span: `{payload['date_start']}` → `{payload['date_end']}`",
            f"- Dataset CSV: `{payload['dataset_path']}`",
            f"- Source counts: `{source_counts}`",
            "",
            "## Label base rates",
            "",
            "| Outcome | Count | Rate |",
            "|---|---:|---:|",
        ]
    )
    for klass, count in labels.items():
        rate = count / len(rows) if rows else 0.0
        md.append(f"| {klass} | {count} | {rate:.2%} |")
    md.extend(
        [
            "",
            "## Regime counts",
            "",
            "| Regime | Count | Rate |",
            "|---|---:|---:|",
        ]
    )
    for klass, count in regimes.items():
        rate = count / len(rows) if rows else 0.0
        md.append(f"| {klass} | {count} | {rate:.2%} |")
    md.extend(
        [
            "",
            "## Brier score — lower is better",
            "",
            "| Class | Brier |",
            "|---|---:|",
        ]
    )
    for klass, value in brier.items():
        md.append(f"| {klass} | {value} |")
    md.extend(
        [
            "",
            "## Reliability bins",
            "",
            "```json",
            json.dumps(payload["reliability"], indent=2, sort_keys=True),
            "```",
            "",
            "## Limitations / next gates",
            "",
            "1. Replace daily proxy with true premarket/Globex snapshots when second intraday feed is implemented.",
            "2. Add macro calendar event-count/name features once parser preserves names.",
            "3. Do not fit isotonic/logistic calibration until the sample count and class balance are sufficient.",
            "4. Keep dashboard label as heuristic until calibrated coefficients pass reliability checks.",
            "",
            "## Machine payload",
            "",
            "```json",
            json.dumps(payload, indent=2, sort_keys=True),
            "```",
            "",
        ]
    )
    return payload, "\n".join(md)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=900, help="Lookback window for Yahoo daily bars")
    parser.add_argument("--output-dir", default=str(REPORT_DIR), help="Report output directory")
    parser.add_argument("--dataset-dir", default=str(DATASET_DIR), help="CSV dataset output directory")
    args = parser.parse_args(argv)

    symbol_bars: dict[str, list[Bar]] = {}
    source_counts: dict[str, int] = {}
    for symbol in SYMBOLS:
        bars = fetch_yahoo_daily(symbol, args.days)
        symbol_bars[symbol] = bars
        source_counts[symbol] = len(bars)

    rows = build_rows(symbol_bars)
    if not rows:
        raise RuntimeError("No calibration rows could be built from fetched bars")

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    dataset_path = Path(args.dataset_dir) / f"market_brief_calibration_rows_{stamp}.csv"
    report_path = Path(args.output_dir) / f"MARKET_BRIEF_PROBABILITY_CALIBRATION_{stamp}.md"
    latest_json_path = Path(args.output_dir) / "MARKET_BRIEF_PROBABILITY_CALIBRATION_LATEST.json"
    latest_md_path = Path(args.output_dir) / "MARKET_BRIEF_PROBABILITY_CALIBRATION_LATEST.md"

    write_dataset(rows, dataset_path)
    payload, report = render_report(rows, source_counts, dataset_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    latest_md_path.write_text(report, encoding="utf-8")
    latest_json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    print(json.dumps({"rows": len(rows), "report": str(report_path), "dataset": str(dataset_path), "brier": payload["brier_score"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
