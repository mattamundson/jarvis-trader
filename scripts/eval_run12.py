#!/usr/bin/env python3
"""
JARVIS TRADER — RL Run Evaluator v2 (QuantStats Edition)
==========================================================
Run 12 replaces the old single-sharpe gate with a 5-metric composite
that exposed Run 9's hold-bloat and Run 10's fat-left-tail problems.

Key changes vs eval_run9.py:
  • sharpe ≥ 1.5            → removed (was gamed by hold-heavy runs)
  • NEW: sortino ≥ 1.0      — downside-only risk (penalises losing holds)
  • NEW: calmar  ≥ 0.5      — return / max-DD (catches drawdown creep)
  • NEW: tail_ratio ≥ 1.0   — right > left tail (Run 10 had 0.6)
  • NEW: exposure ≥ 0.15    — must be in market ≥ 15% of time (no hold-farming)
  • NEW: gain_to_pain ≥ 0.5 — total gains / sum(losses) > 0.5
  • NEW: consecutive_losses ≤ 8 — streak control
  All computed from the raw trade-return series via qs.stats.

Usage:
    cd jarvis-trader/
    python scripts/eval_run12.py [--symbol MES] [--days 180] [--dry-run]

Requirements:
    pip install requests quantstats
    Engine running at http://localhost:8010
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

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
    print("WARNING: quantstats not installed — some gates will use JSON fallbacks.")
    print("         Run:  pip install quantstats")

BASE_URL = "http://localhost:8010"

# ── Run 12 Validation Gates ───────────────────────────────────────────────
# Format: gate_key → (metric_key_in_result, threshold, operator, source)
#   source = "qs" → computed from return series | "api" → from JSON response
VALIDATION_GATES_RUN12: dict[str, tuple[str, float, str, str]] = {
    "min_profit_factor":    ("profit_factor",    2.0,  ">=", "api"),
    "min_sortino":          ("sortino",          1.0,  ">=", "qs"),
    "min_calmar":           ("calmar",           0.5,  ">=", "qs"),
    "min_tail_ratio":       ("tail_ratio",       1.0,  ">=", "qs"),
    "min_exposure":         ("exposure",         0.15, ">=", "qs"),
    "min_gain_to_pain":     ("gain_to_pain",     0.50, ">=", "qs"),
    "max_consecutive_loss": ("consecutive_losses", 8,  "<=", "qs"),
    "min_trades":           ("n_trades",         60,   ">=", "api"),
    "max_drawdown":         ("max_drawdown",     0.15, "<=", "api"),
    "min_win_rate":         ("win_rate",         0.55, ">=", "api"),
}


# ── HTTP helpers ──────────────────────────────────────────────────────────

def _get(path: str, params: dict | None = None) -> Any:
    try:
        r = requests.get(f"{BASE_URL}{path}", params=params, timeout=30)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.ConnectionError:
        print(f"ERROR: Cannot connect to engine at {BASE_URL}")
        sys.exit(1)
    except requests.exceptions.HTTPError as e:
        print(f"ERROR: HTTP {e.response.status_code} from {path}: {e.response.text[:200]}")
        sys.exit(1)


def _post(path: str, payload: dict) -> Any:
    try:
        r = requests.post(f"{BASE_URL}{path}", json=payload, timeout=120)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.ConnectionError:
        print(f"ERROR: Cannot connect to engine at {BASE_URL}")
        sys.exit(1)
    except requests.exceptions.HTTPError as e:
        print(f"ERROR: HTTP {e.response.status_code} from {path}: {e.response.text[:200]}")
        sys.exit(1)


# ── Return-series builder ─────────────────────────────────────────────────

def build_returns_from_trades(eval_result: dict) -> pd.Series | None:
    """
    Build a return series from the engine's evaluate response.

    Tries (in priority order):
      1. eval_result["trade_log"]     — list of {pnl, exit_date}
      2. eval_result["equity_curve"]  — list of {date, equity}
      3. eval_result["daily_returns"] — list of floats
    """
    trades = (eval_result.get("trade_log")
              or eval_result.get("trades")
              or eval_result.get("metrics", {}).get("trade_log")
              or [])

    if trades:
        rows = []
        capital = float(eval_result.get("starting_capital", 10_000))
        for t in trades:
            pnl = t.get("pnl") or t.get("profit") or t.get("net_pnl")
            ts  = t.get("exit_date") or t.get("date") or t.get("entry_date")
            if pnl is not None and ts is not None:
                rows.append({"date": pd.to_datetime(ts), "pnl": float(pnl)})
        if rows:
            df = pd.DataFrame(rows).sort_values("date").set_index("date")
            equity = capital + df["pnl"].cumsum()
            returns = equity.pct_change().dropna()
            returns.index = returns.index.tz_localize(None)
            return returns

    equity_curve = eval_result.get("equity_curve") or []
    if equity_curve:
        rows = [
            {"date": pd.to_datetime(pt.get("date") or pt.get("timestamp")),
             "equity": float(pt.get("equity") or pt.get("value", 0))}
            for pt in equity_curve
            if isinstance(pt, dict)
        ]
        if rows:
            df = pd.DataFrame(rows).sort_values("date").set_index("date")
            returns = df["equity"].pct_change().dropna()
            returns.index = returns.index.tz_localize(None)
            return returns

    daily = eval_result.get("daily_returns") or []
    if daily:
        if isinstance(daily[0], (int, float)):
            idx = pd.date_range(end=datetime.today(), periods=len(daily), freq="B")
            return pd.Series(daily, index=idx, dtype=float)

    return None


# ── QuantStats gate augmenter ─────────────────────────────────────────────

def augment_with_qs_metrics(metrics: dict, returns: pd.Series) -> dict:
    """Add qs.stats computed metrics to the metrics dict."""
    if not QS_AVAILABLE or returns is None or len(returns) < 5:
        return metrics

    try:
        metrics["sortino"]            = float(qs.stats.sortino(returns))
        metrics["calmar"]             = float(qs.stats.calmar(returns))
        metrics["tail_ratio"]         = float(qs.stats.tail_ratio(returns))
        metrics["exposure"]           = float(qs.stats.exposure(returns))
        metrics["gain_to_pain"]       = float(qs.stats.gain_to_pain_ratio(returns))
        metrics["consecutive_losses"] = int(qs.stats.consecutive_losses(returns))
        metrics["skew"]               = float(qs.stats.skew(returns))
        metrics["common_sense_ratio"] = float(qs.stats.common_sense_ratio(returns))
        metrics["ulcer_perf_index"]   = float(qs.stats.ulcer_performance_index(returns))
        metrics["_qs_computed"]       = True
    except Exception as e:
        print(f"  WARNING: qs.stats augmentation failed: {e}")

    return metrics


def evaluate_rl_run(
    symbol: str,
    model_path: str,
    days: int = 180,
) -> tuple[dict, pd.Series | None]:
    """
    Fetch OOS evaluation from engine and augment with qs.stats.
    Returns (augmented_metrics_dict, returns_series).
    """
    end_date   = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    payload = {
        "symbol":     symbol,
        "model_path": model_path,
        "start_date": start_date,
        "end_date":   end_date,
        "interval":   "1h",
    }
    print(f"\nEvaluating {symbol}  {start_date} → {end_date}  ({days}d OOS) …")
    raw = _post("/strategies/rl/evaluate", payload)

    # Normalise: some engine versions nest under "metrics"
    if "n_trades" not in raw and "metrics" in raw:
        metrics = {**raw, **raw["metrics"]}
    else:
        metrics = dict(raw)

    # Build return series and augment
    returns = build_returns_from_trades(raw)
    metrics = augment_with_qs_metrics(metrics, returns)
    return metrics, returns


# ── Gate checker ─────────────────────────────────────────────────────────

def check_gates(metrics: dict) -> tuple[int, int]:
    """Print Run 12 gate report and return (passed, total)."""
    passed = 0
    total  = len(VALIDATION_GATES_RUN12)
    qs_ok  = metrics.get("_qs_computed", False)

    print("\n" + "═" * 65)
    print("  RUN 12 VALIDATION GATES  (QuantStats Edition)")
    print("═" * 65)

    for gate_name, (metric_key, threshold, op, source) in VALIDATION_GATES_RUN12.items():
        value = metrics.get(metric_key)
        src_tag = f"[qs]" if source == "qs" else "[api]"

        if value is None:
            status, sym = "N/A ", "?"
        else:
            try:
                v = float(value)
                ok = (v >= threshold) if op == ">=" else (v <= threshold)
                status = "PASS" if ok else "FAIL"
                sym    = "✓" if ok else "✗"
                if ok:
                    passed += 1
            except (TypeError, ValueError):
                status, sym = "N/A ", "?"

        label     = gate_name.replace("_", " ").replace("min ", "").replace("max ", "").title()
        val_str   = f"{float(value):.4f}" if value is not None else "N/A"
        thresh_str = f"{op} {threshold}"
        qs_warn   = "  ⚠ qs unavailable — may be inaccurate" if source == "qs" and not qs_ok else ""
        print(
            f"  [{status}] {sym} {src_tag:5s} {label:<24}  {val_str:>10}  (need: {thresh_str}){qs_warn}"
        )

    print("═" * 65)
    return passed, total


# ── Summary printer ───────────────────────────────────────────────────────

def print_summary(metrics: dict, symbol: str, model_path: str) -> None:
    print("\n" + "═" * 65)
    print(f"  OOS RESULTS — {symbol}  (Run 12)")
    print("═" * 65)
    print(f"  Model:           {model_path.split('/')[-1].split(chr(92))[-1]}")
    print(f"  Trades:          {metrics.get('n_trades', 'N/A')}")

    wr = metrics.get("win_rate") or metrics.get("win_rate_pct")
    if wr is not None:
        wr = float(wr)
        print(f"  Win Rate:        {wr*100:.1f}%" if wr <= 1 else f"  Win Rate:        {wr:.1f}%")

    print(f"  Profit Factor:   {metrics.get('profit_factor', 'N/A')}")

    for label, key in [
        ("Sortino",         "sortino"),
        ("Calmar",          "calmar"),
        ("Tail Ratio",      "tail_ratio"),
        ("Exposure",        "exposure"),
        ("Gain-to-Pain",    "gain_to_pain"),
        ("Consec. Losses",  "consecutive_losses"),
        ("Skew",            "skew"),
    ]:
        v = metrics.get(key)
        if v is not None:
            print(f"  {label:<16}  {float(v):.4f}")

    dd = metrics.get("max_drawdown")
    if dd is not None:
        print(f"  Max Drawdown:    {float(dd)*100:.2f}%")

    qs_tag = "✓ computed via qs.stats" if metrics.get("_qs_computed") else "⚠ qs.stats unavailable"
    print(f"\n  Metrics source:  {qs_tag}")
    print("═" * 65)


# ── Main ──────────────────────────────────────────────────────────────────

def list_models(symbol: str) -> list[dict]:
    data   = _get("/strategies/rl/models", params={"symbol": symbol})
    models = data if isinstance(data, list) else data.get("models", [])
    return sorted(models, key=lambda m: m.get("path", m.get("filename", "")), reverse=True)


def get_training_status() -> dict:
    return _get("/strategies/rl/status")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="JARVIS RL Evaluator v2 — Run 12 QuantStats gates"
    )
    parser.add_argument("--symbol",     default="MES",  help="Symbol (default: MES)")
    parser.add_argument("--days",       type=int, default=180, help="OOS lookback days (default: 180)")
    parser.add_argument("--model-path", default=None,   help="Specific model path (default: latest)")
    parser.add_argument("--dry-run",    action="store_true", help="List models only, skip evaluation")
    parser.add_argument("--json",       action="store_true", help="Dump augmented metrics as JSON")
    args = parser.parse_args()

    symbol = args.symbol.upper()

    # Training state
    status = get_training_status()
    state  = status.get("state", "unknown")
    print(f"\nEngine training state: {state.upper()}")
    if state == "training":
        pct = status.get("progress_pct", 0)
        print(f"  ⚠ Training still in progress ({pct:.0f}%) — results may be incomplete.")

    # List models
    models = list_models(symbol)
    if not models:
        print(f"\nNo models found for {symbol}. Run training first.")
        return 1

    print(f"\nAvailable {symbol} models ({len(models)} total):")
    for i, m in enumerate(models[:5]):
        path   = m.get("path", m.get("filename", "unknown"))
        ts     = m.get("timestamp", m.get("created_at", ""))
        marker = " ← latest" if i == 0 else ""
        print(f"  [{i+1}] {path.split('/')[-1].split(chr(92))[-1]}  {ts}{marker}")
    if len(models) > 5:
        print(f"  … and {len(models) - 5} more")

    if args.dry_run:
        print("\n[dry-run] Skipping evaluation.")
        return 0

    model_path = args.model_path or models[0].get("path", models[0].get("filename"))
    if not model_path:
        print("ERROR: Could not determine model path. Use --model-path.")
        return 1

    # Evaluate
    metrics, returns = evaluate_rl_run(symbol, model_path, args.days)

    if args.json:
        safe_metrics = {k: (v if not isinstance(v, float) or np.isfinite(v) else None)
                        for k, v in metrics.items()}
        print(json.dumps(safe_metrics, indent=2, default=str))
        return 0

    print_summary(metrics, symbol, model_path)
    passed, total = check_gates(metrics)

    print()
    if passed == total:
        print(f"  ✓ PASSES RUN 12 VALIDATION — {passed}/{total} gates")
        print(f"    Ready for walk-forward evaluation and paper deployment.")
        return 0
    else:
        short = total - passed
        print(f"  ✗ FAILS VALIDATION — {passed}/{total} gates  ({short} short)")
        if not metrics.get("_qs_computed"):
            print("    ⚠ Install quantstats for full gate accuracy:  pip install quantstats")
        print("    Review RL reward config in engine/strategies/rl_config.py")
        return 1


if __name__ == "__main__":
    sys.exit(main())
