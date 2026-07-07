"""Tests for morning_brief.py assembly function."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest


class FakeDataManager:
    async def get_current_price(self, symbol: str):
        if symbol == "MCL":
            return 72.00
        if symbol == "MNQ":
            return 17500.0
        return None

    async def get_bars(self, symbol: str, lookback_days: int = 3, timeframe: str = "1h"):
        return None  # Simulate no bars


class FakeDataManagerWithPrice:
    async def get_current_price(self, symbol: str):
        if symbol == "MCL":
            return 72.50
        if symbol == "MNQ":
            return 17480.0
        return None

    async def get_bars(self, symbol, **kwargs):
        return None


class FakePaperTracker:
    def __init__(self, positions=None):
        self._positions = positions or []

    def get_open_positions(self):
        return self._positions


class FakeSafetyLayer:
    def get_status(self):
        return {"daily_pnl": -50.0, "kill_switch_active": False}


@pytest.mark.asyncio
async def test_assemble_morning_brief_empty_positions():
    """Brief returns non-empty string with empty positions."""
    from notifications.morning_brief import assemble_morning_brief

    result = await assemble_morning_brief(
        data_manager=FakeDataManager(),
        paper_tracker=FakePaperTracker(),
        safety_layer=FakeSafetyLayer(),
    )
    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.asyncio
async def test_morning_brief_shows_avt_na_when_no_bars():
    """With no bars, the report-only AVT indicator degrades to N/A (never raises)."""
    from notifications.morning_brief import assemble_morning_brief

    result = await assemble_morning_brief(
        data_manager=FakeDataManager(),  # get_bars returns None
        paper_tracker=FakePaperTracker(),
        safety_layer=FakeSafetyLayer(),
    )
    assert "AVT: N/A" in result


@pytest.mark.asyncio
async def test_morning_brief_includes_avt_score_with_bars():
    """With real bars, the brief carries an AVT indicator on the instrument lines."""
    import numpy as np

    from notifications.morning_brief import assemble_morning_brief

    n = 240
    close = pd.Series(np.linspace(100, 130, n))
    bars = pd.DataFrame(
        {
            "open": close.shift(1).fillna(close.iloc[0]),
            "high": close * 1.005,
            "low": close * 0.995,
            "close": close,
            "volume": pd.Series([1000.0] * n),
        }
    )

    class DM:
        async def get_current_price(self, symbol):
            return 100.0

        async def get_bars(self, symbol, **kwargs):
            return bars

    result = await assemble_morning_brief(
        data_manager=DM(),
        paper_tracker=FakePaperTracker(),
        safety_layer=FakeSafetyLayer(),
    )
    assert "AVT:" in result
    assert "AVT: N/A" not in result  # real bars -> a real read (long/short/flat)
    # The active instruments (MES/MGC) carry their own report-only AVT read.
    assert "MES: AVT" in result
    assert "MGC: AVT" in result


@pytest.mark.asyncio
async def test_assemble_morning_brief_contains_symbols():
    """Brief contains MCL and MNQ symbol names."""
    from notifications.morning_brief import assemble_morning_brief

    result = await assemble_morning_brief(
        data_manager=FakeDataManager(),
        paper_tracker=FakePaperTracker(),
        safety_layer=FakeSafetyLayer(),
    )
    assert "MCL" in result
    assert "MNQ" in result


@pytest.mark.asyncio
async def test_assemble_morning_brief_no_raise_none_prices():
    """Brief does not raise when data_manager returns None prices."""

    class NullDataManager:
        async def get_current_price(self, symbol):
            return None

        async def get_bars(self, *args, **kwargs):
            return None

    from notifications.morning_brief import assemble_morning_brief

    result = await assemble_morning_brief(
        data_manager=NullDataManager(),
        paper_tracker=FakePaperTracker(),
        safety_layer=FakeSafetyLayer(),
    )
    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.asyncio
async def test_unrealized_pnl_long_mcl():
    """LONG MCL: entry=72.00, current=72.50, qty=1 → +$50.00"""
    from notifications.morning_brief import _compute_unrealized

    position = {
        "symbol": "MCL",
        "action": "buy",
        "quantity": 1,
        "entry_price": 72.00,
    }
    result = _compute_unrealized(position, 72.50)
    assert result == pytest.approx(50.0, abs=0.01)


@pytest.mark.asyncio
async def test_unrealized_pnl_short_mnq():
    """SHORT MNQ: entry=17500, current=17480, qty=1 → +$40.00"""
    from notifications.morning_brief import _compute_unrealized

    position = {
        "symbol": "MNQ",
        "action": "sell",
        "quantity": 1,
        "entry_price": 17500.0,
    }
    result = _compute_unrealized(position, 17480.0)
    assert result == pytest.approx(40.0, abs=0.01)
