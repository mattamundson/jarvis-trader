"""
JARVIS TRADER — Parameter Sensitivity Analysis
Measures strategy robustness by varying each parameter individually
around its optimal value and observing performance degradation.

A strategy that only works at one exact parameter set is overfit.
A robust strategy shows stable performance across a range of values.

Usage:
    python -m backtest.sensitivity --symbol SPY --interval 1h --start 2024-06-01 --end 2026-03-27
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from backtest.backtester import Backtester, BacktestResult
from backtest.data_loader import BacktestDataLoader
from backtest.optimizer import _compute_signals

# ── Parameter ranges for sensitivity sweep ────────────────────────────────────

PARAM_RANGES: Dict[str, list] = {
    "stc_os": [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20],
    "stc_ob": [77, 78, 79, 80, 81, 83, 85, 86, 87, 88, 89],
    "stop_atr": [0.40, 0.50, 0.56, 0.63, 0.70, 0.77, 0.84, 0.90, 1.00],
    "t1_atr": [1.00, 1.20, 1.35, 1.50, 1.65, 1.80, 2.00, 2.20, 2.50],
}

# Map sensitivity param names → _compute_signals kwarg names
_PARAM_TO_KWARG = {
    "stc_os": "stc_oversold",
    "stc_ob": "stc_overbought",
    "stop_atr": "atr_stop_mult",
    "t1_atr": "atr_target_mult",
}

DEFAULT_BASE_PARAMS = {
    "stc_os": 15,
    "stc_ob": 83,
    "stop_atr": 0.70,
    "t1_atr": 1.50,
}


def _run_single_backtest(
    df_base: pd.DataFrame,
    multiplier: float,
    capital: float,
    stc_os: float,
    stc_ob: float,
    stop_atr: float,
    t1_atr: float,
) -> Optional[BacktestResult]:
    """Run a single backtest with the given parameter set."""
    try:
        df = _compute_signals(
            df_base.copy(),
            stc_oversold=stc_os,
            stc_overbought=stc_ob,
            atr_stop_mult=stop_atr,
            atr_target_mult=t1_atr,
            regime_filter=True,
        )
        backtester = Backtester(initial_capital=capital, risk_per_trade=0.01)
        return backtester.run(df, "SENS", multiplier)
    except Exception:
        return None


def _extract_metrics(result: Optional[BacktestResult]) -> Dict[str, float]:
    """Pull the key metrics from a BacktestResult."""
    if result is None or result.total_trades < 1:
        return {
            "pf": 0.0,
            "sharpe": 0.0,
            "return": 0.0,
            "win_rate": 0.0,
            "trades": 0,
        }
    return {
        "pf": round(min(result.profit_factor, 999.0), 3),
        "sharpe": round(result.sharpe_ratio, 3),
        "return": round(result.total_return_pct * 100, 2),
        "win_rate": round(result.win_rate * 100, 1),
        "trades": result.total_trades,
    }


def _compute_stability(pf_values: List[float]) -> float:
    """
    Stability score for a parameter dimension.
    stability = 100 - (std(pf) / mean(pf)) * 100
    Higher = more stable. Clamped to [0, 100].
    """
    arr = np.array([v for v in pf_values if v > 0])
    if len(arr) < 2 or arr.mean() <= 0:
        return 0.0
    cv = (arr.std() / arr.mean()) * 100.0
    return round(max(0.0, min(100.0, 100.0 - cv)), 1)


def sweep_param_sensitivity(
    run_fn,
    param_ranges: Dict[str, list],
    base_params: Dict[str, Any],
    *,
    neighbors: int = 3,
    progress: bool = False,
) -> Dict[str, Any]:
    """Strategy-agnostic parameter-sensitivity sweep.

    ``run_fn(params: dict) -> metrics`` must return a metrics dict containing at
    least ``"pf"`` (float) and ``"trades"`` (int) — ``_extract_metrics`` produces
    exactly this shape, but any study can supply its own adapter. For each
    parameter in ``param_ranges`` the others are pinned at ``base_params`` and the
    target is swept across its range; PF percent-change-from-base is recorded per
    point. Per-parameter stability uses the ``neighbors`` closest values on each
    side of base (CV-based, via ``_compute_stability``); the verdict keys off the
    WORST per-parameter stability.

    Returns ``{base_params, base_result, sensitivity, stability_scores, verdict}``.
    This is the reusable core; the STC ``run_sensitivity_analysis`` and the
    singlefinder driver are thin adapters over it.
    """
    base_metrics = run_fn(dict(base_params))
    base_pf = float(base_metrics.get("pf", 0.0))

    total_runs = sum(len(v) for v in param_ranges.values())
    run_count = 0

    sensitivity: Dict[str, List[Dict]] = {}
    stability_scores: Dict[str, float] = {}

    for param_name, values in param_ranges.items():
        param_results: List[Dict] = []

        for val in values:
            run_count += 1
            if progress and (run_count % 5 == 0 or run_count == total_runs):
                print(f"  [{run_count}/{total_runs}] Sweeping {param_name}={val}", end="\r")

            run_params = dict(base_params)
            run_params[param_name] = val
            metrics = run_fn(run_params)

            if base_pf > 0:
                pct_change = round(((float(metrics.get("pf", 0.0)) - base_pf) / base_pf) * 100, 1)
            else:
                pct_change = 0.0

            param_results.append(
                {
                    "value": val,
                    "pf": metrics.get("pf", 0.0),
                    "sharpe": metrics.get("sharpe", 0.0),
                    "return": metrics.get("return", 0.0),
                    "win_rate": metrics.get("win_rate", 0.0),
                    "trades": metrics.get("trades", 0),
                    "pct_change_from_base": pct_change,
                }
            )

        sensitivity[param_name] = param_results

        # ── Stability: `neighbors` closest values on each side of base ────
        base_val = base_params[param_name]
        try:
            base_idx = values.index(base_val)
            start_idx = max(0, base_idx - neighbors)
            end_idx = min(len(values), base_idx + neighbors + 1)  # exclusive
            nearby_values = values[start_idx:end_idx]
        except ValueError:
            # Base value not in range; use the closest (2*neighbors+1) centered on it.
            nearby_values = sorted(values, key=lambda v: abs(v - base_val))[: 2 * neighbors + 1]
        nearby_pfs = [r["pf"] for r in param_results if r["value"] in nearby_values]
        stability_scores[param_name] = _compute_stability(nearby_pfs)

    if progress:
        print()  # newline after progress

    all_scores = list(stability_scores.values())
    overall = round(float(np.mean(all_scores)), 1) if all_scores else 0.0
    stability_scores["overall"] = overall

    min_score = min(all_scores) if all_scores else 0.0
    if min_score > 70:
        verdict = "ROBUST"
    elif min_score > 50:
        verdict = "ACCEPTABLE"
    else:
        verdict = "FRAGILE"

    return {
        "base_params": dict(base_params),
        "base_result": base_metrics,
        "sensitivity": sensitivity,
        "stability_scores": stability_scores,
        "verdict": verdict,
    }


def run_sensitivity_analysis(
    df: pd.DataFrame,
    symbol: str,
    multiplier: float,
    base_params: Optional[Dict[str, float]] = None,
    capital: float = 10_000.0,
) -> Dict[str, Any]:
    """STC sensitivity analysis — thin adapter over ``sweep_param_sensitivity``.

    Sweeps the 4 STC parameters (stc_os/stc_ob/stop_atr/t1_atr) around their base
    values, holding the others fixed. Returns the same dict shape as the generic
    core: base_params, base_result, sensitivity, stability_scores, verdict.
    """
    if base_params is None:
        base_params = DEFAULT_BASE_PARAMS.copy()

    def _stc_run_fn(params: Dict[str, Any]) -> Dict[str, float]:
        result = _run_single_backtest(
            df,
            multiplier,
            capital,
            stc_os=params["stc_os"],
            stc_ob=params["stc_ob"],
            stop_atr=params["stop_atr"],
            t1_atr=params["t1_atr"],
        )
        return _extract_metrics(result)

    return sweep_param_sensitivity(_stc_run_fn, PARAM_RANGES, base_params, progress=True)


def format_sensitivity_report(result: Dict[str, Any]) -> str:
    """Format the sensitivity analysis result as a human-readable report."""
    bp = result["base_params"]
    br = result["base_result"]
    lines = []

    lines.append("=== PARAMETER SENSITIVITY ANALYSIS ===")
    lines.append(
        f"Base: STC_OS={bp['stc_os']}, STC_OB={bp['stc_ob']}, "
        f"Stop={bp['stop_atr']:.2f} ATR, T1={bp['t1_atr']:.2f} ATR"
    )
    lines.append(
        f"Base Results: PF={br['pf']:.2f}  Sharpe={br['sharpe']:.2f}  "
        f"Return={br['return']:+.1f}%  WR={br['win_rate']:.1f}%  "
        f"Trades={br['trades']}"
    )
    lines.append("")

    param_labels = {
        "stc_os": "STC_OS (Oversold Threshold)",
        "stc_ob": "STC_OB (Overbought Threshold)",
        "stop_atr": "Stop ATR Multiple",
        "t1_atr": "T1 ATR Multiple (Target 1)",
    }

    for param_name, data_points in result["sensitivity"].items():
        label = param_labels.get(param_name, param_name)
        base_val = bp[param_name]
        stability = result["stability_scores"].get(param_name, 0.0)

        lines.append(f"{label}:")
        lines.append(
            f"  {'Value':>8}  {'Trades':>6}  {'WR%':>6}  {'PF':>7}  "
            f"{'Sharpe':>7}  {'Return%':>8}  {'vs Base':>8}"
        )

        for pt in data_points:
            is_base = pt["value"] == base_val
            marker = "  <- base" if is_base else ""
            vs_base = "--" if is_base else f"{pt['pct_change_from_base']:+.0f}%"

            # Format value: integer for stc params, float for ATR params
            if param_name in ("stc_os", "stc_ob"):
                val_str = f"{int(pt['value']):>8}"
            else:
                val_str = f"{pt['value']:>8.2f}"

            lines.append(
                f"  {val_str}  {pt['trades']:>6}  {pt['win_rate']:>6.1f}  "
                f"{pt['pf']:>7.2f}  {pt['sharpe']:>7.2f}  "
                f"{pt['return']:>+8.1f}  {vs_base:>8}{marker}"
            )

        lines.append(f"  Stability Score: {stability:.0f}/100")
        lines.append("")

    lines.append(f"OVERALL STABILITY: {result['stability_scores']['overall']:.0f}/100")
    lines.append(f"VERDICT: {result['verdict']}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="JARVIS TRADER — Parameter Sensitivity Analysis")
    parser.add_argument("--symbol", default="SPY", help="Symbol to analyze")
    parser.add_argument("--interval", default="1h", help="Bar interval (1h, 1d)")
    parser.add_argument("--start", default="2024-06-01", help="Start date")
    parser.add_argument("--end", default="2026-03-27", help="End date")
    parser.add_argument("--capital", type=float, default=10_000.0, help="Initial capital")
    parser.add_argument("--stc-os", type=int, default=15, help="Base STC oversold")
    parser.add_argument("--stc-ob", type=int, default=83, help="Base STC overbought")
    parser.add_argument("--stop-atr", type=float, default=0.70, help="Base stop ATR mult")
    parser.add_argument("--t1-atr", type=float, default=1.50, help="Base T1 ATR mult")
    args = parser.parse_args()

    base_params = {
        "stc_os": args.stc_os,
        "stc_ob": args.stc_ob,
        "stop_atr": args.stop_atr,
        "t1_atr": args.t1_atr,
    }

    print(f"\n[Sensitivity] Loading data for {args.symbol} ({args.interval})...")
    loader = BacktestDataLoader()
    df = loader.load(args.symbol, args.start, args.end, args.interval)
    if df is None or df.empty:
        print(f"[Sensitivity] No data for {args.symbol}. Aborting.")
        return

    multiplier = loader.get_multiplier(args.symbol)
    print(f"[Sensitivity] {len(df)} bars loaded. Multiplier={multiplier}")
    print(f"[Sensitivity] Base params: {base_params}")
    print(
        f"[Sensitivity] Running ~{sum(len(v) for v in PARAM_RANGES.values())} backtest variations...\n"
    )

    result = run_sensitivity_analysis(df, args.symbol, multiplier, base_params, args.capital)

    # Print report
    report = format_sensitivity_report(result)
    print("\n" + report)

    # Save JSON results
    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    out_path = results_dir / f"{args.symbol}_{args.interval}_sensitivity.json"
    out_path.write_text(json.dumps(result, indent=2))
    print(f"\nResults saved to: {out_path}")

    # Save text report
    report_path = results_dir / f"{args.symbol}_{args.interval}_sensitivity_report.txt"
    report_path.write_text(report)
    print(f"Report saved to: {report_path}")


if __name__ == "__main__":
    main()
