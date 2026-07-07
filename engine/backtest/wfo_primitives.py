"""
wfo_primitives.py — shared walk-forward optimization building blocks.

Every runner file (run_mgc_trend_rank4.py, run_mes_trend_rank11.py, etc.)
duplicates the same private WFO functions.  This module is the single source.

Runners can adopt it incrementally: import what they need and drop their local
copies.  Runners not yet migrated continue to work as-is.

Typical usage::

    from backtest.wfo_primitives import generate_windows, grid_search_is
    from backtest.wfo_primitives import run_oos_window, run_wfo

    # Caller provides run_fn that wraps its signal generator + Backtester.
    # Signature: run_fn(df: pd.DataFrame, params: dict) -> BacktestResult
    def run_fn(df, params):
        from backtest.backtester import Backtester
        from backtest.trend_signals import generate_sma_trend_signals
        sigs = generate_sma_trend_signals(df, **params)
        bt = Backtester(initial_capital=50_000.0, ...)
        return bt.run(sigs, symbol="MGC", multiplier=10.0)

    oos_results = run_wfo(
        df, grid, run_fn,
        train_months=6, test_months=2, step_months=1,
    )
"""

from __future__ import annotations

from typing import Any, Callable, Optional

import pandas as pd


def generate_windows(
    df: pd.DataFrame,
    train_months: int,
    test_months: int,
    step_months: int,
    min_bars: int = 30,
) -> list:
    """Generate non-overlapping walk-forward windows from a DatetimeIndex DataFrame.

    Args:
        df: OHLCV DataFrame with a DatetimeIndex (sorted ascending).
        train_months: In-sample window length in calendar months.
        test_months: Out-of-sample window length in calendar months.
        step_months: How many months to advance the cursor between windows.
        min_bars: Minimum rows required in both IS and OOS slices.

    Returns:
        List of window dicts with keys:
            window_num  (int, 1-based)
            train_start (Timestamp)
            train_end   (Timestamp)
            test_start  (Timestamp)
            test_end    (Timestamp)
            n_train     (int)
            n_test      (int)
    """
    data_start = df.index.min()
    data_end = df.index.max()
    windows = []
    cursor = data_start
    wnum = 1

    while True:
        train_start = cursor
        train_end = train_start + pd.DateOffset(months=train_months)
        test_start = train_end
        test_end = test_start + pd.DateOffset(months=test_months)

        if test_start >= data_end:
            break
        if test_end > data_end:
            test_end = data_end

        df_train = df[(df.index >= train_start) & (df.index < train_end)]
        df_test = df[(df.index >= test_start) & (df.index <= test_end)]

        if len(df_train) >= min_bars and len(df_test) >= min_bars:
            windows.append(
                {
                    "window_num": wnum,
                    "train_start": train_start,
                    "train_end": train_end,
                    "test_start": test_start,
                    "test_end": test_end,
                    "n_train": len(df_train),
                    "n_test": len(df_test),
                }
            )
            wnum += 1

        cursor += pd.DateOffset(months=step_months)
        if cursor >= data_end:
            break

    return windows


def grid_search_is(
    df_train: pd.DataFrame,
    grid: list,
    run_fn: Callable[[pd.DataFrame, dict], Any],
    min_trades: int = 1,
) -> tuple:
    """IS grid search: find the grid point with the highest in-sample profit factor.

    Args:
        df_train: In-sample data slice.
        grid: List of param dicts (e.g. [{"fast": 40, "slow": 80, ...}, ...]).
        run_fn: Callable(df, params) -> result.  result must expose
                .profit_factor (float) and .total_trades (int).
        min_trades: Grid points with fewer IS trades are skipped.

    Returns:
        (best_params, best_result) — both None when no valid grid point found.
    """
    best_pf: float = -1.0
    best_params: Optional[dict] = None
    best_result: Any = None

    for params in grid:
        try:
            result = run_fn(df_train, params)
        except Exception:
            continue
        if result.total_trades < min_trades:
            continue
        pf = result.profit_factor
        if pf > best_pf:
            best_pf = pf
            best_params = params
            best_result = result

    return best_params, best_result


def run_oos_window(
    df_test: pd.DataFrame,
    params: dict,
    run_fn: Callable[[pd.DataFrame, dict], Any],
) -> Any:
    """Run a single OOS window with the IS-selected params.

    Returns:
        BacktestResult (or duck-typed equivalent) on success; None if run_fn raises.
    """
    try:
        return run_fn(df_test, params)
    except Exception:
        return None


def run_wfo(
    df: pd.DataFrame,
    grid: list,
    run_fn: Callable[[pd.DataFrame, dict], Any],
    train_months: int,
    test_months: int,
    step_months: int,
    min_bars: int = 30,
    min_trades: int = 1,
) -> list:
    """Full walk-forward optimization: window generation → IS search → OOS eval.

    Args:
        df: Full OHLCV DataFrame with DatetimeIndex.
        grid: List of param dicts tried during IS search.
        run_fn: Callable(df, params) -> BacktestResult (or duck-typed equivalent).
        train_months: IS window length in calendar months.
        test_months: OOS window length in calendar months.
        step_months: Cursor step between successive windows.
        min_bars: Minimum bars per IS/OOS slice (windows below this are skipped).
        min_trades: Minimum IS trades for a grid point to be considered valid.

    Returns:
        List of OOS results, one per window where IS search succeeded and OOS
        execution did not raise.  Empty when no windows form or all IS fail.
    """
    windows = generate_windows(df, train_months, test_months, step_months, min_bars)
    oos_results = []

    for win in windows:
        ts, te = win["train_start"], win["train_end"]
        os_, oe = win["test_start"], win["test_end"]

        df_train = df[(df.index >= ts) & (df.index < te)].copy()
        df_test = df[(df.index >= os_) & (df.index <= oe)].copy()

        best_params, _ = grid_search_is(df_train, grid, run_fn, min_trades)
        if best_params is None:
            continue

        oos_result = run_oos_window(df_test, best_params, run_fn)
        if oos_result is None:
            continue

        oos_results.append(oos_result)

    return oos_results
