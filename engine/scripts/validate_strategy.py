"""Strategy validator — Tier A statistical battery over research-script results.

Loads a per-combo result (by rank) from a research-script JSON (e.g.,
`mes_trend_search_results.json`), extracts the per-trade PnL list, and runs
the full Tier A validation battery:

  * bootstrap_pf (IID resampling with replacement)
  * moving_block_bootstrap (serial-correlation-aware, block = ceil(sqrt(N)))
  * bootstrap_sharpe
  * bootstrap_max_dd (permutation-based, path-dependent)
  * deflated_sharpe_from_returns (multiple-testing correction across N grid
    combinations)

Output: a JSON report with a proposed-gate-v2 verdict and reason list.

Proposed gate v2 (from Tier A plan memo A10):
    (bootstrap_pf_ci_95_lower >= 1.10)
    AND (p_positive_edge >= 0.95)
    AND (mc_95th_max_dd_pct <= 5.0)     # % of initial capital
    AND (dsr_p_value <= 0.10 passes as significance)

Usage (from engine/):
    .venv/Scripts/python -m scripts.validate_strategy \\
        --results-file scripts/mes_trend_search_results.json \\
        --rank 1 \\
        --output validation_reports/mes_rank1.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent
_ENGINE = _HERE.parent
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

from backtest.deflated_sharpe import deflated_sharpe_from_returns  # noqa: E402
from backtest.monte_carlo import (  # noqa: E402
    bootstrap_max_dd,
    bootstrap_pf,
    bootstrap_sharpe,
    moving_block_bootstrap,
)

# Proposed gate v2 thresholds (see plan A10)
GATE_V2 = {
    "pf_ci_lower_min": 1.10,
    "p_positive_edge_min": 0.95,
    "max_dd_95th_pct_max": 5.0,
    "dsr_min_for_significance": 0.10,
}


def _load_result(results_file: Path, rank: int) -> dict:
    """Load rank-th result from a research-script JSON.

    Research scripts sort results[] by PF descending, so rank=1 is best.
    """
    with open(results_file, "r") as f:
        doc = json.load(f)
    results = doc.get("results", [])
    if not results:
        raise ValueError(f"No results in {results_file}")
    if rank < 1 or rank > len(results):
        raise ValueError(f"rank={rank} out of range (1..{len(results)})")
    entry = results[rank - 1]
    return {
        "symbol": doc.get("symbol", "UNKNOWN"),
        "n_grid_trials": doc.get("n_combos", len(results)),
        "start": doc.get("start"),
        "end": doc.get("end"),
        "interval": doc.get("interval"),
        "combo": entry,
    }


def _load_result_from_wfo(results_file: Path, symbol: str, rank: int,
                          window: str = "test") -> dict:
    """Load rank-th result from multi_symbol_trend_wfo output (nested shape)."""
    with open(results_file, "r") as f:
        doc = json.load(f)
    summary = doc.get("summary", {})
    key = f"{symbol.upper()}_wfo"
    if key not in summary:
        raise KeyError(f"{key} not in WFO summary. Available: {list(summary.keys())}")
    top = summary[key].get("top_5", [])
    if rank < 1 or rank > len(top):
        raise ValueError(f"rank={rank} out of top_5 range")
    return {
        "symbol": symbol.upper(),
        "n_grid_trials": len(summary[key].get("top_5", [])),
        "start": doc.get("train" if window == "train" else "test", [None, None])[0],
        "end": doc.get("train" if window == "train" else "test", [None, None])[1],
        "interval": "1h",
        "combo": top[rank - 1],
        "window": window,
    }


def _extract_pnls(combo: dict, window: str | None = None) -> list[float]:
    """Pull per-trade PnLs out of a research result entry.

    Shapes supported:
        {"trades": [{"pnl": ...}, ...]}                  — flat research scripts
        {"train": {..., "trades": [...]}, "test": {...}} — WFO shape
    """
    if window and window in combo:
        window_obj = combo[window]
        trades = window_obj.get("trades", [])
    else:
        trades = combo.get("trades", [])

    if not trades:
        raise ValueError("No 'trades' field in result. Re-run research script to "
                         "regenerate JSON — per-trade emission was added in A2.")
    return [float(t["pnl"]) for t in trades]


def _evaluate_gate_v2(report: dict) -> dict:
    """Apply proposed gate v2 thresholds; return PASS / MARGINAL / FAIL + reasons."""
    reasons = []
    passes = []

    pf_lo = report["bootstrap_iid"]["pf_ci_95_low"]
    if pf_lo >= GATE_V2["pf_ci_lower_min"]:
        passes.append(True)
        reasons.append(f"pf_ci_lower={pf_lo} >= {GATE_V2['pf_ci_lower_min']}")
    else:
        passes.append(False)
        reasons.append(f"FAIL pf_ci_lower={pf_lo} < {GATE_V2['pf_ci_lower_min']}")

    p_edge = report["bootstrap_iid"]["p_positive_edge"]
    if p_edge >= GATE_V2["p_positive_edge_min"]:
        passes.append(True)
        reasons.append(f"p_positive_edge={p_edge} >= {GATE_V2['p_positive_edge_min']}")
    else:
        passes.append(False)
        reasons.append(f"FAIL p_positive_edge={p_edge} < {GATE_V2['p_positive_edge_min']}")

    mc_95 = report["drawdown_mc"]["mc_95th"]
    if mc_95 <= GATE_V2["max_dd_95th_pct_max"]:
        passes.append(True)
        reasons.append(f"mc_95th_dd_pct={mc_95} <= {GATE_V2['max_dd_95th_pct_max']}")
    else:
        passes.append(False)
        reasons.append(f"FAIL mc_95th_dd_pct={mc_95} > {GATE_V2['max_dd_95th_pct_max']}")

    dsr = report["deflated_sharpe"]["dsr"]
    if dsr >= GATE_V2["dsr_min_for_significance"]:
        passes.append(True)
        reasons.append(f"dsr={dsr} >= {GATE_V2['dsr_min_for_significance']} (not selection-bias)")
    else:
        passes.append(False)
        reasons.append(f"FAIL dsr={dsr} < {GATE_V2['dsr_min_for_significance']} (selection bias)")

    n_passed = sum(passes)
    if n_passed == 4:
        verdict = "PASS"
    elif n_passed >= 2:
        verdict = "MARGINAL"
    else:
        verdict = "FAIL"

    return {"verdict": verdict, "reasons": reasons, "n_passed": n_passed, "n_criteria": 4}


def validate(pnls: list[float], n_grid_trials: int,
             initial_capital: float = 10_000.0,
             n_resamples: int = 10_000,
             seed: int = 42) -> dict:
    """Run the full validation battery on a PnL list.

    Returns the report dict without the gate-evaluation wrapper — useful for
    programmatic callers (tests, notebooks, bulk sweeps).
    """
    pnls_arr = np.asarray(pnls, dtype=float)
    raw_pf = float(
        pnls_arr[pnls_arr > 0].sum() / max(abs(pnls_arr[pnls_arr < 0].sum()), 1e-12)
    ) if len(pnls_arr) > 0 else 0.0

    # Returns-as-fraction-of-capital for Sharpe computation (per-trade basis)
    returns = pnls_arr / initial_capital

    return {
        "raw": {
            "n_trades": int(len(pnls_arr)),
            "net_pnl": round(float(pnls_arr.sum()), 2),
            "pf": round(raw_pf, 4),
            "ret_pct": round(float(pnls_arr.sum() / initial_capital * 100), 2),
        },
        "bootstrap_iid": bootstrap_pf(pnls_arr, n_resamples=n_resamples, seed=seed),
        "bootstrap_block": moving_block_bootstrap(pnls_arr, n_resamples=n_resamples, seed=seed),
        "sharpe_ci": bootstrap_sharpe(pnls_arr, initial_capital=initial_capital,
                                       n_resamples=n_resamples, seed=seed),
        "drawdown_mc": bootstrap_max_dd(pnls_arr, initial_capital=initial_capital,
                                         n_resamples=n_resamples, seed=seed),
        "deflated_sharpe": deflated_sharpe_from_returns(
            returns=returns.tolist(), n_trials=n_grid_trials, ann_factor=252.0,
        ),
    }


def main():
    ap = argparse.ArgumentParser(description="Tier A strategy validator")
    ap.add_argument("--results-file", required=True,
                    help="Path to research-script results JSON")
    ap.add_argument("--rank", type=int, default=1,
                    help="1-indexed rank within results[] (1 = best PF)")
    ap.add_argument("--symbol", default=None,
                    help="Required for WFO-shaped JSONs (multi_symbol_trend_wfo)")
    ap.add_argument("--window", default="test", choices=["train", "test"],
                    help="For WFO-shaped JSONs: which window to validate")
    ap.add_argument("--output", default=None,
                    help="Output report JSON path (default: derived from input)")
    ap.add_argument("--initial-capital", type=float, default=10_000.0)
    ap.add_argument("--n-resamples", type=int, default=10_000)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    results_file = Path(args.results_file).resolve()
    if not results_file.exists():
        print(f"[ERROR] results file not found: {results_file}", flush=True)
        return 1

    t0 = time.time()

    # Detect shape: WFO has summary.{SYM}_wfo; flat scripts have top-level results[]
    with open(results_file) as f:
        doc_peek = json.load(f)
    is_wfo = "summary" in doc_peek and any(k.endswith("_wfo") for k in doc_peek["summary"])

    if is_wfo:
        if not args.symbol:
            print("[ERROR] --symbol is required for WFO-shaped JSONs", flush=True)
            return 1
        loaded = _load_result_from_wfo(results_file, args.symbol, args.rank, args.window)
        pnls = _extract_pnls(loaded["combo"], window=args.window)
        params_str = json.dumps(loaded["combo"].get("params", {}))
    else:
        loaded = _load_result(results_file, args.rank)
        pnls = _extract_pnls(loaded["combo"])
        params_str = json.dumps(loaded["combo"].get("params", {}))

    print(f"Validating: {loaded['symbol']} rank={args.rank} params={params_str}", flush=True)
    print(f"  n_trades={len(pnls)} n_grid_trials={loaded['n_grid_trials']}", flush=True)

    report = validate(pnls, n_grid_trials=loaded["n_grid_trials"],
                      initial_capital=args.initial_capital,
                      n_resamples=args.n_resamples, seed=args.seed)

    gate = _evaluate_gate_v2(report)
    report["gate_v2"] = gate
    report["strategy"] = {
        "symbol": loaded["symbol"],
        "interval": loaded.get("interval"),
        "params": loaded["combo"].get("params"),
        "start": loaded.get("start"),
        "end": loaded.get("end"),
        "rank_in_grid": args.rank,
    }
    report["elapsed_sec"] = round(time.time() - t0, 2)

    # Print summary
    print("\n=== TIER A VALIDATION REPORT ===", flush=True)
    print(f"Raw:        PF={report['raw']['pf']:.3f}  net_pnl=${report['raw']['net_pnl']}  n={report['raw']['n_trades']}", flush=True)
    print(f"Bootstrap:  PF median={report['bootstrap_iid']['median_pf']:.3f}  "
          f"CI=[{report['bootstrap_iid']['pf_ci_95_low']:.3f}, "
          f"{report['bootstrap_iid']['pf_ci_95_high']:.3f}]  "
          f"p_edge={report['bootstrap_iid']['p_positive_edge']:.3f}", flush=True)
    print(f"Block-bs:   PF median={report['bootstrap_block']['median_pf']:.3f}  "
          f"CI=[{report['bootstrap_block']['pf_ci_95_low']:.3f}, "
          f"{report['bootstrap_block']['pf_ci_95_high']:.3f}]  "
          f"block={report['bootstrap_block']['block_size']}", flush=True)
    print(f"Sharpe:     median={report['sharpe_ci']['median_sharpe']:.3f}  "
          f"CI=[{report['sharpe_ci']['sharpe_ci_95_low']:.3f}, "
          f"{report['sharpe_ci']['sharpe_ci_95_high']:.3f}]", flush=True)
    print(f"MaxDD MC:   obs={report['drawdown_mc']['observed_max_dd_pct']:.2f}%  "
          f"95th={report['drawdown_mc']['mc_95th']:.2f}%  99th={report['drawdown_mc']['mc_99th']:.2f}%", flush=True)
    print(f"DSR:        raw_sr={report['deflated_sharpe']['raw_sharpe']:.3f}  "
          f"E[max|N]={report['deflated_sharpe']['expected_max_sharpe']:.3f}  "
          f"dsr={report['deflated_sharpe']['dsr']:.3f}  "
          f"passes_10pct={report['deflated_sharpe']['passes_at_10pct']}", flush=True)
    print(f"\nGate v2 verdict: {gate['verdict']} ({gate['n_passed']}/{gate['n_criteria']} criteria)", flush=True)
    for reason in gate["reasons"]:
        print(f"  - {reason}", flush=True)

    if args.output:
        out_path = Path(args.output).resolve()
    else:
        out_path = results_file.parent / "validation_reports" / \
                   f"{loaded['symbol']}_rank{args.rank}_report.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nSaved report to {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
