"""
run_spy_supertrend_weekly_rank1 -- backtest + gate-v2 of the `supertrend_weekly_spx`
Tier-B survivor (X-bookmark edge scan 2026-07-02, @QuantifiedStrat).

Long SPY on a weekly Supertrend(ATR10, mult3) buy; flat to cash on sell. Long-only.
Per-week in-market PnL fed through the repo's real gate-v2 battery. Draft/research;
does NOT authorize paper routing. Run: python backtest/run_spy_supertrend_weekly_rank1.py
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
from generate_supertrend_signals import generate_supertrend_signals  # noqa: E402
from research_verdict import write_research_verdict  # noqa: E402

_DEFAULT_DATA = r"C:/Users/mattm/ThinkorSwim/jarvis-trader/engine/backtest/cache/SPY_1993-01-29_2026-06-24_1d.csv"
_CAPITAL = 10_000.0
# ATR period {7,10,14} x multiplier {2,2.5,3,3.5} = 12 combos considered -> DSR deflation.
_N_GRID_TRIALS = 12


def _metrics(ret: pd.Series, ppy: float) -> dict:
    eq = (1 + ret.fillna(0)).cumprod()
    yrs = len(ret) / ppy
    cagr = eq.iloc[-1] ** (1 / yrs) - 1 if yrs > 0 and eq.iloc[-1] > 0 else float("nan")
    mu, sd = ret.mean(), ret.std()
    sharpe = (mu / sd) * np.sqrt(ppy) if sd and sd > 0 else float("nan")
    dd = (eq / eq.cummax() - 1).min()
    return {"cagr": round(float(cagr), 4), "sharpe_ann": round(float(sharpe), 3),
            "max_dd": round(float(dd), 4), "final_mult": round(float(eq.iloc[-1]), 2)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=_DEFAULT_DATA)
    ap.add_argument("--out", default=os.path.join(_ENGINE, "data", "research_reports", "SPY_supertrendweekly_rank1.json"))
    args = ap.parse_args()

    daily = pd.read_csv(args.data, parse_dates=["timestamp"]).set_index("timestamp").sort_index()
    weekly = daily.resample("W-FRI").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()

    sig = generate_supertrend_signals(weekly, atr_period=10, multiplier=3.0)
    pos = sig["position"].shift(1).fillna(0.0)
    wret = weekly["close"].pct_change()
    strat_ret = (pos * wret).dropna()

    bh = _metrics(wret.dropna(), 52.0)
    strat = _metrics(strat_ret, 52.0)

    in_mkt = strat_ret[pos.reindex(strat_ret.index).fillna(0) > 0]
    pnls = (_CAPITAL * in_mkt).tolist()
    n_flips = int((sig["entry_signal"] == "ENTRY_NOW").sum())
    pct_in_market = round(float((pos > 0).mean()), 3)

    report = vs.validate(pnls, n_grid_trials=_N_GRID_TRIALS, initial_capital=_CAPITAL)
    verdict = vs._evaluate_gate_v2(report)

    out = {
        "strategy": "supertrend_weekly_spx", "symbol": "SPY", "rank": 1,
        "source": "x-bookmark edge scan 2026-07-02 (@QuantifiedStrat)",
        "period": [str(weekly.index[0].date()), str(weekly.index[-1].date())],
        "n_weeks": int(len(strat_ret)), "n_in_market_trades": len(pnls),
        "n_buy_signals": n_flips, "pct_time_in_market": pct_in_market, "n_grid_trials": _N_GRID_TRIALS,
        "strategy_metrics": strat, "buy_hold_metrics": bh,
        "gate_v2": {"verdict": verdict.get("verdict"), "passed_via": verdict.get("passed_via"),
                     "core_verdict": verdict.get("core_verdict"), "alt_verdict": verdict.get("alt_verdict"),
                     "reasons": verdict.get("reasons")},
        "note": "Weekly long-only vol-trailing trend filter. Validated on weekly in-market PnL. "
                "Draft/research only -- does NOT authorize paper routing.",
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
    rv_path = write_research_verdict(
        strategy="supertrend_weekly_spx", symbol="SPY", family="research_equity_trend", rank=2,
        report=report, verdict=verdict, strategy_class="equity_swing",
        provenance={"source_bookmark_url": "https://x.com/QuantifiedStrat/status/2071956929237123252",
                    "author": "@QuantifiedStrat", "scan_date": "2026-07-02"},
        class_note=("3/4 CORE (DSR 0.9998); fails only mc_95th_dd vs the 6% intraday-futures ceiling. "
                    "Raises Sharpe over buy&hold (0.735 vs 0.685) and halves drawdown (-27% vs -55%)."),
    )

    print(json.dumps({k: out[k] for k in ("strategy", "period", "n_in_market_trades", "pct_time_in_market",
                                          "strategy_metrics", "buy_hold_metrics", "gate_v2")}, indent=2))
    print("written:", args.out)
    print("research verdict:", rv_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
