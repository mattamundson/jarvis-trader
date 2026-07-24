"""
MES pure-STC profitability search (2026-04-20).

Bypasses the composite layer (which hardcodes stop/target ATR multiples)
and optimizes the pure STC signal pipeline via _compute_signals + Backtester.
This is the same path the existing BayesianOptimizer hits, but with a wider
random search and an explicit PF primary objective (not sharpe*PF).

Run from engine/:
    .venv/Scripts/python -m scripts.mes_stc_search
"""

from __future__ import annotations

import json
import logging
import os
import random
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

_HERE = Path(__file__).resolve().parent
_ENGINE = _HERE.parent
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

from backtest.backtester import Backtester  # noqa: E402
from backtest.contract_specs import CONTRACT_SPECS  # noqa: E402
from backtest.data_loader import BacktestDataLoader  # noqa: E402
from backtest.optimizer import _compute_signals  # noqa: E402

SYMBOL = "MES"
INTERVAL = "1h"
START = "2024-06-01"
END = "2026-03-27"
CAPITAL = 10_000.0
RISK = 0.01
# Canonical rate from contract_specs.py (single source of truth) -- was
# hardcoded to 2.50, which is not any registered MES/MGC/MCL commission.
COMMISSION_PER_CONTRACT = CONTRACT_SPECS["MES"].commission

# Wider search: also varies stop/target which composite ignored
SPACE = {
    "stc_os": [10, 15, 20, 25, 30],
    "stc_ob": [70, 75, 80, 83, 88, 92, 95],
    "stop_mult": [0.3, 0.5, 0.7, 1.0, 1.5, 2.0],
    "target_mult": [0.8, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0],
    "regime": [True, False],
}


def _run_one(df_base, multiplier, params):
    try:
        df_sig = _compute_signals(
            df_base.copy(),
            stc_oversold=params["stc_os"],
            stc_overbought=params["stc_ob"],
            atr_stop_mult=params["stop_mult"],
            atr_target_mult=params["target_mult"],
            regime_filter=params["regime"],
        )
    except Exception as exc:
        return None, f"signal_error: {exc}"

    try:
        bt = Backtester(
            initial_capital=CAPITAL,
            risk_per_trade=RISK,
            max_daily_loss=0.02,
            max_drawdown=0.05,
            commission_per_contract=COMMISSION_PER_CONTRACT,
            slippage_ticks=1,
        )
        result = bt.run(df_sig, SYMBOL, multiplier)
    except Exception as exc:
        return None, f"backtest_error: {exc}"
    return result, None


def main():
    t0 = time.time()
    loader = BacktestDataLoader()
    df_base = loader.load(SYMBOL, START, END, INTERVAL)
    if df_base is None or df_base.empty:
        print("[ERROR] No data loaded")
        return 1
    multiplier = loader.get_multiplier(SYMBOL)
    print(f"Loaded {len(df_base)} bars for {SYMBOL} {INTERVAL} {START}→{END}")

    n_samples = int(os.environ.get("N", "50"))
    print(f"Random search (pure STC): {n_samples} samples")

    rng = random.Random(7)

    def sample():
        return {k: rng.choice(v) for k, v in SPACE.items()}

    # Anchors: current MES defaults + a few broader tests
    anchors = [
        {"stc_os": 15, "stc_ob": 83, "stop_mult": 0.9, "target_mult": 1.5, "regime": True},  # MES default
        {"stc_os": 19, "stc_ob": 88, "stop_mult": 0.5, "target_mult": 1.0, "regime": True},  # grid default
        {"stc_os": 23, "stc_ob": 83, "stop_mult": 0.5, "target_mult": 1.0, "regime": True},  # MCL best
        {"stc_os": 15, "stc_ob": 92, "stop_mult": 0.7, "target_mult": 1.0, "regime": True},  # MNQ best
        # Wide stop / wide target (let winners run)
        {"stc_os": 20, "stc_ob": 80, "stop_mult": 2.0, "target_mult": 4.0, "regime": True},
        # Tight stop / tight target
        {"stc_os": 15, "stc_ob": 85, "stop_mult": 0.3, "target_mult": 0.8, "regime": True},
    ]

    samples = anchors + [sample() for _ in range(max(0, n_samples - len(anchors)))]

    results = []
    for i, params in enumerate(samples, 1):
        r, err = _run_one(df_base, multiplier, params)
        if r is None:
            print(f"[{i:3d}/{len(samples)}] ERR params={params}  err={err}")
            continue
        pf = r.profit_factor if r.profit_factor != float("inf") else 999.0
        wr = r.win_rate
        nt = r.total_trades
        ret = r.total_return_pct
        results.append({
            "params": params,
            "pf": round(pf, 3),
            "wr": round(wr, 2),
            "trades": nt,
            "ret": round(ret, 2),
            "sharpe": round(r.sharpe_ratio, 3),
        })
        flag = ""
        if pf >= 2.0 and nt >= 50:
            flag = "  <- WINNER PF>=2.0"
        elif pf >= 1.5 and nt >= 100:
            flag = "  <- backup PF>=1.5"
        elif pf >= 1.2 and nt >= 50:
            flag = "  <- marginal PF>=1.2"
        print(
            f"[{i:3d}/{len(samples)}] "
            f"os={params['stc_os']:2d} ob={params['stc_ob']:2d} "
            f"sl={params['stop_mult']:.1f} tp={params['target_mult']:.1f} "
            f"reg={int(params['regime'])}  "
            f"PF={pf:6.2f}  WR={wr:5.1f}%  n={nt:4d}  ret={ret:+.1f}%{flag}"
        )

    results.sort(key=lambda x: (x["pf"], x["trades"]), reverse=True)

    out_path = Path(__file__).parent / "mes_stc_search_results.json"
    with open(out_path, "w") as f:
        json.dump({
            "symbol": SYMBOL,
            "interval": INTERVAL,
            "start": START,
            "end": END,
            "strategy": "pure_stc",
            "n_samples": len(samples),
            "elapsed_sec": round(time.time() - t0, 1),
            "results": results,
        }, f, indent=2)

    print(f"\nSaved {len(results)} results to {out_path}")
    print("\nTOP 10 by PF:")
    print(f"{'rank':>4} {'PF':>7} {'WR%':>6} {'trades':>6} {'ret%':>7} {'sharpe':>7}  params")
    for i, r in enumerate(results[:10], 1):
        p = r["params"]
        print(
            f"{i:>4} {r['pf']:>7.2f} {r['wr']:>6.1f} {r['trades']:>6d} {r['ret']:>+7.1f} {r['sharpe']:>7.2f}  "
            f"os={p['stc_os']} ob={p['stc_ob']} sl={p['stop_mult']} tp={p['target_mult']} reg={int(p['regime'])}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
