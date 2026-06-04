"""
Tests for the real-ATR trailing stop (behind TRAILING_STOP_USE_REAL_ATR).

Default (flag off): the legacy 0.5%-of-price proxy is used unchanged.
Flag on: ATRr_14 from recent bars, with a clean proxy fallback when bars are
unavailable. The flag defaults off so live stop distances are unaffected until
Amo A/Bs it in paper.
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pandas as pd
import pytest

from services.trailing_stop_manager import TrailingStopManager


def _ohlcv(n: int = 40) -> pd.DataFrame:
    # Gentle uptrend with a steady ~2.0 true range per bar.
    rows = []
    base = 5000.0
    for i in range(n):
        c = base + i
        rows.append({"open": c - 0.5, "high": c + 1.0, "low": c - 1.0, "close": c})
    return pd.DataFrame(rows)


class _FakeData:
    def __init__(self, df: pd.DataFrame | None):
        self._df = df

    async def get_bars(self, symbol, lookback_days=5, timeframe="5m", is_futures=False):
        if self._df is None:
            raise RuntimeError("no feed")
        return self._df


def _mgr(df: pd.DataFrame | None) -> TrailingStopManager:
    return TrailingStopManager(oms_manager=object(), data_manager=_FakeData(df))


@pytest.mark.asyncio
async def test_flag_off_uses_proxy(monkeypatch):
    monkeypatch.delenv("TRAILING_STOP_USE_REAL_ATR", raising=False)
    mgr = _mgr(_ohlcv())
    atr = await mgr._resolve_atr("MES", current_price=5000.0)
    assert atr == pytest.approx(5000.0 * 0.005)  # 25.0 proxy


@pytest.mark.asyncio
async def test_flag_on_uses_real_atr(monkeypatch):
    monkeypatch.setenv("TRAILING_STOP_USE_REAL_ATR", "1")
    mgr = _mgr(_ohlcv())
    atr = await mgr._resolve_atr("MES", current_price=5000.0)
    # Real ATR for a ~2.0-TR series is far smaller than the 25.0 proxy.
    assert atr is not None
    assert 0.0 < atr < 10.0
    assert atr != pytest.approx(25.0)


@pytest.mark.asyncio
async def test_flag_on_no_bars_falls_back_to_proxy(monkeypatch):
    monkeypatch.setenv("TRAILING_STOP_USE_REAL_ATR", "1")
    mgr = _mgr(pd.DataFrame())  # empty
    atr = await mgr._resolve_atr("MES", current_price=5000.0)
    assert atr == pytest.approx(25.0)


@pytest.mark.asyncio
async def test_flag_on_feed_error_falls_back_to_proxy(monkeypatch):
    monkeypatch.setenv("TRAILING_STOP_USE_REAL_ATR", "1")
    mgr = _mgr(None)  # get_bars raises
    atr = await mgr._resolve_atr("MES", current_price=5000.0)
    assert atr == pytest.approx(25.0)


@pytest.mark.asyncio
async def test_compute_atr_positive_on_synthetic_bars():
    mgr = _mgr(_ohlcv())
    atr = await mgr._compute_atr("MES")
    assert atr is not None and atr > 0
