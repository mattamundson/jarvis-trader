"""
run_spy_sma12_rank1 -- backtest + gate-v2 validation of the `sma12_monthly_momentum`
Tier-A survivor from the 2026-07-02 X-bookmark edge scan.

Long SPY while monthly close > 12-month SMA; flat to cash below. Monthly rebalance.
Feeds the per-month in-market PnL series through the repo's real gate-v2 battery
(validate_strategy.validate + _evaluate_gate_v2) -- the same acceptance logic used
for the intraday strategies, but on monthly observations.

This is a DRAFT/research runner: it validates the economic edge, it does NOT authorize
paper routing. Run:
    python backtest/run_spy_sma12_rank1.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ENGINE, "scripts"))
sys.path.insert(0, _HERE)

import validate_strategy as vs  # noqa: E402
from generate_sma12_momentum_signals import generate_sma12_momentum_signals  # noqa: E402
from research_verdict import write_research_verdict  # noqa: E402

# SPY daily lives in the main checkout's (gitignored) cache; absolute default.
_DEFAULT_DATA = r"C:/Users/mattm/ThinkorSwim/jarvis-trader/engine/backtest/cache/SPY_1993-01-29_2026-06-24_1d.csv"
_CAPITAL = 10_000.0
# Documented parameterization surface for honest DSR deflation:
# sma_len in {6,9,10,12,15,18} x {SMA,EMA} filter = 12 combinations considered.
_N_GRID_TRIALS = 12


def _metrics(monthly_strat_ret: pd.Series) -> dict:
    eq = (1 + monthly_strat_ret.fillna(0)).cumprod()
    yrs = len(monthly_strat_ret) / 12.0
    cagr = eq.iloc[-1] ** (1 / yrs) - 1 if yrs > 0 and eq.iloc[-1] > 0 else float("nan")
    mu, sd = monthly_strat_ret.mean(), monthly_strat_ret.std()
    sharpe = (mu / sd) * np.sqrt(12) if sd and sd > 0 else float("nan")
    dd = (eq / eq.cummax() - 1).min()
    return {"cagr": round(float(cagr), 4), "sharpe_ann": round(float(sharpe), 3),
            "max_dd": round(float(dd), 4), "final_mult": round(float(eq.iloc[-1]), 2)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=_DEFAULT_DATA)
    ap.add_argument("--out", default=os.path.join(_ENGINE, "data", "research_reports", "SPY_sma12momentum_rank1.json"))
    args = ap.parse_args()

    daily = pd.read_csv(args.data, parse_dates=["timestamp"]).set_index("timestamp").sort_index()
    monthly = daily.resample("ME").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()

    sig = generate_sma12_momentum_signals(monthly, sma_len=12)
    pos = sig["position"].shift(1).fillna(0.0)          # hold next month on this month's signal (no look-ahead)
    mret = monthly["close"].pct_change()
    strat_ret = (pos * mret).dropna()

    # buy & hold benchmark
    bh = _metrics(mret.dropna())
    strat = _metrics(strat_ret)

    # gate-v2 trade list: dollar PnL of each IN-MARKET month (flat months are non-trades)
    in_mkt = strat_ret[pos.reindex(strat_ret.index).fillna(0) > 0]
    pnls = (_CAPITAL * in_mkt).tolist()
    n_flips = int(((pos.diff().abs() > 0)).sum())

    report = vs.validate(pnls, n_grid_trials=_N_GRID_TRIALS, initial_capital=_CAPITAL)
    verdict = vs._evaluate_gate_v2(report)

    out = {
        "strategy": "sma12_monthly_momentum", "symbol": "SPY", "rank": 1,
        "source": "x-bookmark edge scan 2026-07-02 (@QuantifiedStrat)",
        "period": [str(monthly.index[0].date()), str(monthly.index[-1].date())],
        "n_months": int(len(strat_ret)), "n_in_market_trades": len(pnls), "n_regime_flips": n_flips,
        "n_grid_trials": _N_GRID_TRIALS,
        "strategy_metrics": strat, "buy_hold_metrics": bh,
        "gate_v2": {"verdict": verdict.get("verdict"), "passed_via": verdict.get("passed_via"),
                     "core_verdict": verdict.get("core_verdict"), "alt_verdict": verdict.get("alt_verdict"),
                     "reasons": verdict.get("reasons")},
        "report_keys": sorted(report.keys()),
        "note": "Monthly regime filter (not intraday). Validated on monthly in-market PnL. "
                "Draft/research only -- does NOT authorize paper routing.",
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)

    rv_path = write_research_verdict(
        strategy="sma12_monthly_momentum", symbol="SPY", family="research_equity_trend", rank=1,
        report=report, verdict=verdict, strategy_class="equity_swing",
        provenance={"source_bookmark_url": "https://x.com/QuantifiedStrat/status/2072002224553603121",
                    "author": "@QuantifiedStrat", "scan_date": "2026-07-02"},
        class_note=("3/4 CORE (PF-CI, p_edge, DSR pass); fails only mc_95th_dd vs the 6% "
                    "intraday-futures ceiling. Halves buy&hold drawdown (-16.6% vs -50.8%)."),
    )

    print(json.dumps({k: out[k] for k in ("strategy", "period", "n_in_market_trades", "n_regime_flips",
                                          "strategy_metrics", "buy_hold_metrics", "gate_v2")}, indent=2))
    print("written:", args.out)
    print("research verdict:", rv_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
