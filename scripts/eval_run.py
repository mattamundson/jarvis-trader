#!/usr/bin/env python3
"""eval_run.py — generalized RL run evaluator with the Run-12 gate set.

Replaces the per-run eval_run9.py pattern. Audit F-12 deliverable (2026-06-11),
gate design per the April 2026 QuantStats analysis §4.5:

- sharpe>=1.5 is DROPPED as a gate (too much sampling variance at 60 trades;
  penalizes t1_bonus upside volatility symmetrically). Replaced by
  sortino + calmar + tail_ratio + gain_to_pain + consecutive_losses.
- PF/WR/DD relaxed for intraday futures during ITERATION; --production restores
  the strict thresholds for go/no-go decisions.

Usage:
    engine\\.venv\\Scripts\\python.exe scripts\\eval_run.py <run_name> [--production]

Exit: 0 all gates pass, 1 any gate fails, 2 usage/data error.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENGINE_DIR = REPO_ROOT / "engine"
sys.path.insert(0, str(ENGINE_DIR))

import pandas as pd  # noqa: E402
import requests  # noqa: E402

from reports.quantstats_metrics import compute_quantstats_metrics  # noqa: E402

ENGINE_BASE = os.environ.get("JARVIS_ENGINE_URL", "http://127.0.0.1:8010")

# Iteration gates (Run-12 set) — tuned for learning loops on intraday futures.
ITERATION_GATES: dict[str, tuple[str, float]] = {
    "profit_factor": (">=", 1.5),
    "win_rate": (">=", 0.52),
    "max_dd": ("<=", 0.20),  # abs()
    "sortino": (">=", 1.0),
    "calmar": (">=", 0.5),
    "tail_ratio": (">=", 1.0),
    "gain_to_pain": (">=", 0.5),
    "consecutive_losses": ("<=", 8),
    # Run-12 additions: skew floor (distribution quality) + exposure floor
    # (ensures the strategy is actually deployed, not trivially safe).
    "skew": (">=", -1.5),
    "exposure": (">=", 0.15),
}

# Production gates — strict go/no-go thresholds.
PRODUCTION_GATES: dict[str, tuple[str, float]] = {
    "profit_factor": (">=", 2.0),
    "win_rate": (">=", 0.55),
    "max_dd": ("<=", 0.15),
    "sortino": (">=", 1.5),
    "calmar": (">=", 1.0),
    "tail_ratio": (">=", 1.0),
    "gain_to_pain": (">=", 0.7),
    "consecutive_losses": ("<=", 6),
    # Run-12 additions (tightened for production).
    "skew": (">=", -1.5),
    "exposure": (">=", 0.20),
}

MIN_TRADES = 60  # engine-sourced sample floors stay unchanged
MIN_DAYS = 30


def _api_key() -> str:
    env_path = ENGINE_DIR / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("API_KEY="):
                return line.split("=", 1)[1].strip()
    return os.environ.get("API_KEY", "")


def evaluate_rl_run(run_name: str, production: bool = False) -> int:
    gates = PRODUCTION_GATES if production else ITERATION_GATES

    resp = requests.post(
        f"{ENGINE_BASE}/strategies/rl/evaluate",
        json={"run_name": run_name},
        headers={"X-API-Key": _api_key()},
        timeout=300,
    )
    resp.raise_for_status()
    data = resp.json()
    trades = data.get("trades", [])
    if not trades:
        print(f"[eval] no trades returned for {run_name} — cannot evaluate")
        return 2

    returns = (
        pd.Series({pd.to_datetime(t["exit_time"]): t["pnl_pct"] / 100.0 for t in trades})
        .sort_index()
    )
    # Aggregate to daily before annualized stats (trade-indexed annualization
    # with periods=252 is wrong for intraday — see analysis §2.4).
    daily = returns.groupby(returns.index.normalize()).sum()

    metrics = compute_quantstats_metrics(daily, source="rl_eval")
    metrics["n_trades"] = len(trades)
    n_days = daily.index.nunique()

    failures: list[str] = []
    if len(trades) < MIN_TRADES:
        failures.append(f"min_trades: {len(trades)} < {MIN_TRADES}")
    if n_days < MIN_DAYS:
        failures.append(f"min_days: {n_days} < {MIN_DAYS}")
    for gate, (op, threshold) in gates.items():
        val = metrics.get(gate)
        if val is None:
            failures.append(f"{gate}: MISSING")
            continue
        if gate == "max_dd":
            val = abs(val)
        ok = (op == ">=" and val >= threshold) or (op == "<=" and val <= threshold)
        if not ok:
            failures.append(f"{gate}: {val:.4f} (need {op} {threshold})")

    mode = "PRODUCTION" if production else "ITERATION"
    print(f"\n=== RL eval: {run_name} ({mode} gates) ===")
    print(f"  trades: {len(trades)}  days: {n_days}")
    diag_keys = list(gates) + [
        "sharpe", "skew", "kurtosis", "ulcer_index", "ulcer_perf_index",
        "exposure", "outlier_loss_ratio", "recovery_factor", "cpc_index",
    ]
    for k in diag_keys:
        v = metrics.get(k)
        gate_mark = ""
        if k in gates and v is not None:
            op, thresh = gates[k]
            vv = abs(v) if k == "max_dd" else v
            gate_mark = "  PASS" if (
                (op == ">=" and vv >= thresh) or (op == "<=" and vv <= thresh)
            ) else "  FAIL"
        print(f"  {k:<22} {v if v is None else round(float(v), 4)!s:>12}{gate_mark}")

    if failures:
        print(f"\nFAILED ({len(failures)}):")
        for f in failures:
            print(f"  {f}")
        return 1
    print("\nALL GATES PASSED")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1].startswith("-"):
        print(__doc__)
        sys.exit(2)
    sys.exit(evaluate_rl_run(sys.argv[1], production="--production" in sys.argv))
