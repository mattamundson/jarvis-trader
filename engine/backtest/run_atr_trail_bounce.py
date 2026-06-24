"""ATR Trailing-Stop Bounce — local backtest + MCPT runner.

Tests Matt's /ES hypothesis (2026-06-24): the dotted ATR trailing-stop line
(TOS ``ATRTrailingStop modified, 5, 3.5, long, WILDERS``) is dynamic S/R and
price bounces off it. Signal: backtest/atr_trail_bounce_signals.py.

RUN THIS LOCALLY (data + venv live on Matt's machine; the web container has no
bars). From engine/:

    .venv/Scripts/python -m backtest.run_atr_trail_bounce --symbol MES --timeframe 1h
    .venv/Scripts/python -m backtest.run_atr_trail_bounce --symbol MES --timeframe 5m \
        --data-file backtest/cache/MES_..._5m.csv

What it does:
  1. Loads OHLC for the symbol/timeframe.
  2. Grid-searches the LOCKED param spec on in-sample data (profit factor).
  3. Runs the existing event-driven Backtester for the headline metrics.
  4. Runs bar-permutation MCPT (analytics.permutation_test.validate_strategy)
     to separate real edge from data-mining luck — the whole point, since a
     single visual "bounce" is exactly what survives in random data.

LOCKED SPEC (do not re-tune after seeing the p-value — see ml-pitfalls-defense.md):
    factor       in {3.0, 3.5, 4.0}
    hold_bars    in {0, 1, 2}
    touch_tol_atr in {0.0, 0.10}
    atr_period   = 5   (fixed — the TOS study value)
A REJECT verdict means discard the hypothesis, not tweak-and-rerun.
"""

from __future__ import annotations

import argparse
import sys
from itertools import product
from pathlib import Path

import pandas as pd

ENGINE_ROOT = Path(__file__).resolve().parent.parent
if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))

from backtest.atr_trail_bounce_signals import generate_atr_trail_bounce_signals  # noqa: E402
from backtest.backtester import Backtester  # noqa: E402

# ── Locked spec ────────────────────────────────────────────────────────────
ATR_PERIOD = 5
FACTOR_GRID = [3.0, 3.5, 4.0]
HOLD_BARS_GRID = [0, 1, 2]
TOUCH_TOL_GRID = [0.0, 0.10]
PARAM_GRID = list(product(FACTOR_GRID, HOLD_BARS_GRID, TOUCH_TOL_GRID))

# ── Instrument economics (mirror run_mes_trend_rank8.py) ─────────────────────
MULTIPLIERS = {"MES": 5.0, "ES": 50.0, "MNQ": 2.0, "MCL": 100.0, "MGC": 10.0}
CAPITAL = 50_000.0
COMMISSION = 0.62  # $/contract round-trip, IB micro futures
SLIPPAGE_TICKS = 1.0
MIN_TRADES = 20  # below this a PF is not trustworthy


