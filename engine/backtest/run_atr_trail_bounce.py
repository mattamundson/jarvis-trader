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
import re
import sys
from datetime import date
from itertools import product
from pathlib import Path

import pandas as pd

ENGINE_ROOT = Path(__file__).resolve().parent.parent
if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))

from backtest.atr_trail_bounce_signals import (  # noqa: E402
    generate_atr_trail_bounce_signals,
    generate_atr_trail_confluence_signals,
    generate_atr_trail_fade_signals,
    generate_atr_trail_flip_signals,
    generate_atr_trail_kelt_confluence_signals,
    generate_atr_trail_tpotarget_confluence_signals,
)
from backtest.backtester import Backtester  # noqa: E402
from backtest.contract_specs import CONTRACT_SPECS  # noqa: E402

_CACHE_RANGE_RE = re.compile(r"_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})_")


def _pick_cache_file(paths: list[Path]) -> Path:
    """Pick the most useful cache file: latest END date, tie-broken by longest span.

    The cache convention is ``<SYM>_<start>_<end>_<tf>.csv`` with ISO dates. A naive
    ``sorted(paths)[-1]`` sorts the *strings* and so picks the file with the latest
    START date — which is usually the SHORTEST, most-recent slice (e.g. a 2-month
    tail), silently ignoring a freshly-refreshed multi-year file whose start date
    sorts earlier. That bug ran the whole ATR-trail backtest on ~965 bars / ~21
    trades instead of the 12.5k-bar 2-year file, and made the refresh step a no-op.

    Parse the range instead: prefer the file that ENDS latest (freshest data), break
    ties toward the EARLIEST start (longest history), then newest mtime. Files whose
    names carry no parseable range fall back to mtime only and rank below any that do.
    """

    def key(p: Path):
        m = _CACHE_RANGE_RE.search(p.name)
        if m:
            start = date.fromisoformat(m.group(1)).toordinal()
            end = date.fromisoformat(m.group(2)).toordinal()
            return (1, end, -start, p.stat().st_mtime)
        return (0, 0, 0, p.stat().st_mtime)

    return max(paths, key=key)


# ── Locked spec ────────────────────────────────────────────────────────────
ATR_PERIOD = 5
FACTOR_GRID = [3.0, 3.5, 4.0]
HOLD_BARS_GRID = [0, 1, 2]
TOUCH_TOL_GRID = [0.0, 0.10]
PARAM_GRID = list(product(FACTOR_GRID, HOLD_BARS_GRID, TOUCH_TOL_GRID))

# ── Instrument economics (mirror run_mes_trend_rank8.py) ─────────────────────
MULTIPLIERS = {"MES": 5.0, "ES": 50.0, "MNQ": 2.0, "MCL": 100.0, "MGC": 10.0}
CAPITAL = 50_000.0
# Was a flat COMMISSION=0.62 applied to every --symbol (found 2026-07-10):
# correct for MES/ES/MNQ, but wrong for MCL/MGC (0.85 per contract_specs.py).
# Kept as a fallback default for any symbol missing from CONTRACT_SPECS.
_DEFAULT_COMMISSION = 0.62
SLIPPAGE_TICKS = 1.0
MIN_TRADES = 20  # below this a PF is not trustworthy


def _commission_for(symbol: str) -> float:
    spec = CONTRACT_SPECS.get(symbol)
    return spec.commission if spec is not None else _DEFAULT_COMMISSION


