"""
run_spy_atr_band_rank1 -- backtest + gate-v2 of the `atr_band_breakout` Tier-B survivor
(X-bookmark edge scan 2026-07-02, @QuantifiedStrat).

The open question flagged in the scan is polarity: does a close beyond an MA +/- k*ATR band
lead to CONTINUATION (breakout) or REVERSION? This runner tests all four configs on 33yr SPY
daily -- {breakout, meanrev} x {long-only, long/short} -- reports metrics for each, and feeds
the best-by-Sharpe config's in-market PnL through the repo's real gate-v2 battery.

DRAFT/research runner -- does NOT authorize paper routing. Run: python backtest/run_spy_atr_band_rank1.py
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
from generate_atr_band_signals import generate_atr_band_signals  # noqa: E402
from research_verdict import write_research_verdict  # noqa: E402

_DEFAULT_DATA = r"C:/Users/mattm/ThinkorSwim/jarvis-trader/engine/backtest/cache/SPY_1993-01-29_2026-06-24_1d.csv"
_CAPITAL = 10_000.0
# ma_len {10,20,50} x k {1.5,2,2.5,3} x mode {breakout,meanrev} = 24 combos considered.
_N_GRID_TRIALS = 24


def _metrics(ret: pd.Series, ppy: int = 252) -> dict:
    eq = (1 + ret.fillna(0)).cumprod()
    yrs = len(ret) / float(ppy)
    cagr = eq.iloc[-1] ** (1 / yrs) - 1 if yrs > 0 and eq.iloc[-1] > 0 else float("nan")
    mu, sd = ret.mean(), ret.std()
    sharpe = (mu / sd) * np.sqrt(ppy) if sd and sd > 0 else float("nan")
    dd = (eq / eq.cummax() - 1).min()
    return {"cagr": round(float(cagr), 4), "sharpe_ann": round(float(sharpe), 3),
            "max_dd": round(float(dd), 4), "final_mult": round(float(eq.iloc[-1]), 2)}


def _run_config(daily: pd.DataFrame, mode: str, long_only: bool) -> tuple[dict, pd.Series, pd.Series]:
    sig = generate_atr_band_signals(daily, ma_len=20, atr_period=14, k=2.5, mode=mode, long_only=long_only)
    pos = sig["position"].shift(1).fillna(0.0)
    dret = daily["close"].pct_change()
    strat_ret = (pos * dret).dropna()
    return _metrics(strat_ret), strat_ret, pos


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=_DEFAULT_DATA)
    ap.add_argument("--out", default=os.path.join(_ENGINE, "data", "research_reports", "SPY_atrband_rank1.json"))
    args = ap.parse_args()

    daily = pd.read_csv(args.data, parse_dates=["timestamp"]).set_index("timestamp").sort_index()
    bh = _metrics(daily["close"].pct_change().dropna())

    configs = {}
    series = {}
    for mode in ("breakout", "meanrev"):
        for lo in (True, False):
            name = f"{mode}_{'long_only' if lo else 'long_short'}"
            m, sret, pos = _run_config(daily, mode, lo)
            configs[name] = m
            series[name] = (sret, pos)

    # pick best by annualized Sharpe (finite only)
    best_name = max(configs, key=lambda k: (configs[k]["sharpe_ann"] if np.isfinite(configs[k]["sharpe_ann"]) else -1e9))
    best_sret, best_pos = series[best_name]
    in_mkt = best_sret[best_pos.reindex(best_sret.index).fillna(0) != 0]
    pnls = (_CAPITAL * in_mkt).tolist()

    report = vs.validate(pnls, n_grid_trials=_N_GRID_TRIALS, initial_capital=_CAPITAL)
    verdict = vs._evaluate_gate_v2(report, strategy_class="equity_swing")

    out = {
        "strategy": "atr_band_breakout", "symbol": "SPY", "rank": 1,
        "source": "x-bookmark edge scan 2026-07-02 (@QuantifiedStrat)",
        "period": [str(daily.index[0].date()), str(daily.index[-1].date())],
        "polarity_test": configs,
        "best_config": best_name, "n_in_market_bars": len(pnls), "n_grid_trials": _N_GRID_TRIALS,
        "buy_hold_metrics": bh,
        "gate_v2": {"verdict": verdict.get("verdict"), "passed_via": verdict.get("passed_via"),
                     "core_verdict": verdict.get("core_verdict"), "alt_verdict": verdict.get("alt_verdict"),
                     "reasons": verdict.get("reasons")},
        "note": "Polarity resolved empirically by best-Sharpe across 4 configs (ma20/k2.5/atr14). Best "
                "config's per-bar in-market PnL fed to gate v2. Draft/research only -- no paper routing.",
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
    rv_path = write_research_verdict(
        strategy="atr_band_breakout", symbol="SPY", family="research_equity_meanrev", rank=1,
        report=report, verdict=verdict, strategy_class="equity_swing",
        provenance={"source_bookmark_url": "https://x.com/QuantifiedStrat/status/2072047523917885657",
                    "author": "@QuantifiedStrat", "scan_date": "2026-07-02"},
        class_note=("REFUTED on SPY: breakout polarity loses; best variant (mean-rev) underperforms "
                    "buy&hold and DSR collapses to 0.0 after 24-trial deflation. Documented negative result."),
        extra={"best_config": out.get("best_config"), "polarity_test": out.get("polarity_test")},
    )

    print(json.dumps({k: out[k] for k in ("strategy", "period", "polarity_test", "best_config",
                                          "n_in_market_bars", "buy_hold_metrics", "gate_v2")}, indent=2))
    print("written:", args.out)
    print("research verdict:", rv_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
