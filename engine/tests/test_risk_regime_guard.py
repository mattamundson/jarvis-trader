"""
Tests for risk/regime_guard.py — RegimeGuard public API.

Covers: get_market_regime (trending, ranging, unknown paths, DataFrame and
list-of-bars interfaces, missing columns, empty bars, ADX NaN), is_suitable_for_mm.
Uses mocked data_manager and JesseIndicators to avoid real network calls.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from risk.regime_guard import RegimeGuard


def _guard(adx_threshold=25.0) -> RegimeGuard:
    dm = AsyncMock()
    return RegimeGuard(data_manager=dm, adx_threshold=adx_threshold)


def _df_with_ohlcv(n=30) -> pd.DataFrame:
    """Minimal OHLCV DataFrame for indicator calculation."""
    return pd.DataFrame(
        {
            "open": np.full(n, 5800.0),
            "high": np.full(n, 5810.0),
            "low": np.full(n, 5790.0),
            "close": np.full(n, 5800.0),
            "volume": np.full(n, 1000.0),
        }
    )


@pytest.mark.asyncio
class TestGetMarketRegime:
    async def test_trending_when_adx_above_threshold(self):
        guard = _guard(adx_threshold=25.0)
        guard.data_manager.get_bars.return_value = _df_with_ohlcv(30)

        # Mock JesseIndicators.adx to return a high-ADX DataFrame
        adx_df = pd.DataFrame({"ADX_14": [30.0]})
        with patch.object(guard.indicators, "adx", return_value=adx_df):
            regime = await guard.get_market_regime("SPY")

        assert regime == "trending"
        assert guard.last_regime == "trending"
        assert guard.last_check is not None

    async def test_ranging_when_adx_below_threshold(self):
        guard = _guard(adx_threshold=25.0)
        guard.data_manager.get_bars.return_value = _df_with_ohlcv(30)

        adx_df = pd.DataFrame({"ADX_14": [15.0]})
        with patch.object(guard.indicators, "adx", return_value=adx_df):
            regime = await guard.get_market_regime("SPY")

        assert regime == "ranging"
        assert guard.last_regime == "ranging"

    async def test_empty_dataframe_returns_unknown(self):
        guard = _guard()
        guard.data_manager.get_bars.return_value = pd.DataFrame()
        regime = await guard.get_market_regime("SPY")
        assert regime == "unknown"

    async def test_too_few_bars_returns_unknown(self):
        guard = _guard()
        guard.data_manager.get_bars.return_value = _df_with_ohlcv(5)
        regime = await guard.get_market_regime("SPY")
        assert regime == "unknown"

    async def test_missing_ohlc_columns_returns_unknown(self):
        guard = _guard()
        # DataFrame without 'high', 'low', 'close'
        df = pd.DataFrame({"open": [5800.0] * 30, "volume": [1000.0] * 30})
        guard.data_manager.get_bars.return_value = df
        regime = await guard.get_market_regime("SPY")
        assert regime == "unknown"

    async def test_adx_returns_none_returns_unknown(self):
        guard = _guard()
        guard.data_manager.get_bars.return_value = _df_with_ohlcv(30)
        with patch.object(guard.indicators, "adx", return_value=None):
            regime = await guard.get_market_regime("SPY")
        assert regime == "unknown"

    async def test_adx_returns_empty_df_returns_unknown(self):
        guard = _guard()
        guard.data_manager.get_bars.return_value = _df_with_ohlcv(30)
        with patch.object(guard.indicators, "adx", return_value=pd.DataFrame()):
            regime = await guard.get_market_regime("SPY")
        assert regime == "unknown"

    async def test_adx_no_adx_column_returns_unknown(self):
        guard = _guard()
        guard.data_manager.get_bars.return_value = _df_with_ohlcv(30)
        # ADX DataFrame with no column containing 'ADX'
        adx_df = pd.DataFrame({"SMA_14": [20.0]})
        with patch.object(guard.indicators, "adx", return_value=adx_df):
            regime = await guard.get_market_regime("SPY")
        assert regime == "unknown"

    async def test_adx_nan_value_returns_unknown(self):
        guard = _guard()
        guard.data_manager.get_bars.return_value = _df_with_ohlcv(30)
        adx_df = pd.DataFrame({"ADX_14": [float("nan")]})
        with patch.object(guard.indicators, "adx", return_value=adx_df):
            regime = await guard.get_market_regime("SPY")
        assert regime == "unknown"

    async def test_data_manager_exception_returns_unknown(self):
        guard = _guard()
        guard.data_manager.get_bars.side_effect = RuntimeError("Market data unavailable")
        regime = await guard.get_market_regime("SPY")
        assert regime == "unknown"

    async def test_list_of_bars_interface(self):
        """Legacy list-of-dicts interface (non-DataFrame) is handled."""
        guard = _guard(adx_threshold=25.0)
        # Return a list of bar dicts (legacy connector format)
        bars = [
            {"open": 5800.0, "high": 5810.0, "low": 5790.0, "close": 5800.0, "volume": 1000}
        ] * 30
        guard.data_manager.get_bars.return_value = bars

        adx_df = pd.DataFrame({"ADX_14": [30.0]})
        with patch.object(guard.indicators, "adx", return_value=adx_df):
            regime = await guard.get_market_regime("MES")

        assert regime == "trending"

    async def test_list_too_short_returns_unknown(self):
        guard = _guard()
        # list with <20 items
        bars = [{"open": 5800.0, "high": 5810.0, "low": 5790.0, "close": 5800.0}] * 5
        guard.data_manager.get_bars.return_value = bars
        regime = await guard.get_market_regime("MES")
        assert regime == "unknown"

    async def test_empty_list_returns_unknown(self):
        guard = _guard()
        guard.data_manager.get_bars.return_value = []
        regime = await guard.get_market_regime("MES")
        assert regime == "unknown"

    async def test_adx_exactly_at_threshold_returns_ranging(self):
        """ADX == threshold is NOT > threshold, so returns 'ranging'."""
        guard = _guard(adx_threshold=25.0)
        guard.data_manager.get_bars.return_value = _df_with_ohlcv(30)
        adx_df = pd.DataFrame({"ADX_14": [25.0]})
        with patch.object(guard.indicators, "adx", return_value=adx_df):
            regime = await guard.get_market_regime("SPY")
        assert regime == "ranging"

    async def test_custom_symbol_forwarded_to_data_manager(self):
        guard = _guard()
        guard.data_manager.get_bars.return_value = pd.DataFrame()
        await guard.get_market_regime("MES")
        guard.data_manager.get_bars.assert_called_once_with("MES", timeframe="1h", count=100)


class TestIsSuitableForMM:
    def test_initially_not_suitable(self):
        guard = _guard()
        # last_regime starts as "unknown"
        assert guard.is_suitable_for_mm() is False

    def test_ranging_regime_is_suitable(self):
        guard = _guard()
        guard.last_regime = "ranging"
        assert guard.is_suitable_for_mm() is True

    def test_trending_regime_not_suitable(self):
        guard = _guard()
        guard.last_regime = "trending"
        assert guard.is_suitable_for_mm() is False

    def test_unknown_regime_not_suitable(self):
        guard = _guard()
        guard.last_regime = "unknown"
        assert guard.is_suitable_for_mm() is False

    def test_custom_symbol_does_not_affect_last_regime(self):
        """is_suitable_for_mm uses last_regime; symbol arg is informational."""
        guard = _guard()
        guard.last_regime = "ranging"
        assert guard.is_suitable_for_mm("MES") is True
        assert guard.is_suitable_for_mm("SPY") is True
