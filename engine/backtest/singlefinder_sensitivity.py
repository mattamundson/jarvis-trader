"""Sensitivity + sub-period stability audit for the singlefinder champion (Task 2).

The singlefinder ALT-path PASS (`MGC_singlefinder_fill_rank1`, pf_ci_lower≈1.05)
is the only edge-validation candidate with a believable per-window sample. This
driver kills-or-confirms it two ways, reusing the strategy-agnostic
`sweep_param_sensitivity` core:

  1. PARAM sensitivity — sweep the one knob (`min_single_ticks`) around the
     champion (=2) on the full dataset; a robust edge holds across the
     neighborhood, an overfit one spikes only at the exact value.
  2. SUB-PERIOD stability — the dispersion of the 7 per-window OOS profit
     factors from the sequential WFO verdict (the edge must be broad across time,
     not concentrated in one window).

Read-only (writes nothing to gate_v2_verdicts). Run from engine/:

    .venv/Scripts/python -m backtest.singlefinder_sensitivity --symbol MGC
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from backtest.contract_specs import CONTRACT_SPECS
from backtest.sensitivity import _compute_stability, sweep_param_sensitivity
from backtest.studies import load_study
from backtest.study_wfo_runner import DATA_FILES, _backtest, _load_data, engine_root

MIN_SINGLE_TICKS_SWEEP = [1, 2, 3, 4, 5, 6]
CHAMPION = {"min_single_ticks": 2}
MODE = "fill"


def _metrics_from_result(r) -> dict:
    """BacktestResult -> the metrics dict the sensitivity core consumes."""
    if r is None or r.total_trades < 1:
        return {"pf": 0.0, "trades": 0, "sharpe": 0.0, "return": 0.0, "win_rate": 0.0}
    return {
        "pf": round(min(r.profit_factor, 999.0), 3),
        "trades": r.total_trades,
        "sharpe": round(r.sharpe_ratio, 3),
        "return": round(r.total_return_pct * 100, 2),
        "win_rate": round(r.win_rate * 100, 1),
    }


def build_run_fn(study, df, symbol: str, base_comm: float):
    """Adapter: params dict -> full-dataset backtest -> metrics dict."""

    def run_fn(params: dict) -> dict:
        try:
            r = _backtest(
                study,
                df,
                symbol,
                MODE,
                {"min_single_ticks": params["min_single_ticks"]},
                commission=base_comm,
                slippage_ticks=1.0,
            )
        except Exception as exc:  # noqa: BLE001 - defensive; a dead combo scores 0
            print(f"    [WARN] backtest {params}: {exc}")
            return {"pf": 0.0, "trades": 0, "sharpe": 0.0, "return": 0.0, "win_rate": 0.0}
        return _metrics_from_result(r)

    return run_fn


def subperiod_stability(verdict_path: Path) -> tuple[list, float, dict]:
    """Per-window OOS PF dispersion from the sequential WFO verdict."""
    j = json.loads(verdict_path.read_text())
    pf = [w["oos_pf"] for w in j.get("windows", [])]
    finite = [v for v in pf if isinstance(v, (int, float)) and v == v]
    wins = sum(1 for v in finite if v > 1.0)
    stab = _compute_stability(finite)
    return pf, stab, {"wins": wins, "n": len(pf), "p_edge": round(wins / max(1, len(pf)), 3)}


def run(symbol: str = "MGC") -> dict:
    study = load_study("singlefinder")
    df = _load_data(engine_root / "backtest" / "cache" / DATA_FILES[symbol])
    base_comm = CONTRACT_SPECS[symbol].commission
    print(f"[singlefinder-sensitivity] {symbol} {DATA_FILES[symbol]} | {len(df)} bars")

    run_fn = build_run_fn(study, df, symbol, base_comm)
    res = sweep_param_sensitivity(
        run_fn, {"min_single_ticks": MIN_SINGLE_TICKS_SWEEP}, CHAMPION, progress=True
    )

    print("\n=== PARAM SENSITIVITY (min_single_ticks, full dataset) ===")
    print(f"{'ticks':>6} {'PF':>7} {'trades':>7} {'WR%':>6} {'ret%':>8} {'vsBase':>8}")
    for pt in res["sensitivity"]["min_single_ticks"]:
        mark = "  <- champion" if pt["value"] == CHAMPION["min_single_ticks"] else ""
        print(
            f"{pt['value']:>6} {pt['pf']:>7.3f} {pt['trades']:>7} {pt['win_rate']:>6.1f} "
            f"{pt['return']:>+8.1f} {pt['pct_change_from_base']:>+7.1f}%{mark}"
        )
    print(
        f"\nPARAM stability: {res['stability_scores']['min_single_ticks']:.1f}/100  "
        f"-> sensitivity verdict: {res['verdict']}"
    )

    vp = engine_root / "data" / "gate_v2_verdicts" / f"{symbol}_singlefinder_fill_rank1.json"
    pf_series, sub_stab, info = subperiod_stability(vp)
    print("\n=== SUB-PERIOD STABILITY (7 OOS windows, sequential WFO) ===")
    print(f"per-window OOS PF: {pf_series}")
    print(
        f"p_edge: {info['wins']}/{info['n']} = {info['p_edge']}   "
        f"sub-period stability: {sub_stab:.1f}/100"
    )

    combined = (
        "CONFIRM"
        if res["verdict"] in {"ROBUST", "ACCEPTABLE"} and sub_stab >= 50 and info["p_edge"] >= 0.6
        else "KILL"
    )
    print(
        f"\n>>> Task 2 combined verdict: {combined} "
        f"(param={res['verdict']}, subperiod_stab={sub_stab:.0f}, p_edge={info['p_edge']})"
    )
    return {
        "param_sensitivity": res,
        "subperiod_pf": pf_series,
        "subperiod_stability": sub_stab,
        "subperiod_info": info,
        "combined_verdict": combined,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbol", default="MGC")
    args = ap.parse_args()
    run(args.symbol)


if __name__ == "__main__":
    main()
