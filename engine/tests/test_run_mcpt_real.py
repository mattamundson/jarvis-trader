"""Tests for run_mcpt's real Backtester optimizer path and PF cap.

These exercise the production strategy glue (config_for -> generate_sma_trend_signals ->
Backtester) on a small synthetic frame -- no market data needed. The real path needs
pydantic + the engine config (API_KEY); the test sets a dummy key and skips cleanly if
the engine config stack is unavailable, so it never breaks a dependency-light CI slice.
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("pydantic")
os.environ.setdefault("API_KEY", "test-key")  # TradingConfig requires a non-empty key

from backtest import run_mcpt


def _frame(n: int = 900, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 4000.0 * np.exp(np.cumsum(rng.normal(0.0003, 0.004, n)))
    open_ = np.empty(n)
    open_[0] = close[0]
    open_[1:] = close[:-1]
    idx = pd.date_range("2024-01-01", periods=n, freq="h")
    return pd.DataFrame(
        {"open": open_, "high": np.maximum(open_, close) * 1.0006,
         "low": np.minimum(open_, close) * 0.9994, "close": close},
        index=idx,
    )


def test_cap_pf():
    assert run_mcpt._cap_pf(float("inf")) == run_mcpt._PF_CAP
    assert run_mcpt._cap_pf(float("nan")) == run_mcpt._PF_CAP
    assert run_mcpt._cap_pf(3.0) == 3.0
    assert run_mcpt._cap_pf(99.0) == run_mcpt._PF_CAP


def test_real_optimizer_runs_and_is_capped():
    try:
        optimize_fn, walkforward_fn = run_mcpt._real_strategy_factory("MES", capital=10_000.0)
    except Exception as exc:  # pragma: no cover - engine config stack absent in light CI
        pytest.skip(f"real Backtester path unavailable: {exc}")

    df = _frame()
    params, pf = optimize_fn(df)
    assert isinstance(params, tuple) and len(params) == 3  # (fast, slow, atr_trail)
    assert 0.0 <= pf <= run_mcpt._PF_CAP  # cap holds even on a no-loss window

    wf_pf = walkforward_fn(df, train_window=500, step=200)
    assert 0.0 <= wf_pf <= run_mcpt._PF_CAP