def _load(symbol: str, timeframe: str, data_file: str | None) -> pd.DataFrame:
    if data_file:
        path = Path(data_file)
    else:
        cache = ENGINE_ROOT / "backtest" / "cache"
        matches = list(cache.glob(f"{symbol}_*_{timeframe}.csv"))
        if not matches:
            raise SystemExit(
                f"No cache file matching {symbol}_*_{timeframe}.csv in {cache}. "
                f"Pass --data-file explicitly."
            )
        # Pick the freshest+longest file by parsing the date range — NOT the
        # lexicographically-last one, which silently picks the shortest recent
        # tail and ignores a freshly-refreshed multi-year file. See _pick_cache_file.
        path = _pick_cache_file(matches)
    print(f"[ATR-BOUNCE] loading {path.name}")
    df = pd.read_csv(path)
    df.columns = [c.lower() for c in df.columns]
    required = {"open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise SystemExit(f"Missing columns in {path.name}: {missing}")
    # The backtester, TPO confluence, and MTF Keltner all need a DatetimeIndex.
    # Without one, the Backtester raises "'int' object has no attribute 'date'"
    # (it groups bars by .date() for the daily-loss limit) — which the runner's
    # broad `except Exception: continue` silently swallows, making every param
    # set look like it produced 0 trades ("too rare on this data").
    for tcol in ("timestamp", "datetime", "date", "time"):
        if tcol in df.columns:
            df[tcol] = pd.to_datetime(df[tcol], utc=True)
            df = df.set_index(tcol).sort_index()
            break
    else:
        raise SystemExit(
            f"No timestamp/datetime column in {path.name}; the Backtester needs a "
            f"DatetimeIndex. Columns: {list(df.columns)}"
        )
    return df


def _grid_for(mode: str) -> list[dict]:
    """Locked param grids, per mode."""
    if mode == "flip":
        return [{"factor": f} for f in FACTOR_GRID]
    if mode == "confluence":
        # flip base + prior-session value-area gate; sweep factor x strictness
        return [{"factor": f, "strict_confluence": s} for f in FACTOR_GRID for s in (False, True)]
    if mode == "kelt":
        # flip base + 4H Keltner gate; sweep factor x strictness
        return [{"factor": f, "strict_kelt": s} for f in FACTOR_GRID for s in (False, True)]
    if mode == "tpotgt":
        # flip base + TPO measured-move direction gate; sweep factor x room
        return [{"factor": f, "require_room": r} for f in FACTOR_GRID for r in (False, True)]
    if mode == "fade":
        # mean-reversion inverse of flip; sweep factor x reversion target (ATR mult).
        # stop is fixed at 1.0 ATR so target_atr both sets the goal AND the R:R
        # (target/stop). 1.5 and 2.0 both clear the Backtester's R:R>=1.2 gate.
        return [{"factor": f, "target_atr": t} for f in FACTOR_GRID for t in (1.5, 2.0)]
    return [{"factor": f, "hold_bars": h, "touch_tol_atr": t} for f, h, t in PARAM_GRID]


def _signals_for(mode: str, df: pd.DataFrame, params: dict):
    if mode == "flip":
        return generate_atr_trail_flip_signals(df, atr_period=ATR_PERIOD, factor=params["factor"])
    if mode == "confluence":
        return generate_atr_trail_confluence_signals(
            df,
            atr_period=ATR_PERIOD,
            factor=params["factor"],
            base="flip",
            strict_confluence=params["strict_confluence"],
        )
    if mode == "kelt":
        return generate_atr_trail_kelt_confluence_signals(
            df,
            atr_period=ATR_PERIOD,
            factor=params["factor"],
            base="flip",
            strict_kelt=params["strict_kelt"],
        )
    if mode == "tpotgt":
        return generate_atr_trail_tpotarget_confluence_signals(
            df,
            atr_period=ATR_PERIOD,
            factor=params["factor"],
            base="flip",
            require_room=params["require_room"],
        )
    if mode == "fade":
        return generate_atr_trail_fade_signals(
            df,
            atr_period=ATR_PERIOD,
            factor=params["factor"],
            target_atr=params["target_atr"],
        )
    return generate_atr_trail_bounce_signals(
        df,
        atr_period=ATR_PERIOD,
        factor=params["factor"],
        hold_bars=params["hold_bars"],
        touch_tol_atr=params["touch_tol_atr"],
    )


def _backtest(df: pd.DataFrame, symbol: str, mode: str, params: dict):
    sig = _signals_for(mode, df, params)
    kwargs = {
        "initial_capital": CAPITAL,
        "risk_per_trade": 0.01,
        "max_daily_loss": 0.02,
        "max_drawdown": 0.05,
        "commission_per_contract": _commission_for(symbol),
        "slippage_ticks": SLIPPAGE_TICKS,
    }
    if mode in ("flip", "confluence", "kelt", "tpotgt"):
        # flip + all confluence variants ride a flip base (trend-following): exit
        # on the opposite flip (exit_signal=EXIT_NOW) with a trailing stop, no
        # fixed targets, hold overnight, 1 contract — the SMA-trend convention.
        kwargs.update(
            use_targets=False,
            eod_close=False,
            fixed_contracts=1,
            trailing_stop=True,
            strict_trailing=True,
        )
    elif mode == "fade":
        # fade is mean-reversion: it TAKES PROFIT at a fixed ATR target and stops
        # out beyond the breakout — so it needs use_targets=True and NO trailing
        # stop (the opposite of the trend-following family). 1 contract, hold
        # overnight, to stay comparable to the flip it inverts.
        kwargs.update(
            use_targets=True,
            eod_close=False,
            fixed_contracts=1,
            trailing_stop=False,
        )
    bt = Backtester(**kwargs)
    return bt.run(sig, symbol=symbol, multiplier=MULTIPLIERS.get(symbol, 1.0))


def _make_optimize_fn(symbol: str, mode: str):
    """optimize_fn(df) -> (best_params, best_profit_factor) over the LOCKED grid."""
    grid = _grid_for(mode)

    def optimize_fn(df: pd.DataFrame):
        best_pf, best_params = -1.0, None
        for params in grid:
            try:
                res = _backtest(df, symbol, mode, params)
            except Exception:
                continue
            if res.total_trades < MIN_TRADES:
                continue
            if res.profit_factor > best_pf:
                best_pf = res.profit_factor
                best_params = params
        return best_params, (best_pf if best_pf > 0 else 0.0)

    return optimize_fn


def _make_walkforward_fn(symbol: str, mode: str):
    """walkforward_fn(df, train_window) -> OOS profit factor via rolling re-opt."""
    optimize_fn = _make_optimize_fn(symbol, mode)

    def walkforward_fn(df: pd.DataFrame, train_window: int) -> float:
        if len(df) <= train_window + MIN_TRADES:
            return 0.0
        params, _ = optimize_fn(df.iloc[:train_window])
        if not params:
            return 0.0
        # Keep the DatetimeIndex on the OOS slice — the Backtester groups by
        # .date() for the daily-loss limit. reset_index(drop=True) would replace
        # it with a RangeIndex, crash the backtest, get swallowed by the
        # `except` below (-> 0.0), and silently fail the walk-forward gate for
        # every strategy. (See test_walkforward_oos_preserves_datetime_index.)
        oos = df.iloc[train_window:]
        try:
            res = _backtest(oos, symbol, mode, params)
        except Exception:
            return 0.0
        return res.profit_factor if res.total_trades >= MIN_TRADES else 0.0

    return walkforward_fn


def _run_mode(mode: str, df: pd.DataFrame, args) -> None:
    label = {
        "bounce": "BOUNCE (tag+reclaim+hold)",
        "flip": "FLIP (stop-and-reverse / TOS LE/SE)",
        "confluence": "CONFLUENCE (flip + prior-session value-area gate)",
        "kelt": "KELT-CONFLUENCE (flip + 4H Keltner gate)",
        "tpotgt": "TPO-TARGET (flip + profile measured-move direction gate)",
        "fade": "FADE (mean-reversion inverse of flip — fade the breakout)",
    }[mode]
    optimize_fn = _make_optimize_fn(args.symbol, mode)
    grid = _grid_for(mode)

    print(f"\n{'=' * 72}\nMODE: {label}\n{'=' * 72}")
    print(f"[ATR-{mode.upper()}] grid-searching {len(grid)} param sets on {len(df)} bars ...")
    best_params, _ = optimize_fn(df)
    if not best_params:
        print(f"  No param set produced >= {MIN_TRADES} trades — too rare on this data. Skipping.")
        return

    res = _backtest(df, args.symbol, mode, best_params)
    print("\n--- HEADLINE (full-sample, best in-sample params) ---")
    print(f"  params        : {best_params}")
    print(f"  trades        : {res.total_trades}")
    print(f"  profit factor : {res.profit_factor:.3f}")
    print(f"  win rate      : {getattr(res, 'win_rate', float('nan')):.1%}")
    print(f"  sharpe        : {getattr(res, 'sharpe_ratio', float('nan')):.2f}")
    print(f"  max drawdown  : {getattr(res, 'max_drawdown_pct', float('nan')):.2%}")
    print("  NOTE: full-sample PF is optimistic — the MCPT verdict below is what matters.")

    if args.skip_mcpt:
        return

    print(f"\n[ATR-{mode.upper()}] running bar-permutation MCPT (the honest test) ...")
    from analytics.permutation_test import validate_strategy

    verdict = validate_strategy(
        df,
        optimize_fn,
        _make_walkforward_fn(args.symbol, mode),
        train_window=args.train_window,
        n_insample_perms=args.insample_perms,
        n_wf_perms=args.walkforward_perms,
    )
    print("--- MCPT VERDICT ---")
    for k, v in verdict.items():
        print(f"  {k:24s}: {v}")


def main() -> None:
    ap = argparse.ArgumentParser(description="ATR trail bounce/flip backtest + MCPT")
    ap.add_argument("--symbol", default="MES")
    ap.add_argument("--timeframe", default="1h")
    ap.add_argument("--data-file", default=None)
    ap.add_argument(
        "--mode",
        choices=["bounce", "flip", "confluence", "kelt", "tpotgt", "fade", "both", "all"],
        default="all",
        help="bounce = tag+reclaim+hold; flip = TOS LE/SE stop-and-reverse; "
        "confluence = flip + prior-session value-area gate; "
        "kelt = flip + 4H Keltner gate; tpotgt = flip + TPO target direction; "
        "fade = mean-reversion inverse of flip (fresh hypothesis, opt-in only); "
        "both = bounce+flip; all = bounce+flip+confluence+kelt+tpotgt "
        "(fade is NOT in 'all' — it is a distinct hypothesis, run it explicitly)",
    )
    ap.add_argument("--train-window", type=int, default=2000, help="bars for MCPT in-sample")
    ap.add_argument("--insample-perms", type=int, default=200)
    ap.add_argument("--walkforward-perms", type=int, default=200)
    ap.add_argument("--skip-mcpt", action="store_true")
    args = ap.parse_args()

    df = _load(args.symbol, args.timeframe, args.data_file)
    mode_sets = {
        "both": ["bounce", "flip"],
        "all": ["bounce", "flip", "confluence", "kelt", "tpotgt"],
    }
    modes = mode_sets.get(args.mode, [args.mode])
    for mode in modes:
        _run_mode(mode, df, args)

    print("\nGate: PASS only if in-sample MCPT p < 0.01 AND walk-forward MCPT p < 0.05.")
    print("A REJECT means discard that variant. Do NOT re-tune and rerun (data-mines the p-value).")


if __name__ == "__main__":
    main()
