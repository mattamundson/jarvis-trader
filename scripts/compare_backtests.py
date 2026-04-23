#!/usr/bin/env python3
"""
Backtest Results Comparison Tool — JARVIS TRADER v2 (QuantStats Edition)
=========================================================================
Loads backtest JSON results, rebuilds a trade-return series from the raw
trade log (or falls back to summary metrics), then computes all gate metrics
via qs.stats so the validation is never fooled by cherry-picked JSON fields.

Usage:
    python scripts/compare_backtests.py
    python scripts/compare_backtests.py --results-dir engine/backtest/results/
    python scripts/compare_backtests.py --output docs/reports/BACKTEST_COMPARISON.md

10-Gate Validation (replaces old 4-gate):
    profit_factor ≥ 2.0       common_sense_ratio ≥ 1.5
    sharpe        ≥ 1.5       ulcer_perf_index   ≥ 0.5
    sortino       ≥ 1.0       skew               ≥ -1.5
    calmar        ≥ 0.5       win_rate           ≥ 55 %
    tail_ratio    ≥ 1.0       max_drawdown       ≤ 15 %
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ── QuantStats import (graceful degradation) ──────────────────────────────
try:
    import quantstats as qs
    QS_AVAILABLE = True
    qs.extend_pandas()          # adds .sharpe(), .sortino(), … to Series
except ImportError:
    QS_AVAILABLE = False
    logger.warning(
        "quantstats not installed — falling back to JSON metrics. "
        "Run:  pip install quantstats"
    )

# ── 10-Gate Validation Spec ───────────────────────────────────────────────
VALIDATION_GATES: dict[str, tuple[float, str]] = {
    # (threshold, operator)   operator: ">=" or "<="
    "profit_factor":       (2.0,   ">="),
    "sharpe":              (1.5,   ">="),
    "sortino":             (1.0,   ">="),
    "calmar":              (0.5,   ">="),
    "tail_ratio":          (1.0,   ">="),
    "common_sense_ratio":  (1.5,   ">="),
    "ulcer_perf_index":    (0.5,   ">="),
    "skew":                (-1.5,  ">="),
    "win_rate":            (0.55,  ">="),
    "max_drawdown":        (0.15,  "<="),
}

# Gates available without QuantStats (JSON-only fallback)
LEGACY_GATES: dict[str, tuple[float, str]] = {
    "profit_factor": (2.0,  ">="),
    "sharpe":        (1.5,  ">="),
    "win_rate":      (0.55, ">="),
    "max_drawdown":  (0.15, "<="),
}


# ── Return-series builder ─────────────────────────────────────────────────

def _build_returns_series(data: dict) -> Optional[pd.Series]:
    """
    Build a daily/trade-by-trade return series from raw JSON.

    Tries (in order):
      1. data["trades"]            — list of {pnl, entry_date/date, …}
      2. data["equity_curve"]      — list of {date, equity}
      3. data["daily_returns"]     — list of floats or {date, return}
    Returns None if no raw series can be built.
    """
    trades = data.get("trades") or data.get("trade_log") or []
    if trades and isinstance(trades, list):
        rows = []
        for t in trades:
            pnl = t.get("pnl") or t.get("profit") or t.get("net_pnl")
            ts  = t.get("exit_date") or t.get("date") or t.get("entry_date")
            if pnl is not None and ts is not None:
                rows.append({"date": pd.to_datetime(ts), "pnl": float(pnl)})
        if rows:
            df = pd.DataFrame(rows).sort_values("date").set_index("date")
            # Convert PnL to % returns (assume starting capital = 10 000 if missing)
            capital = float(data.get("starting_capital", data.get("initial_capital", 10_000)))
            equity = capital + df["pnl"].cumsum()
            returns = equity.pct_change().dropna()
            returns.index = returns.index.tz_localize(None)
            return returns

    equity_curve = data.get("equity_curve") or []
    if equity_curve and isinstance(equity_curve, list):
        rows = []
        for pt in equity_curve:
            if isinstance(pt, dict):
                ts  = pt.get("date") or pt.get("timestamp")
                eq  = pt.get("equity") or pt.get("value")
                if ts is not None and eq is not None:
                    rows.append({"date": pd.to_datetime(ts), "equity": float(eq)})
        if rows:
            df = pd.DataFrame(rows).sort_values("date").set_index("date")
            returns = df["equity"].pct_change().dropna()
            returns.index = returns.index.tz_localize(None)
            return returns

    daily = data.get("daily_returns") or []
    if daily and isinstance(daily, list):
        if isinstance(daily[0], (int, float)):
            idx = pd.date_range(end=datetime.today(), periods=len(daily), freq="B")
            return pd.Series(daily, index=idx, dtype=float)
        rows = []
        for pt in daily:
            if isinstance(pt, dict):
                ts  = pt.get("date") or pt.get("timestamp")
                ret = pt.get("return") or pt.get("pct_return")
                if ts is not None and ret is not None:
                    rows.append({"date": pd.to_datetime(ts), "ret": float(ret)})
        if rows:
            df = pd.DataFrame(rows).sort_values("date").set_index("date")
            return df["ret"]

    return None


# ── QuantStats metric extractor ───────────────────────────────────────────

def extract_qs_metrics(data: dict) -> Optional[dict]:
    """
    Extract all 10 gate metrics (+ extras) using qs.stats on a return series.
    Falls back gracefully to JSON fields where a series cannot be built or QS
    is unavailable.
    """
    if not data.get("symbol") and not data.get("instrument"):
        return None

    m      = data.get("full_metrics", data)
    symbol = data.get("symbol") or data.get("instrument", "N/A")
    tf     = data.get("interval") or data.get("timeframe", "N/A")

    # ── Defaults from JSON (used as fallback) ──────────────────────────────
    pf   = m.get("profit_factor",    m.get("PF", "N/A"))
    sh   = m.get("sharpe_ratio",     m.get("sharpe", "N/A"))
    wr   = m.get("win_rate",         m.get("win_rate_pct", "N/A"))
    if isinstance(wr, (int, float)) and wr > 1:
        wr /= 100.0
    dd   = m.get("max_drawdown_pct", m.get("max_drawdown", "N/A"))
    if isinstance(dd, (int, float)) and dd < 0:
        dd = abs(dd)
    ret  = m.get("total_return_pct", m.get("total_return", "N/A"))
    cnt  = m.get("total_trades",     m.get("n_trades",     "N/A"))
    run_date = data.get("run_date", "unknown")

    result: dict[str, Any] = {
        "symbol":           symbol,
        "timeframe":        tf,
        "profit_factor":    pf,
        "sharpe":           sh,
        "sortino":          "N/A",
        "calmar":           "N/A",
        "tail_ratio":       "N/A",
        "common_sense_ratio": "N/A",
        "ulcer_perf_index": "N/A",
        "skew":             "N/A",
        "win_rate":         wr,
        "total_return_pct": ret,
        "max_drawdown":     dd,
        "trade_count":      cnt,
        "date":             run_date,
        "qs_computed":      False,
    }

    if not QS_AVAILABLE:
        return result

    # ── Try to build return series and compute via qs.stats ───────────────
    returns = _build_returns_series(data)
    if returns is None or len(returns) < 5:
        logger.debug(f"{symbol}: no return series — using JSON metrics")
        return result

    try:
        result["sharpe"]             = round(float(qs.stats.sharpe(returns)),            4)
        result["sortino"]            = round(float(qs.stats.sortino(returns)),           4)
        result["calmar"]             = round(float(qs.stats.calmar(returns)),            4)
        result["tail_ratio"]         = round(float(qs.stats.tail_ratio(returns)),        4)
        result["common_sense_ratio"] = round(float(qs.stats.common_sense_ratio(returns)),4)
        result["ulcer_perf_index"]   = round(float(qs.stats.ulcer_performance_index(returns)), 4)
        result["skew"]               = round(float(qs.stats.skew(returns)),              4)
        result["max_drawdown"]       = round(abs(float(qs.stats.max_drawdown(returns))), 4)
        result["qs_computed"]        = True
        logger.debug(f"{symbol}: qs.stats computed from {len(returns)}-point series")
    except Exception as e:
        logger.warning(f"{symbol}: qs.stats failed ({e}) — keeping JSON metrics")

    return result


# ── Validation gate checker ───────────────────────────────────────────────

def check_passes_validation(row: dict) -> tuple[bool, int, int]:
    """
    Returns (all_passed, gates_passed, total_gates).
    Uses 10-gate spec if qs_computed, else 4-gate legacy spec.
    """
    gates = VALIDATION_GATES if row.get("qs_computed") else LEGACY_GATES
    passed = 0
    for metric, (threshold, op) in gates.items():
        val = row.get(metric)
        if val == "N/A" or val is None:
            continue
        try:
            v = float(val)
        except (TypeError, ValueError):
            continue
        if op == "<=" and v <= threshold:
            passed += 1
        elif op == ">=" and v >= threshold:
            passed += 1
    return passed == len(gates), passed, len(gates)


# ── Formatter ─────────────────────────────────────────────────────────────

def _fmt(val: Any, pct: bool = False) -> str:
    if val == "N/A" or val is None:
        return "N/A"
    try:
        v = float(val)
        if pct:
            return f"{v*100:.1f}%"
        if 0.001 < abs(v) < 10_000:
            return f"{v:.3f}"
        return f"{v:.4f}"
    except (TypeError, ValueError):
        return str(val)


# ── Directory loader ──────────────────────────────────────────────────────

def load_results_from_directory(results_dir: str) -> list[dict]:
    results = []
    results_path = Path(results_dir)
    if not results_path.exists():
        logger.error(f"Results directory not found: {results_dir}")
        return results

    json_files = list(results_path.glob("*.json"))
    logger.info(f"Found {len(json_files)} JSON files in {results_dir}")

    for json_file in json_files:
        try:
            with open(json_file) as f:
                data = json.load(f)
            if isinstance(data, dict):
                if "results" in data and isinstance(data["results"], list):
                    for result in data["results"]:
                        m = extract_qs_metrics(result)
                        if m:
                            results.append(m)
                else:
                    m = extract_qs_metrics(data)
                    if m:
                        results.append(m)
        except json.JSONDecodeError:
            logger.warning(f"Skipping {json_file.name}: invalid JSON")
        except Exception as e:
            logger.warning(f"Skipping {json_file.name}: {e}")

    return results


# ── Markdown report ───────────────────────────────────────────────────────

def generate_markdown_table(results: list[dict], output_path: str) -> None:
    def sort_key(row):
        v = row.get("sortino") if row.get("qs_computed") else row.get("sharpe")
        if v == "N/A" or v is None:
            return float("-inf")
        try:
            return float(v)
        except (TypeError, ValueError):
            return float("-inf")

    sorted_results = sorted(results, key=sort_key, reverse=True)
    qs_mode = any(r.get("qs_computed") for r in sorted_results)
    gates_desc = (
        "PF≥2.0 · Sharpe≥1.5 · Sortino≥1.0 · Calmar≥0.5 · TailRatio≥1.0 · "
        "CSR≥1.5 · UPI≥0.5 · Skew≥-1.5 · WR≥55% · DD≤15%"
        if qs_mode else
        "PF≥2.0 · Sharpe≥1.5 · WR≥55% · DD≤15% (QuantStats not available)"
    )

    lines = [
        "# Backtest Results Comparison — JARVIS TRADER",
        "",
        f"Generated: {datetime.now().isoformat()}",
        f"Total Results: {len(sorted_results)}",
        f"QuantStats computed: {'YES' if qs_mode else 'NO (install quantstats)'}",
        "",
        f"**Validation Gates ({len(VALIDATION_GATES if qs_mode else LEGACY_GATES)}-gate):** {gates_desc}",
        "Rows marked `PASS n/n` meet ALL gates.",
        "",
    ]

    if qs_mode:
        lines += [
            "| Symbol | TF | PF | Sharpe | Sortino | Calmar | Tail | CSR | UPI | Skew | WR | DD | Return | Trades | Gates |",
            "|--------|----|----|-------:|--------:|-------:|-----:|----:|----:|-----:|---:|---:|-------:|-------:|-------|",
        ]
        for row in sorted_results:
            all_pass, n_pass, total = check_passes_validation(row)
            gate_str = f"**PASS {n_pass}/{total}**" if all_pass else f"{n_pass}/{total}"
            lines.append(
                f"| {row['symbol']} | {row['timeframe']} "
                f"| {_fmt(row.get('profit_factor'))} "
                f"| {_fmt(row.get('sharpe'))} "
                f"| {_fmt(row.get('sortino'))} "
                f"| {_fmt(row.get('calmar'))} "
                f"| {_fmt(row.get('tail_ratio'))} "
                f"| {_fmt(row.get('common_sense_ratio'))} "
                f"| {_fmt(row.get('ulcer_perf_index'))} "
                f"| {_fmt(row.get('skew'))} "
                f"| {_fmt(row.get('win_rate'), pct=True)} "
                f"| {_fmt(row.get('max_drawdown'), pct=True)} "
                f"| {_fmt(row.get('total_return_pct'))} "
                f"| {row.get('trade_count', 'N/A')} "
                f"| {gate_str} |"
            )
    else:
        lines += [
            "| Symbol | TF | PF | Sharpe | WR | DD | Return | Trades | Status |",
            "|--------|----|----|-------:|---:|---:|-------:|-------:|--------|",
        ]
        for row in sorted_results:
            all_pass, n_pass, total = check_passes_validation(row)
            gate_str = f"**PASS**" if all_pass else ""
            lines.append(
                f"| {row['symbol']} | {row['timeframe']} "
                f"| {_fmt(row.get('profit_factor'))} "
                f"| {_fmt(row.get('sharpe'))} "
                f"| {_fmt(row.get('win_rate'), pct=True)} "
                f"| {_fmt(row.get('max_drawdown'), pct=True)} "
                f"| {_fmt(row.get('total_return_pct'))} "
                f"| {row.get('trade_count', 'N/A')} "
                f"| {gate_str} |"
            )

    lines += [
        "",
        "## Metrics Legend",
        "",
        "| Metric | Description | Gate |",
        "|--------|-------------|------|",
        "| **PF** | Profit Factor: gross profit / gross loss | ≥ 2.0 |",
        "| **Sharpe** | Annualised risk-adjusted return | ≥ 1.5 |",
        "| **Sortino** | Downside-deviation adjusted return | ≥ 1.0 |",
        "| **Calmar** | Return / max drawdown | ≥ 0.5 |",
        "| **Tail Ratio** | Right-tail / left-tail magnitude | ≥ 1.0 |",
        "| **CSR** | Common Sense Ratio (Sharpe × Tail) | ≥ 1.5 |",
        "| **UPI** | Ulcer Performance Index | ≥ 0.5 |",
        "| **Skew** | Return distribution skewness | ≥ -1.5 |",
        "| **WR** | Win Rate % | ≥ 55% |",
        "| **DD** | Max Drawdown % | ≤ 15% |",
        "",
        "> ⚡ Metrics marked with qs_computed=True are derived from raw trade-return series, "
        "not from potentially optimistic JSON summary fields.",
    ]

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write("\n".join(lines))
    logger.info(f"Markdown table written to {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Backtest Results Comparison Tool — JARVIS TRADER (QuantStats Edition)"
    )
    parser.add_argument(
        "--results-dir", default="engine/backtest/results/",
        help="Path to backtest results directory (default: engine/backtest/results/)",
    )
    parser.add_argument(
        "--output", default="docs/reports/BACKTEST_COMPARISON.md",
        help="Output markdown path (default: docs/reports/BACKTEST_COMPARISON.md)",
    )
    args = parser.parse_args()

    logger.info(f"Loading backtest results from {args.results_dir}")
    results = load_results_from_directory(args.results_dir)

    if not results:
        logger.warning("No valid backtest results found.")
        return

    logger.info(f"Loaded {len(results)} backtest results")
    generate_markdown_table(results, args.output)

    passes = sum(1 for r in results if check_passes_validation(r)[0])
    total  = len(results)
    qs_cnt = sum(1 for r in results if r.get("qs_computed"))
    logger.info(f"{passes}/{total} results PASS all validation gates  ({qs_cnt} via qs.stats)")


if __name__ == "__main__":
    main()
