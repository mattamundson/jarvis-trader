"""
US-007 — Coverage tests for BreakoutAgent + HarmonicAgent.

Findings during scoping:
  1. BreakoutAgent: NOT orphan — wired at pipeline.py:1379-1401 in _run_analysts.
  2. HarmonicAgent: NOT orphan — same wiring as breakout.
  3. RegimeGuard: was orphan + structurally broken (JesseIndicators.adx missing,
     atr wrong signature). Deleted in US-012.
"""

import os
import sys
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.breakout_agent import BreakoutAgent, BreakoutReport  # noqa: E402
from agents.harmonic_agent import HarmonicAgent, HarmonicReport  # noqa: E402


def _ohlcv(rows: int) -> pd.DataFrame:
    """Synthetic OHLCV DataFrame with `rows` bars."""
    rng = np.random.default_rng(42)
    base = 5800.0
    closes = base + rng.standard_normal(rows).cumsum()
    return pd.DataFrame(
        {
            "open": closes - 0.5,
            "high": closes + 1.0,
            "low": closes - 1.0,
            "close": closes,
            "volume": rng.integers(1000, 10000, rows),
        }
    )


# ─────────────────────────────────────────────────────────────────────────────
# BreakoutAgent
# ─────────────────────────────────────────────────────────────────────────────


class TestBreakoutAgent:
    @pytest.mark.asyncio
    async def test_empty_dataframe_returns_empty_report(self):
        dm = MagicMock()
        dm.get_bars = AsyncMock(return_value=pd.DataFrame())
        agent = BreakoutAgent(dm)
        result = await agent.analyze("MES", is_futures=True)
        assert isinstance(result, BreakoutReport)
        assert result.status == "none"
        assert result.signal == 0

    @pytest.mark.asyncio
    async def test_short_history_returns_empty_report(self):
        dm = MagicMock()
        dm.get_bars = AsyncMock(return_value=_ohlcv(20))  # < 50 bars
        agent = BreakoutAgent(dm)
        result = await agent.analyze("MES", is_futures=True)
        assert result.status == "none"

    @pytest.mark.asyncio
    async def test_breakout_status_yields_signed_signal(self):
        dm = MagicMock()
        dm.get_bars = AsyncMock(return_value=_ohlcv(100))
        agent = BreakoutAgent(dm)
        # Mock the engine to force a breakout detection
        agent._engine = MagicMock()
        agent._engine.calculate_profile.return_value = {
            "vah": 5810.0, "val": 5790.0, "poc": 5800.0, "va_volume_pct": 0.7,
        }
        agent._engine.detect_breakout.return_value = {"status": "breakout", "side": "bullish"}
        result = await agent.analyze("MES", is_futures=True)
        assert result.status == "breakout"
        assert result.signal == 0.8
        assert result.confidence == 0.75

    @pytest.mark.asyncio
    async def test_bearish_breakout_negative_signal(self):
        dm = MagicMock()
        dm.get_bars = AsyncMock(return_value=_ohlcv(100))
        agent = BreakoutAgent(dm)
        agent._engine = MagicMock()
        agent._engine.calculate_profile.return_value = {
            "vah": 5810.0, "val": 5790.0, "poc": 5800.0, "va_volume_pct": 0.7,
        }
        agent._engine.detect_breakout.return_value = {"status": "breakout", "side": "bearish"}
        result = await agent.analyze("MES", is_futures=True)
        assert result.signal == -0.8

    @pytest.mark.asyncio
    async def test_extended_status_half_signal(self):
        dm = MagicMock()
        dm.get_bars = AsyncMock(return_value=_ohlcv(100))
        agent = BreakoutAgent(dm)
        agent._engine = MagicMock()
        agent._engine.calculate_profile.return_value = {
            "vah": 5810.0, "val": 5790.0, "poc": 5800.0, "va_volume_pct": 0.7,
        }
        agent._engine.detect_breakout.return_value = {"status": "extended", "side": "bullish"}
        result = await agent.analyze("MES", is_futures=True)
        assert result.signal == 0.4
        assert result.confidence == 0.5

    @pytest.mark.asyncio
    async def test_inside_va_zero_signal(self):
        dm = MagicMock()
        dm.get_bars = AsyncMock(return_value=_ohlcv(100))
        agent = BreakoutAgent(dm)
        agent._engine = MagicMock()
        agent._engine.calculate_profile.return_value = {
            "vah": 5810.0, "val": 5790.0, "poc": 5800.0, "va_volume_pct": 0.7,
        }
        agent._engine.detect_breakout.return_value = {"status": "inside_va", "side": "neutral"}
        result = await agent.analyze("MES", is_futures=True)
        assert result.signal == 0.0
        assert result.confidence == 0.3

    def test_breakout_report_to_dict_has_required_fields(self):
        report = BreakoutReport(
            symbol="MES", timestamp=datetime.now(), status="breakout", side="bullish",
            vah=5810.0, val=5790.0, poc=5800.0, signal=0.8, confidence=0.75,
            summary="up", reasoning="momentum",
        )
        d = report.to_dict()
        for key in ("symbol", "timestamp", "status", "side", "vah", "val", "poc", "signal", "confidence"):
            assert key in d
        assert d["signal"] == 0.8


# ─────────────────────────────────────────────────────────────────────────────
# HarmonicAgent
# ─────────────────────────────────────────────────────────────────────────────


class TestHarmonicAgent:
    @pytest.mark.asyncio
    async def test_empty_dataframe_returns_empty_report(self):
        dm = MagicMock()
        dm.get_bars = AsyncMock(return_value=pd.DataFrame())
        agent = HarmonicAgent(dm)
        result = await agent.analyze("MES", is_futures=True)
        assert isinstance(result, HarmonicReport)
        assert result.signal == 0
        assert result.patterns == []

    @pytest.mark.asyncio
    async def test_short_history_returns_empty_report(self):
        dm = MagicMock()
        dm.get_bars = AsyncMock(return_value=_ohlcv(50))  # < 100 bars
        agent = HarmonicAgent(dm)
        result = await agent.analyze("MES", is_futures=True)
        assert result.signal == 0

    @pytest.mark.asyncio
    async def test_no_patterns_returns_empty_report(self):
        dm = MagicMock()
        dm.get_bars = AsyncMock(return_value=_ohlcv(150))
        agent = HarmonicAgent(dm)
        agent._engine = MagicMock()
        agent._engine.detect_patterns.return_value = []
        result = await agent.analyze("MES", is_futures=True)
        assert result.patterns == []

    def test_harmonic_report_to_dict_has_required_fields(self):
        report = HarmonicReport(
            symbol="MES", timestamp=datetime.now(),
            patterns=[{"name": "Gartley", "type": "bullish", "age_bars": 2}],
            signal=0.7, confidence=0.65, summary="bullish gartley", reasoning="XD/XA=0.786",
        )
        d = report.to_dict()
        assert d["signal"] == 0.7
        assert d["patterns"][0]["name"] == "Gartley"


