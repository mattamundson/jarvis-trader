"""Parity tests for the linear-time KAMA volatility calculation."""

import numpy as np
import pandas as pd

from backtest.indicators import kama


def _reference_kama(close: pd.Series, period: int = 10) -> pd.Series:
    fast_sc = 2.0 / 3.0
    slow_sc = 2.0 / 31.0
    result = pd.Series(np.nan, index=close.index, dtype=float)
    if len(close) < period:
        return result
    result.iloc[period - 1] = close.iloc[period - 1]
    differences = close.diff().abs()
    for index in range(period, len(close)):
        change = abs(close.iloc[index] - close.iloc[index - period])
        volatility = differences.iloc[index - period + 1 : index + 1].sum()
        efficiency_ratio = 0.0 if volatility == 0 else change / volatility
        smoothing = (efficiency_ratio * (fast_sc - slow_sc) + slow_sc) ** 2
        result.iloc[index] = result.iloc[index - 1] + smoothing * (
            close.iloc[index] - result.iloc[index - 1]
        )
    return result


def test_kama_matches_reference_calculation() -> None:
    close = pd.Series(
        [100.0, 101.0, 99.5, 102.0, 103.0, 102.5, 104.0, 103.5, 105.0, 106.0] * 5
    )
    pd.testing.assert_series_equal(kama(close), _reference_kama(close), check_exact=False, rtol=1e-14)


def test_kama_flat_prices_remain_flat() -> None:
    close = pd.Series([5000.0] * 30)
    result = kama(close)
    assert result.iloc[:9].isna().all()
    assert (result.iloc[9:] == 5000.0).all()
