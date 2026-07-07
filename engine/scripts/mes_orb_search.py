"""
MES ORB profitability grid — throwaway scratch script (2026-04-20).

Goal: find an ORB configuration with PF >= 1.5 on cached MES 1h data
over the 2024-06-01 → 2026-03-27 window. Fallback path if composite
search yields no winner.

Strategy: exhaustive grid over the three ORB dimensions exposed by
generate_orb_signals / run_orb_backtest:
  - volume_filter   [True, False]
  - regime_filter   [True, False]
  - min_or_range_pct [0.0004, 0.0008, 0.0012, 0.0020, 0.0030]

20 combos total. In-process. Uses the same cached OHLC loader as
mes_search.py.

Run from engine/:
    .venv/Scripts/python -m scripts.mes_orb_search
"""

from __future__ import annotations

import json
import logging
import sys
import time
from itertools import product
from pathlib import Path

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
for name in ("orb_signals", "orb_backtester"):
    logging.getLogger(name).setLevel(logging.WARNING)

_HERE = Path(__file__).resolve().parent
_ENGINE = _HERE.parent
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

from backtest.data_loader import BacktestDataLoader  # noqa: E402
from backtest.orb_backtester import run_orb_backtest  # noqa: E402

SYMBOL = "MES"
INTERVAL = "1h"
START = "2024-06-01"
END = "2026-03-27"

GRID = {
    "volume_filter": [True, False],
    "regime_filter": [True, False],
    "min_or_range_pct": [0.0004, 0.0008, 0.0012, 0.0020, 0.0030],
}


def _run_one(df_base, params):
    try:
        result = run_orb_backtest(
            df_base.copy(),
            symbol=SYMBOL,
            contracts=1,
            volume_filter=params["volume_filter"],
            regime_filter=params["regime_filter"],
            min_or_range_pct=params["min_or_range_pct"],
        )
    except Exception as exc:
        return None, f"error: {exc}"
    return result, None


def main():
    t0 = time.time()
    loader = BacktestDataLoader()
    df_base = loader.load(SYMBOL, START, END, INTERVAL)
    if df_base is None or df_base.empty:
        print("[ERROR] No data loaded", flush=True)
        return 1
    print(f"Loaded {len(df_base)} bars for {SYMBOL} {INTERVAL} {START}->{END}", flush=True)

    combos = [
        dict(zip(GRID.keys(), vals, strict=False)) for vals in product(*GRID.values())
    ]
    print(f"ORB grid: {len(combos)} combos", flush=True)

    results = []
    for i, params in enumerate(combos, 1):
        r, err = _run_one(df_base, params)
        if r is None:
            print(f"[{i:2d}/{len(combos)}] ERR params={params}  err={err}", flush=True)
            continue
        s = r.summary()
        pf = s["profit_factor"] if s["profit_factor"] != float("inf") else 999.0
        wr = s["win_rate"] * 100.0
        nt = s["total_trades"]
        pnl = s["net_pnl"]
        flag = ""
        if pf >= 2.0 and nt >= 50:
            flag = "  <- WINNER PF>=2.0"
        elif pf >= 1.5 and nt >= 100:
            flag = "  <- backup PF>=1.5"
        results.append({
            "params": params,
            "pf": round(pf, 3),
            "wr": round(wr, 2),
            "trades": nt,
            "net_pnl": round(pnl, 2),
            "sharpe": s.get("sharpe", 0.0),
            "max_dd": s.get("max_drawdown", 0.0),
        })
        print(
            f"[{i:2d}/{len(combos)}] "
            f"vol={int(params['volume_filter'])} reg={int(params['regime_filter'])} "
            f"minrng={params['min_or_range_pct']:.4f}  "
            f"PF={pf:6.2f}  WR={wr:5.1f}%  n={nt:4d}  "
            f"pnl=${pnl:+.0f}{flag}",
            flush=True,
        )

    results.sort(key=lambda x: (x["pf"], x["trades"]), reverse=True)

    out_path = Path(__file__).parent / "mes_orb_search_results.json"
    with open(out_path, "w") as f:
        json.dump({
            "symbol": SYMBOL,
            "interval": INTERVAL,
            "start": START,
            "end": END,
            "n_combos": len(combos),
            "elapsed_sec": round(time.time() - t0, 1),
            "results": results,
        }, f, indent=2)

    print(f"\nSaved {len(results)} results to {out_path}", flush=True)
    print("\nTOP 10 by PF:", flush=True)
    print(f"{'rank':>4} {'PF':>7} {'WR%':>6} {'trades':>6} {'pnl$':>8}  params", flush=True)
    for i, r in enumerate(results[:10], 1):
        p = r["params"]
        print(
            f"{i:>4} {r['pf']:>7.2f} {r['wr']:>6.1f} {r['trades']:>6d} {r['net_pnl']:>+8.0f}  "
            f"vol={int(p['volume_filter'])} reg={int(p['regime_filter'])} "
            f"minrng={p['min_or_range_pct']:.4f}",
            flush=True,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