def _load(symbol: str, timeframe: str, data_file: str | None) -> pd.DataFrame:
    if data_file:
        path = Path(data_file)
    else:
        cache = ENGINE_ROOT / "backtest" / "cache"
        matches = sorted(cache.glob(f"{symbol}_*_{timeframe}.csv"))
        if not matches:
            raise SystemExit(
                f"No cache file matching {symbol}_*_{timeframe}.csv in {cache}. "
                f"Pass --data-file explicitly."
            )
        path = matches[-1]
    print(f"[ATR-BOUNCE] loading {path.name}")
    df = pd.read_csv(path)
    df.columns = [c.lower() for c in df.columns]
    required = {"open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise SystemExit(f"Missing columns in {path.name}: {missing}")
    return df


def _backtest(df: pd.DataFrame, symbol: str, factor: float, hold_bars: int, tol: float):
    sig = generate_atr_trail_bounce_signals(
        df, atr_period=ATR_PERIOD, factor=factor, hold_bars=hold_bars, touch_tol_atr=tol
    )
    bt = Backtester(
        initial_capital=CAPITAL,
        risk_per_trade=0.01,
        max_daily_loss=0.02,
        max_drawdown=0.05,
        commission_per_contract=COMMISSION,
        slippage_ticks=SLIPPAGE_TICKS,
    )
    return bt.run(sig, symbol=symbol, multiplier=MULTIPLIERS.get(symbol, 1.0))


def _make_optimize_fn(symbol: str):
    """optimize_fn(df) -> (best_params, best_profit_factor) over the LOCKED grid."""

    def optimize_fn(df: pd.DataFrame):
        best_pf, best_params = -1.0, None
        for factor, hold_bars, tol in PARAM_GRID:
            try:
                res = _backtest(df, symbol, factor, hold_bars, tol)
            except Exception:
                continue
            if res.total_trades < MIN_TRADES:
                continue
            if res.profit_factor > best_pf:
                best_pf = res.profit_factor
                best_params = {"factor": factor, "hold_bars": hold_bars, "touch_tol_atr": tol}
        return best_params, (best_pf if best_pf > 0 else 0.0)

    return optimize_fn


def _make_walkforward_fn(symbol: str):
    """walkforward_fn(df, train_window) -> OOS profit factor via rolling re-opt."""
    optimize_fn = _make_optimize_fn(symbol)

    def walkforward_fn(df: pd.DataFrame, train_window: int) -> float:
        if len(df) <= train_window + MIN_TRADES:
            return 0.0
        params, _ = optimize_fn(df.iloc[:train_window])
        if not params:
            return 0.0
        oos = df.iloc[train_window:].reset_index(drop=True)
        try:
            res = _backtest(oos, symbol, params["factor"], params["hold_bars"], params["touch_tol_atr"])
        except Exception:
            return 0.0
        return res.profit_factor if res.total_trades >= MIN_TRADES else 0.0

    return walkforward_fn


def main() -> None:
    ap = argparse.ArgumentParser(description="ATR trail-bounce backtest + MCPT")
    ap.add_argument("--symbol", default="MES")
    ap.add_argument("--timeframe", default="1h")
    ap.add_argument("--data-file", default=None)
    ap.add_argument("--train-window", type=int, default=2000, help="bars for MCPT in-sample")
    ap.add_argument("--insample-perms", type=int, default=200)
    ap.add_argument("--walkforward-perms", type=int, default=200)
    ap.add_argument("--skip-mcpt", action="store_true")
    args = ap.parse_args()

    df = _load(args.symbol, args.timeframe, args.data_file)
    optimize_fn = _make_optimize_fn(args.symbol)

    print(f"\n[ATR-BOUNCE] grid-searching {len(PARAM_GRID)} param sets on {len(df)} bars ...")
    best_params, best_pf = optimize_fn(df)
    if not best_params:
        raise SystemExit(f"No param set produced >= {MIN_TRADES} trades. Bounce too rare here.")

    res = _backtest(df, args.symbol, best_params["factor"], best_params["hold_bars"],
                    best_params["touch_tol_atr"])
    print("\n=== HEADLINE (full-sample, best in-sample params) ===")
    print(f"  params        : {best_params}")
    print(f"  trades        : {res.total_trades}")
    print(f"  profit factor : {res.profit_factor:.3f}")
    print(f"  win rate      : {getattr(res, 'win_rate', float('nan')):.1%}")
    print(f"  sharpe        : {getattr(res, 'sharpe_ratio', float('nan')):.2f}")
    print(f"  max drawdown  : {getattr(res, 'max_drawdown_pct', float('nan')):.2%}")
    print("  NOTE: full-sample PF is optimistic — the MCPT verdict below is what matters.")

    if args.skip_mcpt:
        return

    print("\n[ATR-BOUNCE] running bar-permutation MCPT (this is the honest test) ...")
    from analytics.permutation_test import validate_strategy

    verdict = validate_strategy(
        df,
        optimize_fn,
        _make_walkforward_fn(args.symbol),
        train_window=args.train_window,
        n_insample_perms=args.insample_perms,
        n_wf_perms=args.walkforward_perms,
    )
    print("\n=== MCPT VERDICT ===")
    for k, v in verdict.items():
        print(f"  {k:24s}: {v}")
    print("\nGate: PASS only if in-sample MCPT p < 0.01 AND walk-forward MCPT p < 0.05.")
    print("A REJECT means discard the hypothesis. Do NOT re-tune and rerun.")


if __name__ == "__main__":
    main()
