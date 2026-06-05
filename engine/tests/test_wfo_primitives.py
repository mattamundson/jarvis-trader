"""Tests for backtest.wfo_primitives — shared WFO building blocks.

Covers all four public functions with synthetic DataFrames and lightweight
duck-typed result objects so no real market data or IBKR connection is needed.
"""

from __future__ import annotations

import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

_engine = Path(__file__).parent.parent
if str(_engine) not in sys.path:
    sys.path.insert(0, str(_engine))

from backtest.wfo_primitives import (
    generate_windows,
    grid_search_is,
    run_oos_window,
    run_wfo,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_df(n_months: int = 24, freq: str = "h") -> pd.DataFrame:
    """Synthetic hourly OHLCV DataFrame spanning n_months calendar months."""
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    idx = pd.date_range(start=start, periods=n_months * 30 * 24, freq=freq)
    close = 2000.0 + pd.Series(range(len(idx)), index=idx, dtype=float)
    df = pd.DataFrame(
        {"open": close, "high": close + 1.0, "low": close - 1.0, "close": close},
        index=idx,
    )
    return df


def _make_result(
    *, pf: float = 1.5, trades: int = 10, dd: float = -0.02, sharpe: float = 1.0
) -> Any:
    """Lightweight BacktestResult stand-in."""
    return SimpleNamespace(
        profit_factor=pf,
        total_trades=trades,
        max_drawdown_pct=dd,
        sharpe_ratio=sharpe,
    )


def _make_run_fn(pf: float = 1.5, trades: int = 10) -> Any:
    """run_fn that always returns a fixed result."""

    def run_fn(df: pd.DataFrame, params: dict) -> Any:  # noqa: ARG001
        return _make_result(pf=pf, trades=trades)

    return run_fn


# ---------------------------------------------------------------------------
# generate_windows
# ---------------------------------------------------------------------------


class TestGenerateWindows:
    def test_returns_list(self):
        df = _make_df(24)
        windows = generate_windows(df, train_months=6, test_months=2, step_months=1)
        assert isinstance(windows, list)

    def test_nonempty_for_sufficient_data(self):
        df = _make_df(24)
        windows = generate_windows(df, train_months=6, test_months=2, step_months=1)
        assert len(windows) > 0

    def test_window_has_required_keys(self):
        df = _make_df(24)
        windows = generate_windows(df, train_months=6, test_months=2, step_months=1)
        required = {
            "window_num",
            "train_start",
            "train_end",
            "test_start",
            "test_end",
            "n_train",
            "n_test",
        }
        for win in windows:
            assert required.issubset(win.keys()), f"window missing keys: {required - win.keys()}"

    def test_window_nums_are_sequential(self):
        df = _make_df(24)
        windows = generate_windows(df, train_months=6, test_months=2, step_months=1)
        nums = [w["window_num"] for w in windows]
        assert nums == list(range(1, len(windows) + 1))

    def test_window_nums_gapless_when_early_window_filtered(self):
        """window_num must stay [1,2,3..] with no gap even when the EARLY
        cursors are skipped by the min_bars filter.

        wnum increments only when a window is appended, so a filtered leading
        window must NOT consume a number — the first surviving window is #1.
        Build sparse data (10 daily bars in Jan, nothing in Feb/Mar) followed
        by dense hourly data from April so the first two cursors fail min_bars
        and the third is the first to pass.
        """
        sparse = pd.date_range(start="2024-01-01", periods=10, freq="D", tz="UTC")
        dense = pd.date_range(start="2024-04-01", periods=18 * 30 * 24, freq="h", tz="UTC")
        idx = sparse.union(dense)
        close = 2000.0 + pd.Series(range(len(idx)), index=idx, dtype=float)
        df = pd.DataFrame(
            {"open": close, "high": close + 1.0, "low": close - 1.0, "close": close},
            index=idx,
        )

        windows = generate_windows(
            df, train_months=2, test_months=1, step_months=1, min_bars=200
        )

        assert len(windows) > 0, "expected some surviving windows after the sparse gap"
        nums = [w["window_num"] for w in windows]
        # Gapless and 1-based despite the skipped leading cursors.
        assert nums == list(range(1, len(windows) + 1))
        # Prove a skip actually happened: the first surviving window does not
        # start at the data's first timestamp (early cursors were filtered).
        assert windows[0]["window_num"] == 1
        assert windows[0]["train_start"] > df.index.min()

    def test_train_end_equals_test_start(self):
        df = _make_df(24)
        for win in generate_windows(df, train_months=6, test_months=2, step_months=1):
            assert win["train_end"] == win["test_start"]

    def test_n_train_n_test_match_slice_lengths(self):
        df = _make_df(24)
        for win in generate_windows(df, train_months=6, test_months=2, step_months=1):
            ts, te = win["train_start"], win["train_end"]
            os_, oe = win["test_start"], win["test_end"]
            actual_train = len(df[(df.index >= ts) & (df.index < te)])
            actual_test = len(df[(df.index >= os_) & (df.index <= oe)])
            assert win["n_train"] == actual_train
            assert win["n_test"] == actual_test

    def test_empty_for_insufficient_data(self):
        df = _make_df(3)  # only 3 months — can't fit 6+2 month windows
        windows = generate_windows(df, train_months=6, test_months=2, step_months=1)
        assert windows == []

    def test_min_bars_filter(self):
        df = _make_df(24)
        # huge min_bars excludes all windows
        windows = generate_windows(
            df, train_months=6, test_months=2, step_months=1, min_bars=999_999
        )
        assert windows == []

    def test_step_months_controls_window_count(self):
        df = _make_df(36)
        step1 = generate_windows(df, train_months=6, test_months=2, step_months=1)
        step3 = generate_windows(df, train_months=6, test_months=2, step_months=3)
        # Smaller step → more windows
        assert len(step1) > len(step3)


# ---------------------------------------------------------------------------
# grid_search_is
# ---------------------------------------------------------------------------


class TestGridSearchIs:
    def _make_df_train(self) -> pd.DataFrame:
        return _make_df(6)

    def test_returns_best_pf(self):
        grid = [{"fast": 10}, {"fast": 20}, {"fast": 30}]
        pfs = [1.2, 2.5, 1.8]

        def run_fn(df, params):
            i = [g["fast"] for g in grid].index(params["fast"])
            return _make_result(pf=pfs[i], trades=5)

        best_params, best_result = grid_search_is(self._make_df_train(), grid, run_fn)
        assert best_params == {"fast": 20}
        assert abs(best_result.profit_factor - 2.5) < 1e-9

    def test_returns_none_when_all_raise(self):
        def always_raise(df, params):
            raise ValueError("broken")

        params, result = grid_search_is(self._make_df_train(), [{"a": 1}], always_raise)
        assert params is None
        assert result is None

    def test_skips_below_min_trades(self):
        grid = [{"fast": 1}, {"fast": 2}]

        def run_fn(df, params):
            trades = 0 if params["fast"] == 1 else 10
            return _make_result(pf=2.0, trades=trades)

        params, result = grid_search_is(self._make_df_train(), grid, run_fn, min_trades=5)
        assert params == {"fast": 2}

    def test_empty_grid_returns_none(self):
        params, result = grid_search_is(self._make_df_train(), [], _make_run_fn())
        assert params is None and result is None

    def test_single_valid_point(self):
        grid = [{"x": 99}]
        params, result = grid_search_is(self._make_df_train(), grid, _make_run_fn(pf=1.7, trades=8))
        assert params == {"x": 99}
        assert result.profit_factor == pytest.approx(1.7)


# ---------------------------------------------------------------------------
# run_oos_window
# ---------------------------------------------------------------------------


class TestRunOosWindow:
    def _df(self) -> pd.DataFrame:
        return _make_df(2)

    def test_returns_result_on_success(self):
        result = run_oos_window(self._df(), {"fast": 10}, _make_run_fn(pf=1.9))
        assert result is not None
        assert result.profit_factor == pytest.approx(1.9)

    def test_returns_none_on_exception(self):
        def bad_fn(df, params):
            raise RuntimeError("oos exploded")

        result = run_oos_window(self._df(), {}, bad_fn)
        assert result is None

    def test_params_passed_through(self):
        received = {}

        def capture_fn(df, params):
            received.update(params)
            return _make_result()

        run_oos_window(self._df(), {"key": "val"}, capture_fn)
        assert received == {"key": "val"}


# ---------------------------------------------------------------------------
# run_wfo
# ---------------------------------------------------------------------------


class TestRunWfo:
    def test_returns_list(self):
        df = _make_df(24)
        results = run_wfo(
            df, [{"x": 1}], _make_run_fn(), train_months=6, test_months=2, step_months=1
        )
        assert isinstance(results, list)

    def test_nonempty_for_valid_data(self):
        df = _make_df(24)
        results = run_wfo(
            df, [{"x": 1}], _make_run_fn(), train_months=6, test_months=2, step_months=1
        )
        assert len(results) > 0

    def test_result_count_matches_windows_with_valid_is(self):
        df = _make_df(24)
        windows = generate_windows(df, train_months=6, test_months=2, step_months=1)
        results = run_wfo(
            df, [{"x": 1}], _make_run_fn(), train_months=6, test_months=2, step_months=1
        )
        assert len(results) == len(windows)

    def test_empty_when_all_oos_fail(self):
        df = _make_df(24)

        def always_raise(df, params):
            raise RuntimeError("always fail")

        results = run_wfo(
            df, [{"x": 1}], always_raise, train_months=6, test_months=2, step_months=1
        )
        assert results == []

    def test_empty_for_insufficient_data(self):
        df = _make_df(3)
        results = run_wfo(
            df, [{"x": 1}], _make_run_fn(), train_months=6, test_months=2, step_months=1
        )
        assert results == []

    def test_result_objects_have_expected_attributes(self):
        df = _make_df(24)
        results = run_wfo(
            df,
            [{"x": 1}],
            _make_run_fn(pf=1.3, trades=7),
            train_months=6,
            test_months=2,
            step_months=1,
        )
        for r in results:
            assert math.isfinite(r.profit_factor)
            assert r.total_trades >= 0

    def test_min_trades_excludes_low_volume_windows(self):
        df = _make_df(24)

        def sparse_fn(df, params):
            return _make_result(pf=1.5, trades=1)

        # min_trades=5 → IS search finds no valid point → all windows skipped
        results = run_wfo(
            df, [{"x": 1}], sparse_fn, train_months=6, test_months=2, step_months=1, min_trades=5
        )
        assert results == []
