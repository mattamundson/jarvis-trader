"""
run_spy_overnight_rank1 -- backtest + gate-v2 validation of the `spy_overnight_hold`
Tier-A survivor from the 2026-07-02 X-bookmark edge scan.

Buy market-on-close, sell market-on-open next session; flat intraday. Captures the
close-to-open drift / overnight risk premium. Feeds the per-night PnL series through
the repo's real gate-v2 battery.

DRAFT/research runner -- validates the edge, does NOT authorize paper routing. Run:
    python backtest/run_spy_overnight_rank1.py
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
from generate_overnight_hold_signals import generate_overnight_hold_signals  # noqa: E402
from research_verdict import write_research_verdict  # noqa: E402

_DEFAULT_DATA = r"C:/Users/mattm/ThinkorSwim/jarvis-trader/engine/backtest/cache/SPY_1993-01-29_2026-06-24_1d.csv"
_CAPITAL = 10_000.0
# Base overnight hold is parameter-free; the only optional knob is skip_after_up_days
# in {0,2,3}. 3 variants considered -> honest DSR deflation.
_N_GRID_TRIALS = 3


def _metrics(daily_ret: pd.Series, ppy: int = 252) -> dict:
    eq = (1 + daily_ret.fillna(0)).cumprod()
    yrs = len(daily_ret) / float(ppy)
    cagr = eq.iloc[-1] ** (1 / yrs) - 1 if yrs > 0 and eq.iloc[-1] > 0 else float("nan")
    mu, sd = daily_ret.mean(), daily_ret.std()
    sharpe = (mu / sd) * np.sqrt(ppy) if sd and sd > 0 else float("nan")
    dd = (eq / eq.cummax() - 1).min()
    return {"cagr": round(float(cagr), 4), "sharpe_ann": round(float(sharpe), 3),
            "max_dd": round(float(dd), 4), "final_mult": round(float(eq.iloc[-1]), 2)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=_DEFAULT_DATA)
    ap.add_argument("--out", default=os.path.join(_ENGINE, "data", "research_reports", "SPY_overnighthold_rank1.json"))
    args = ap.parse_args()

    daily = pd.read_csv(args.data, parse_dates=["timestamp"]).set_index("timestamp").sort_index()
    sig = generate_overnight_hold_signals(daily, skip_after_up_days=0)

    overnight = sig["overnight_ret"]
    strat_ret = (sig["position"] * overnight).dropna()

    # benchmarks: overnight-only vs full close-to-close buy&hold vs intraday-only
    c2c = daily["close"].pct_change().dropna()
    intraday = (daily["close"] / daily["open"] - 1).dropna()

    strat = _metrics(strat_ret)
    bh = _metrics(c2c)
    intr = _metrics(intraday)

    pnls = (_CAPITAL * strat_ret[sig["position"].reindex(strat_ret.index).fillna(0) > 0]).tolist()

    report = vs.validate(pnls, n_grid_trials=_N_GRID_TRIALS, initial_capital=_CAPITAL)
    verdict = vs._evaluate_gate_v2(report)

    out = {
        "strategy": "spy_overnight_hold", "symbol": "SPY", "rank": 1,
        "source": "x-bookmark edge scan 2026-07-02 (@QuantifiedStrat)",
        "period": [str(daily.index[0].date()), str(daily.index[-1].date())],
        "n_nights": len(pnls), "n_grid_trials": _N_GRID_TRIALS,
        "strategy_metrics": strat, "buy_hold_c2c_metrics": bh, "intraday_only_metrics": intr,
        "gate_v2": {"verdict": verdict.get("verdict"), "passed_via": verdict.get("passed_via"),
                     "core_verdict": verdict.get("core_verdict"), "alt_verdict": verdict.get("alt_verdict"),
                     "reasons": verdict.get("reasons")},
        "note": "Per-night PnL, gross of commission/slippage (a real overnight implementation pays the "
                "close/open spread + financing -- gate reasons reflect gross). Draft/research only; does "
                "NOT authorize paper routing. The overnight-vs-intraday split is the headline evidence.",
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)

    rv_path = write_research_verdict(
        strategy="spy_overnight_hold", symbol="SPY", family="research_equity_overnight", rank=1,
        report=report, verdict=verdict, strategy_class="equity_overnight",
        provenance={"source_bookmark_url": "https://x.com/QuantifiedStrat/status/2070190285746036963",
                    "author": "@QuantifiedStrat", "scan_date": "2026-07-02"},
        class_note=("3/4 CORE; DD-only fail. Overnight-only captures ~all of SPY's 33yr return; "
                    "intraday-only = 0.7% CAGR. PnL is GROSS of close/open spread + financing."),
    )

    print(json.dumps({k: out[k] for k in ("strategy", "period", "n_nights", "strategy_metrics",
                                          "buy_hold_c2c_metrics", "intraday_only_metrics", "gate_v2")}, indent=2))
    print("written:", args.out)
    print("research verdict:", rv_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
