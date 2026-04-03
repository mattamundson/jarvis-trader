#!/usr/bin/env python3
"""
JARVIS TRADER — RL Run Evaluator
=================================
Fetches the latest trained RL model and runs OOS evaluation
via the engine's /strategies/rl/evaluate endpoint.

Usage:
    cd C:\\Users\\mattm\\ThinkorSwim\\jarvis-trader\\engine
    .venv\\Scripts\\python ..\\scripts\\eval_run9.py [--symbol MES] [--days 180]

Requirements:
    - Engine running at http://localhost:8010
    - At least one saved .zip model in data/rl_models/
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from typing import Any

try:
    import requests
except ImportError:
    print("ERROR: requests not installed. Run: pip install requests")
    sys.exit(1)

BASE_URL = "http://localhost:8010"

VALIDATION_GATES = {
    "min_profit_factor": ("profit_factor", 2.0, ">="),
    "min_sharpe":        ("sharpe",         1.5, ">="),
    "min_win_rate":      ("win_rate",        0.55, ">="),
    "min_trades":        ("n_trades",        60,  ">="),
    "min_hold_rate":     ("hold_rate",       0.50, ">="),
    "max_drawdown":      ("max_drawdown",    0.15, "<="),
}


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


def list_models(symbol: str) -> list[dict]:
    data = _get("/strategies/rl/models", params={"symbol": symbol})
    models = data if isinstance(data, list) else data.get("models", [])
    return sorted(models, key=lambda m: m.get("path", m.get("filename", "")), reverse=True)


def get_training_status() -> dict:
    return _get("/strategies/rl/status")


def evaluate_model(symbol: str, model_path: str, days: int) -> dict:
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    payload = {
        "symbol": symbol,
        "model_path": model_path,
        "start_date": start_date,
        "end_date": end_date,
        "interval": "1h",
    }
    print(f"Evaluating {symbol} from {start_date} to {end_date} ({days} days OOS)...")
    return _post("/strategies/rl/evaluate", payload)


def check_gates(results: dict) -> tuple[int, int]:
    passed = 0
    total = len(VALIDATION_GATES)
    print("\n" + "=" * 60)
    print("  VALIDATION GATES")
    print("=" * 60)
    for gate_name, (metric_key, threshold, op) in VALIDATION_GATES.items():
        value = results.get(metric_key, results.get("metrics", {}).get(metric_key))
        if value is None:
            status = "N/A "
            symbol = "?"
        elif op == ">=":
            ok = float(value) >= threshold
            status = "PASS" if ok else "FAIL"
            symbol = "✓" if ok else "✗"
            if ok:
                passed += 1
        else:  # "<="
            ok = float(value) <= threshold
            status = "PASS" if ok else "FAIL"
            symbol = "✓" if ok else "✗"
            if ok:
                passed += 1
        label = gate_name.replace("_", " ").replace("min ", "").replace("max ", "").title()
        val_str = f"{float(value):.4f}" if value is not None else "N/A"
        thresh_str = f"{op} {threshold}"
        print(f"  [{status}] {symbol} {label:<22} {val_str:>10}  (required: {thresh_str})")
    print("=" * 60)
    return passed, total


def print_summary(results: dict, symbol: str, model_path: str) -> None:
    metrics = results if "n_trades" in results else results.get("metrics", results)
    print("\n" + "=" * 60)
    print(f"  OOS EVALUATION RESULTS — {symbol}")
    print("=" * 60)
    print(f"  Model:          {model_path.split('/')[-1].split(chr(92))[-1]}")
    print(f"  Trades:         {metrics.get('n_trades', 'N/A')}")
    win_rate = metrics.get('win_rate', metrics.get('win_rate_pct'))
    print(f"  Win Rate:       {float(win_rate)*100:.1f}%" if win_rate is not None else "  Win Rate:       N/A")
    print(f"  Profit Factor:  {metrics.get('profit_factor', 'N/A')}")
    print(f"  Sharpe:         {metrics.get('sharpe', 'N/A')}")
    dd = metrics.get('max_drawdown')
    print(f"  Max Drawdown:   {float(dd)*100:.2f}%" if dd is not None else "  Max Drawdown:   N/A")
    t1 = metrics.get('t1_hit_rate')
    print(f"  T1 Hit Rate:    {float(t1)*100:.1f}%" if t1 is not None else "  T1 Hit Rate:    N/A")
    avg_bars = metrics.get('avg_bars_in_trade')
    print(f"  Avg Bars/Trade: {avg_bars}" if avg_bars is not None else "  Avg Bars/Trade: N/A")
    hold = metrics.get('hold_rate', metrics.get('flat_hold_rate'))
    print(f"  Hold Rate:      {float(hold)*100:.1f}%" if hold is not None else "  Hold Rate:      N/A")
    print("=" * 60)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate latest JARVIS TRADER RL model via engine API"
    )
    parser.add_argument("--symbol",     default="MES",  help="Symbol to evaluate (default: MES)")
    parser.add_argument("--days",       type=int, default=180, help="OOS lookback days (default: 180)")
    parser.add_argument("--model-path", default=None,   help="Specific model path (default: latest)")
    parser.add_argument("--dry-run",    action="store_true", help="List models only, skip evaluation")
    args = parser.parse_args()

    symbol = args.symbol.upper()

    # Show last training result
    status = get_training_status()
    state = status.get("state", "unknown")
    print(f"\nEngine training state: {state.upper()}")
    if state == "training":
        pct = status.get("progress_pct", 0)
        print(f"  WARNING: Training still in progress ({pct:.0f}%). Results may be incomplete.")

    # List available models
    models = list_models(symbol)
    if not models:
        print(f"\nNo models found for {symbol}. Run training first:")
        print("  bash scripts/launch_run9.sh --symbol", symbol)
        return 1

    print(f"\nAvailable {symbol} models ({len(models)} total):")
    for i, m in enumerate(models[:5]):
        path = m.get("path", m.get("filename", "unknown"))
        ts = m.get("timestamp", m.get("created_at", ""))
        marker = " ← latest" if i == 0 else ""
        print(f"  [{i+1}] {path.split('/')[-1].split(chr(92))[-1]}  {ts}{marker}")
    if len(models) > 5:
        print(f"  ... and {len(models) - 5} more")

    if args.dry_run:
        print("\n[dry-run] Skipping evaluation.")
        return 0

    # Pick model
    model_path = args.model_path or models[0].get("path", models[0].get("filename"))
    if not model_path:
        print("ERROR: Could not determine model path. Use --model-path to specify.")
        return 1

    print(f"\nSelected: {model_path.split('/')[-1].split(chr(92))[-1]}")

    # Run evaluation
    results = evaluate_model(symbol, model_path, args.days)

    # Print summary
    print_summary(results, symbol, model_path)

    # Check validation gates
    passed, total = check_gates(results if "n_trades" in results else results.get("metrics", results))

    # Final verdict
    print()
    if passed == total:
        print(f"  ✓ PASSES VALIDATION — {passed}/{total} gates passed")
        print(f"  Ready for walk-forward validation and paper deployment.")
        return 0
    else:
        print(f"  ✗ FAILS VALIDATION — {passed}/{total} gates passed")
        print(f"  Review failed gates and adjust REWARD_CONFIG in engine/strategies/rl_config.py")
        print(f"  See docs/rl-run7-decision-tree.md for tuning scenarios.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
