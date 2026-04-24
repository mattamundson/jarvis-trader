"""
US-007 — Coverage tests for the three "orphan agents" identified during the
top-10 ROI roadmap audit.

Findings during scoping (recorded here for the commit triage in US-009):

  1. BreakoutAgent: NOT orphan — wired into TradingPipeline at
     pipeline.py:1379-1401 as part of `_run_analysts`. Just untested.
  2. HarmonicAgent: NOT orphan — same wiring as breakout.
  3. RegimeGuard: TRULY orphan AND structurally broken.
     - Instantiated at main.py:465 + sdk_pipeline.py:342
     - `classify_regime` and `is_strategy_safe` never invoked anywhere
     - `classify_regime` calls `self.indicators.adx(df)` but JesseIndicators
       has no `adx` method → AttributeError on first call.
     - `classify_regime` also calls `self.indicators.atr(df)` but the real
       signature is `atr(high, low, close, period=14)` (three arrays).

This file:
  * Adds behavioral tests for BreakoutAgent + HarmonicAgent.
  * Reproduces the RegimeGuard bugs so the broken state is visible in CI
    and can drive a deletion decision in US-009 commit triage.
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
from agents.regime_guard import RegimeGuard  # noqa: E402


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


# ─────────────────────────────────────────────────────────────────────────────
# RegimeGuard — broken-state regression tests
# ─────────────────────────────────────────────────────────────────────────────


class TestRegimeGuardBrokenState:
    """
    These tests document the broken state of RegimeGuard so the failure is
    visible in CI rather than only at runtime when (if) it gets wired.
    """

    def test_classify_regime_short_history_returns_unknown_safely(self):
        """Short-history early-return path (line 26-27) works without touching indicators."""
        guard = RegimeGuard()
        df = _ohlcv(20)  # < 30 → early return
        assert guard.classify_regime(df) == "unknown"
        assert guard.current_regime == "unknown"

    def test_classify_regime_with_full_history_crashes_due_to_missing_adx(self):
        """
        AttributeError documented: JesseIndicators has no `adx` method.
        If this test ever PASSES (i.e., does NOT raise), it means someone added
        `JesseIndicators.adx` and RegimeGuard might be safe to wire — re-evaluate.
        """
        guard = RegimeGuard()
        df = _ohlcv(100)
        with pytest.raises((AttributeError, TypeError)):
            guard.classify_regime(df)

    def test_is_strategy_safe_pure_function_works(self):
        """is_strategy_safe is the only working method — pure boolean policy."""
        guard = RegimeGuard()
        assert guard.is_strategy_safe("mm", "ranging") is True
        assert guard.is_strategy_safe("mm", "trending") is False
        assert guard.is_strategy_safe("trend", "trending") is True
        assert guard.is_strategy_safe("trend", "ranging") is False
        # Unknown strategy types default to True (permissive)
        assert guard.is_strategy_safe("scalp", "ranging") is True
        assert guard.is_strategy_safe("anything", "volatile") is True

    def test_default_current_regime_is_unknown(self):
        guard = RegimeGuard()
        assert guard.current_regime == "unknown"
