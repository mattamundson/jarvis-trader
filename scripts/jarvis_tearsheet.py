#!/usr/bin/env python3
"""
JARVIS TRADER — Standalone Tearsheet Generator
===============================================
Backbone for Sprint 21-E Walk-Forward Evaluation (WFE) live monitor.
Imports cleanly from other scripts and runs standalone via CLI.

Features:
  • Fetches returns from the JARVIS engine API (live or paper)
  • Computes all QuantStats gates (10-gate Run-12 spec)
  • Generates a full HTML tearsheet via qs.reports.html
  • Optionally runs Walk-Forward slicing (--wfe flag)
  • Strategy-aware: C+, A, RL — each with custom benchmark + gate profile
  • Regime-conditional stats (RISK_ON / RISK_OFF / NORMAL)

CLI:
    python scripts/jarvis_tearsheet.py --strategy C+ --symbol MES --days 90
    python scripts/jarvis_tearsheet.py --strategy RL --symbol MES --days 180 --gates
    python scripts/jarvis_tearsheet.py --strategy A  --symbol MCL --wfe

Imports (programmatic):
    from scripts.jarvis_tearsheet import generate_tearsheet, compute_gates

Requirements:
    pip install quantstats requests
    Engine running at http://localhost:8010
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, NamedTuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

try:
    import requests
except ImportError:
    print("ERROR: requests not installed. Run: pip install requests")
    sys.exit(1)

try:
    import quantstats as qs
    qs.extend_pandas()
    QS_AVAILABLE = True
except ImportError:
    QS_AVAILABLE = False
    logger.warning("quantstats not installed — tearsheet unavailable. Run: pip install quantstats")

BASE_URL = "http://localhost:8010"
API_KEY  = "test-key"
OUTPUT_DIR = Path("docs/reports/tearsheets")

# ── Strategy profiles ─────────────────────────────────────────────────────

STRATEGY_PROFILES: dict[str, dict] = {
    "C+": {
        "benchmark":     "SPY",
        "title_prefix":  "Strategy C+ (ETF Momentum)",
        "gate_profile":  "momentum",
        "endpoints": {
            "returns":  "/paper/trades/log",
            "regime":   "/api/signal",
            "validate": "/paper/validation/progress",
        },
    },
    "A": {
        "benchmark":    "MCL",
        "title_prefix": "Strategy A (Futures Intraday)",
        "gate_profile": "futures",
        "endpoints": {
            "returns":  "/paper/trades/log",
            "regime":   "/api/signal",
            "validate": "/paper/validation/progress",
        },
    },
    "RL": {
        "benchmark":    "MES",
        "title_prefix": "Strategy RL (PPO-LSTM Agent)",
        "gate_profile": "rl",
        "endpoints": {
            "returns":  "/strategies/rl/evaluate",
            "regime":   "/strategies/rl/status",
            "validate": "/paper/validation/progress",
        },
    },
}

# ── Gate profiles (10-gate Run-12 spec) ──────────────────────────────────

GATE_PROFILES: dict[str, dict[str, tuple[float, str]]] = {
    "momentum": {
        "profit_factor":      (2.0,   ">="),
        "sharpe":             (1.5,   ">="),
        "sortino":            (1.0,   ">="),
        "calmar":             (0.5,   ">="),
        "tail_ratio":         (1.0,   ">="),
        "common_sense_ratio": (1.5,   ">="),
        "ulcer_perf_index":   (0.5,   ">="),
        "skew":               (-1.5,  ">="),
        "win_rate":           (0.55,  ">="),
        "max_drawdown":       (0.15,  "<="),
    },
    "futures": {
        "profit_factor":      (1.8,   ">="),   # tighter markets, lower PF ok
        "sharpe":             (1.2,   ">="),
        "sortino":            (0.8,   ">="),
        "calmar":             (0.4,   ">="),
        "tail_ratio":         (0.9,   ">="),
        "common_sense_ratio": (1.2,   ">="),
        "ulcer_perf_index":   (0.4,   ">="),
        "skew":               (-2.0,  ">="),   # futures more left-skewed
        "win_rate":           (0.50,  ">="),
        "max_drawdown":       (0.20,  "<="),
    },
    "rl": {
        "profit_factor":      (2.0,   ">="),
        "sortino":            (1.0,   ">="),
        "calmar":             (0.5,   ">="),
        "tail_ratio":         (1.0,   ">="),
        "exposure":           (0.15,  ">="),
        "gain_to_pain":       (0.50,  ">="),
        "consecutive_losses": (8,     "<="),
        "win_rate":           (0.55,  ">="),
        "max_drawdown":       (0.15,  "<="),
        "skew":               (-1.5,  ">="),
    },
}

REGIME_LABELS = ("RISK_ON", "RISK_OFF", "NORMAL")


# ── API helpers ───────────────────────────────────────────────────────────

def _get(path: str, params: dict | None = None) -> Any:
    try:
        r = requests.get(
            f"{BASE_URL}{path}",
            params=params,
            headers={"X-API-Key": API_KEY},
            timeout=15,
        )
        r.raise_for_status()
        return r.json()
    except requests.exceptions.ConnectionError:
        logger.error(f"Cannot connect to engine at {BASE_URL}")
        return None
    except Exception as e:
        logger.warning(f"GET {path} failed: {e}")
        return None


def _post(path: str, payload: dict) -> Any:
    try:
        r = requests.post(
            f"{BASE_URL}{path}",
            json=payload,
            headers={"X-API-Key": API_KEY},
            timeout=120,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.warning(f"POST {path} failed: {e}")
        return None


# ── Return-series fetcher ─────────────────────────────────────────────────

def fetch_returns(
    strategy: str,
    symbol:   str,
    days:     int = 90,
    starting_capital: float = 10_000.0,
) -> pd.Series | None:
    """
    Fetch trade log from engine and build a daily return series.
    Strategy-aware: RL uses /strategies/rl/evaluate endpoint.
    """
    if strategy == "RL":
        # Fetch from RL evaluate endpoint
        end   = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        raw   = _post("/strategies/rl/evaluate", {
            "symbol": symbol, "start_date": start, "end_date": end, "interval": "1h"
        })
        if raw is None:
            return None
        trades = raw.get("trade_log") or raw.get("trades") or []
    else:
        raw = _get("/paper/trades/log", params={"symbol": symbol, "days": days})
        if raw is None:
            return None
        trades = raw if isinstance(raw, list) else raw.get("trades") or []

    if not trades:
        logger.warning("No trades returned — cannot build return series.")
        return None

    rows = []
    for t in trades:
        pnl = t.get("pnl") or t.get("profit") or t.get("net_pnl")
        ts  = t.get("exit_date") or t.get("date") or t.get("timestamp")
        if pnl is not None and ts is not None:
            try:
                rows.append({"date": pd.to_datetime(ts), "pnl": float(pnl)})
            except Exception:
                continue

    if len(rows) < 5:
        logger.warning(f"Only {len(rows)} trades — insufficient for tearsheet.")
        return None

    df     = pd.DataFrame(rows).sort_values("date").set_index("date")
    equity = starting_capital + df["pnl"].cumsum()
    ret    = equity.pct_change().dropna()
    ret.index = ret.index.tz_localize(None)
    logger.info(f"Return series: {len(ret)} pts  ({ret.index[0].date()} → {ret.index[-1].date()})")
    return ret


# ── Regime label fetcher ──────────────────────────────────────────────────

def fetch_regime_labels(instrument: str = "MCL") -> pd.Series | None:
    """
    Fetch per-day regime labels from /paper/validation/progress.
    Returns a Series indexed by date with values in REGIME_LABELS.
    """
    raw = _get(f"/paper/validation/progress", params={"instrument": instrument})
    if raw is None:
        return None

    # Try daily_regime_log first
    log = (raw.get("data", {}).get("daily_regime_log")
           or raw.get("daily_regime_log")
           or [])
    if not log:
        return None

    rows = []
    for entry in log:
        d      = entry.get("date") or entry.get("timestamp")
        regime = entry.get("regime") or entry.get("risk_regime") or "NORMAL"
        if d:
            rows.append({"date": pd.to_datetime(d), "regime": str(regime).upper()})

    if not rows:
        return None

    df = pd.DataFrame(rows).sort_values("date").set_index("date")
    return df["regime"]


# ── Gate computation ──────────────────────────────────────────────────────

class GateResult(NamedTuple):
    metric:    str
    value:     float | None
    threshold: float
    op:        str
    passed:    bool


def compute_gates(
    returns:      pd.Series,
    gate_profile: str = "momentum",
    extra_metrics: dict | None = None,
) -> list[GateResult]:
    """
    Compute all gate metrics via qs.stats and return structured results.
    extra_metrics: pre-computed values from engine JSON (e.g. profit_factor, n_trades)
    """
    if not QS_AVAILABLE:
        logger.error("quantstats required for gate computation.")
        return []

    gates    = GATE_PROFILES.get(gate_profile, GATE_PROFILES["momentum"])
    extra    = extra_metrics or {}
    results  = []

    # Compute qs metrics
    qs_computed: dict[str, float] = {}
    try:
        qs_computed["sharpe"]             = float(qs.stats.sharpe(returns))
        qs_computed["sortino"]            = float(qs.stats.sortino(returns))
        qs_computed["calmar"]             = float(qs.stats.calmar(returns))
        qs_computed["tail_ratio"]         = float(qs.stats.tail_ratio(returns))
        qs_computed["common_sense_ratio"] = float(qs.stats.common_sense_ratio(returns))
        qs_computed["ulcer_perf_index"]   = float(qs.stats.ulcer_performance_index(returns))
        qs_computed["skew"]               = float(qs.stats.skew(returns))
        qs_computed["max_drawdown"]       = abs(float(qs.stats.max_drawdown(returns)))
        qs_computed["exposure"]           = float(qs.stats.exposure(returns))
        qs_computed["gain_to_pain"]       = float(qs.stats.gain_to_pain_ratio(returns))
        qs_computed["consecutive_losses"] = int(qs.stats.consecutive_losses(returns))
    except Exception as e:
        logger.warning(f"qs.stats computation partial failure: {e}")

    for metric, (threshold, op) in gates.items():
        # Prefer qs-computed, then engine JSON
        value = qs_computed.get(metric) or extra.get(metric)

        if value is None:
            results.append(GateResult(metric, None, threshold, op, False))
            continue

        try:
            v      = float(value)
            passed = (v >= threshold) if op == ">=" else (v <= threshold)
            results.append(GateResult(metric, v, threshold, op, passed))
        except (TypeError, ValueError):
            results.append(GateResult(metric, None, threshold, op, False))

    return results


def print_gate_report(gate_results: list[GateResult], strategy: str) -> tuple[int, int]:
    """Pretty-print gate report. Returns (passed, total)."""
    passed = sum(1 for g in gate_results if g.passed)
    total  = len(gate_results)

    print("\n" + "═" * 68)
    print(f"  JARVIS GATE REPORT — Strategy {strategy}")
    print("═" * 68)
    for g in gate_results:
        status = "PASS" if g.passed else "FAIL"
        sym    = "✓" if g.passed else "✗"
        val_s  = f"{g.value:.4f}" if g.value is not None else "N/A"
        print(f"  [{status}] {sym} {g.metric:<24}  {val_s:>10}  (need: {g.op} {g.threshold})")
    print("═" * 68)
    verdict = "✓ ALL GATES PASSED" if passed == total else f"✗ {total - passed} GATE(S) FAILED"
    print(f"  {verdict}  ({passed}/{total})\n")
    return passed, total


# ── Walk-Forward Evaluation ───────────────────────────────────────────────

def compute_wfe_report(
    returns:      pd.Series,
    gate_profile: str = "momentum",
    n_windows:    int = 6,
    window_days:  int = 30,
) -> dict:
    """
    Slice returns into n_windows rolling windows and compute gates on each.
    Returns a dict with per-window stats (for Sprint 21-E WFE live monitor).
    """
    if not QS_AVAILABLE or returns is None or len(returns) < window_days:
        return {"error": "insufficient data or quantstats unavailable"}

    windows   = []
    total_pts = len(returns)

    for i in range(n_windows):
        end_idx   = total_pts - i * (window_days // 2)
        start_idx = max(0, end_idx - window_days)
        if end_idx <= 0 or start_idx >= end_idx:
            break

        window_ret = returns.iloc[start_idx:end_idx]
        if len(window_ret) < 5:
            continue

        w_start = window_ret.index[0].date().isoformat()
        w_end   = window_ret.index[-1].date().isoformat()

        try:
            w_stats = {
                "window":    f"{w_start} → {w_end}",
                "n_points":  len(window_ret),
                "sharpe":    round(float(qs.stats.sharpe(window_ret)),    3),
                "sortino":   round(float(qs.stats.sortino(window_ret)),   3),
                "calmar":    round(float(qs.stats.calmar(window_ret)),    3),
                "tail_ratio":round(float(qs.stats.tail_ratio(window_ret)),3),
                "max_dd":    round(abs(float(qs.stats.max_drawdown(window_ret))), 3),
                "skew":      round(float(qs.stats.skew(window_ret)),      3),
            }
            gate_results = compute_gates(window_ret, gate_profile=gate_profile)
            w_stats["gates_passed"] = sum(1 for g in gate_results if g.passed)
            w_stats["gates_total"]  = len(gate_results)
            windows.append(w_stats)
        except Exception as e:
            logger.warning(f"WFE window {i} failed: {e}")

    windows.reverse()   # chronological order
    all_passed = [w["gates_passed"] == w["gates_total"] for w in windows]
    wfe_score  = sum(all_passed) / len(windows) if windows else 0.0

    return {
        "wfe_score":    round(wfe_score, 3),
        "windows_pass": sum(all_passed),
        "windows_total":len(windows),
        "window_days":  window_days,
        "windows":      windows,
    }


# ── Regime-conditional stats ──────────────────────────────────────────────

def compute_regime_stats(
    returns:        pd.Series,
    regime_labels:  pd.Series,
    gate_profile:   str = "momentum",
) -> dict[str, dict]:
    """
    Slice returns by regime and compute qs stats on each slice.
    Returns dict: {regime → {sharpe, sortino, max_dd, n_points, …}}
    """
    if not QS_AVAILABLE:
        return {}

    results: dict[str, dict] = {}

    for regime in REGIME_LABELS:
        regime_dates = regime_labels[regime_labels == regime].index
        slice_ret    = returns[returns.index.isin(regime_dates)]

        if len(slice_ret) < 3:
            results[regime] = {"n_points": len(slice_ret), "note": "insufficient data"}
            continue

        try:
            results[regime] = {
                "n_points":  len(slice_ret),
                "sharpe":    round(float(qs.stats.sharpe(slice_ret)),    3),
                "sortino":   round(float(qs.stats.sortino(slice_ret)),   3),
                "calmar":    round(float(qs.stats.calmar(slice_ret)),    3),
                "tail_ratio":round(float(qs.stats.tail_ratio(slice_ret)),3),
                "max_dd":    round(abs(float(qs.stats.max_drawdown(slice_ret))), 3),
                "skew":      round(float(qs.stats.skew(slice_ret)),      3),
            }
        except Exception as e:
            results[regime] = {"n_points": len(slice_ret), "error": str(e)}

    return results


# ── Main HTML tearsheet generator ─────────────────────────────────────────

def generate_tearsheet(
    returns:      pd.Series,
    strategy:     str     = "C+",
    symbol:       str     = "MES",
    days:         int     = 90,
    benchmark:    str     = "SPY",
    output_dir:   Path    = OUTPUT_DIR,
    run_gates:    bool    = False,
    run_wfe:      bool    = False,
    extra_metrics: dict | None = None,
) -> dict:
    """
    Generate an HTML tearsheet and optionally run gate/WFE analysis.

    Returns a result dict with keys:
      html_path, gate_results, wfe_report, regime_stats
    """
    if not QS_AVAILABLE:
        return {"error": "quantstats not installed. Run: pip install quantstats"}

    profile   = STRATEGY_PROFILES.get(strategy, STRATEGY_PROFILES["C+"])
    gate_key  = profile["gate_profile"]
    title     = f"{profile['title_prefix']} — {symbol} ({days}d)"
    today     = date.today().isoformat()

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    html_path = output_dir / f"{today}_{strategy.replace('+','plus')}_{symbol}.html"

    result: dict = {
        "html_path":     None,
        "gate_results":  [],
        "wfe_report":    {},
        "regime_stats":  {},
    }

    # Generate HTML tearsheet
    try:
        qs.reports.html(
            returns,
            benchmark=benchmark,
            output=str(html_path),
            title=title,
            download_filename=str(html_path),
            grayscale=False,
        )
        result["html_path"] = str(html_path)
        logger.info(f"HTML tearsheet saved: {html_path}")
    except Exception as e:
        logger.error(f"qs.reports.html failed: {e}")
        result["error"] = str(e)

    # Gate computation
    if run_gates or run_wfe:
        result["gate_results"] = compute_gates(
            returns, gate_profile=gate_key, extra_metrics=extra_metrics
        )

    # WFE
    if run_wfe:
        result["wfe_report"] = compute_wfe_report(
            returns, gate_profile=gate_key, n_windows=6, window_days=30
        )

    return result


# ── CLI ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="JARVIS Tearsheet Generator — Sprint 21-E WFE backbone"
    )
    parser.add_argument("--strategy",  default="C+",    choices=["C+", "A", "RL"],
                        help="Strategy profile (default: C+)")
    parser.add_argument("--symbol",    default="MES",   help="Symbol (default: MES)")
    parser.add_argument("--days",      type=int, default=90,
                        help="Lookback days (default: 90)")
    parser.add_argument("--benchmark", default=None,
                        help="Benchmark ticker (default: from strategy profile)")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR),
                        help=f"Output directory (default: {OUTPUT_DIR})")
    parser.add_argument("--gates",     action="store_true", help="Run 10-gate validation report")
    parser.add_argument("--wfe",       action="store_true", help="Run walk-forward evaluation")
    parser.add_argument("--capital",   type=float, default=10_000.0,
                        help="Starting capital for return calculation (default: 10000)")
    parser.add_argument("--json-out",  default=None,
                        help="Save gate/WFE results as JSON to this path")
    args = parser.parse_args()

    if not QS_AVAILABLE:
        print("ERROR: quantstats is required. Run:  pip install quantstats")
        sys.exit(1)

    profile   = STRATEGY_PROFILES.get(args.strategy, STRATEGY_PROFILES["C+"])
    benchmark = args.benchmark or profile["benchmark"]

    print(f"\nJARVIS Tearsheet Generator")
    print(f"  Strategy : {args.strategy}")
    print(f"  Symbol   : {args.symbol}")
    print(f"  Days     : {args.days}")
    print(f"  Benchmark: {benchmark}")
    print(f"  Gates    : {'YES' if args.gates else 'NO'}")
    print(f"  WFE      : {'YES' if args.wfe else 'NO'}")
    print()

    # Fetch returns
    returns = fetch_returns(args.strategy, args.symbol, args.days, args.capital)
    if returns is None:
        print("ERROR: Could not build return series. Is the engine running?")
        sys.exit(1)

    # Generate tearsheet
    result = generate_tearsheet(
        returns,
        strategy    = args.strategy,
        symbol      = args.symbol,
        days        = args.days,
        benchmark   = benchmark,
        output_dir  = Path(args.output_dir),
        run_gates   = args.gates or args.wfe,
        run_wfe     = args.wfe,
    )

    if result.get("html_path"):
        print(f"✓ HTML tearsheet: {result['html_path']}")

    if result.get("gate_results"):
        passed, total = print_gate_report(result["gate_results"], args.strategy)

    if result.get("wfe_report") and "windows" in result["wfe_report"]:
        wfe = result["wfe_report"]
        print(f"\nWalk-Forward Evaluation  ({wfe['window_days']}d windows)")
        print(f"  WFE Score:   {wfe['wfe_score']:.1%}")
        print(f"  Windows PASS: {wfe['windows_pass']}/{wfe['windows_total']}")
        print()
        for w in wfe["windows"]:
            tag  = "✓" if w["gates_passed"] == w["gates_total"] else "✗"
            print(
                f"  {tag} {w['window']:40s}  "
                f"Sh:{w['sharpe']:>6.3f}  So:{w['sortino']:>6.3f}  "
                f"DD:{w['max_dd']*100:>5.1f}%  "
                f"Gates:{w['gates_passed']}/{w['gates_total']}"
            )

    if args.json_out:
        out: dict = {
            "generated":   datetime.now().isoformat(),
            "strategy":    args.strategy,
            "symbol":      args.symbol,
            "days":        args.days,
            "html_path":   result.get("html_path"),
            "wfe":         result.get("wfe_report", {}),
            "gate_results": [
                {
                    "metric":    g.metric,
                    "value":     g.value,
                    "threshold": g.threshold,
                    "op":        g.op,
                    "passed":    g.passed,
                }
                for g in result.get("gate_results", [])
            ],
        }
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        with open(args.json_out, "w") as f:
            json.dump(out, f, indent=2, default=str)
        print(f"\nJSON results saved: {args.json_out}")


if __name__ == "__main__":
    main()
