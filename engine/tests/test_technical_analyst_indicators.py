"""
Tests for TechnicalAnalystAgent indicator computation and the to_thread offload path.

Two concerns:
  (a) _compute_indicators runs correctly off-thread: synthetic OHLCV data produces
      non-None ATR and rv_20_ann_pct in the returned indicators dict.
  (b) If _compute_indicators raises inside asyncio.to_thread, the analyze() caller
      degrades gracefully: returns an empty/safe TechnicalReport, does NOT propagate
      the exception or crash the pipeline. (Guards the try/except added at
      technical_analyst.py:182 — previously this offload path was unguarded.)

No LLM, no broker I/O — llm_client and data_manager are mocked throughout.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest

engine_root = Path(__file__).parent.parent
if str(engine_root) not in sys.path:
    sys.path.insert(0, str(engine_root))

from agents.technical_analyst import TechnicalAnalystAgent, TechnicalReport  # noqa: E402

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _make_synthetic_ohlcv(n: int = 60, base_price: float = 5800.0) -> pd.DataFrame:
    """
    Produce a minimal synthetic OHLCV DataFrame with a DatetimeIndex.
    60 rows (> _MIN_INTRADAY_BARS=50) so pandas_ta has enough warmup for ATR.
    """
    rng = np.random.default_rng(42)
    close = base_price + np.cumsum(rng.normal(0, 2, n))
    high = close + rng.uniform(0.5, 3.0, n)
    low = close - rng.uniform(0.5, 3.0, n)
    open_ = close + rng.normal(0, 1, n)
    volume = rng.integers(1000, 5000, n).astype(float)
    idx = pd.date_range("2026-01-01 09:30", periods=n, freq="15min", tz="America/New_York")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )


def _make_agent(llm_client=None, data_manager=None):
    """Build a TechnicalAnalystAgent with throwaway mocks."""
    llm = llm_client or MagicMock()
    data = data_manager or MagicMock()
    return TechnicalAnalystAgent(llm, data)


# ---------------------------------------------------------------------------
# (a) _compute_indicators: synthetic OHLCV -> non-None ATR + rv_20_ann_pct
# ---------------------------------------------------------------------------

class TestComputeIndicatorsBasic:
    """Direct unit-level tests for _compute_indicators (the to_thread payload)."""

    def test_returns_non_none_atr(self):
        """ATR(14) must be computable from 60-bar OHLCV data."""
        agent = _make_agent()
        df = _make_synthetic_ohlcv(60)
        result = agent._compute_indicators(df)
        assert isinstance(result, dict), "_compute_indicators must return a dict"
        assert result.get("atr") is not None, "atr must be non-None for 60-bar OHLCV"
        assert float(result["atr"]) > 0.0, "atr must be positive"

    def test_atr_has_plausible_magnitude(self):
        """ATR should be a fraction of the price, not wildly out of range."""
        agent = _make_agent()
        df = _make_synthetic_ohlcv(60, base_price=5800.0)
        result = agent._compute_indicators(df)
        atr = result.get("atr", 0.0)
        assert 0.1 < atr < 200.0, f"ATR={atr} is implausible for synthetic MES-like data"

    def test_current_price_set_from_last_close(self):
        df = _make_synthetic_ohlcv(60)
        agent = _make_agent()
        result = agent._compute_indicators(df)
        expected = float(df["close"].iloc[-1])
        assert result.get("current_price") == pytest.approx(expected, rel=1e-6)

    def test_support_and_resistance_populated(self):
        df = _make_synthetic_ohlcv(60)
        agent = _make_agent()
        result = agent._compute_indicators(df)
        assert isinstance(result.get("support_levels"), list)
        assert isinstance(result.get("resistance_levels"), list)
        assert len(result["support_levels"]) > 0
        assert len(result["resistance_levels"]) > 0


class TestRv20AnnPct:
    """
    rv_20_ann_pct is computed AFTER _compute_indicators returns in analyze(),
    so we test it via the analyze() path with a mocked LLM and data_manager.
    """

    def _make_llm_returning_valid_report(self):
        """Return a minimal LLM mock that emits a valid JSON technical analysis."""
        llm = MagicMock()
        llm_result = MagicMock()
        llm_result.success = True
        llm_result.content = """{
            "signal": 0.1,
            "confidence": 0.5,
            "trend": "neutral",
            "regime": "trending",
            "trend_score": 0.1,
            "momentum_score": 0.0,
            "volatility_score": 0.2,
            "volume_score": 0.1,
            "is_overbought": false,
            "is_oversold": false,
            "summary": "Test summary",
            "reasoning": "Test reasoning",
            "mtf_alignment": "insufficient MTF data",
            "regime_readiness": "CAUTION"
        }"""
        llm.call = AsyncMock(return_value=llm_result)
        return llm

    def _make_data_manager_with_bars(self, df: pd.DataFrame):
        """Return a data_manager mock that provides the given bars and a real price."""
        dm = MagicMock()
        dm.get_bars = AsyncMock(return_value=df)
        price_val = float(df["close"].iloc[-1])
        dm.get_current_price = AsyncMock(return_value={"last_price": price_val, "source": "mock"})
        return dm

    def test_rv_20_ann_pct_is_non_none_for_sufficient_bars(self):
        """
        For >= 22 bars (non-daily-fallback) rv_20_ann_pct must be a float, not None.
        This exercises the asyncio.to_thread path indirectly: analyze() calls
        _compute_indicators in the thread, then computes rv on the main thread.

        TradingViewFeed is imported locally inside analyze() so we patch via the
        data.tradingview_feed module path instead.
        """
        df = _make_synthetic_ohlcv(60)
        llm = self._make_llm_returning_valid_report()
        dm = self._make_data_manager_with_bars(df)
        agent = _make_agent(llm, dm)

        # TradingViewFeed is lazy-imported as `from data.tradingview_feed import TradingViewFeed`
        # inside the try-block in analyze(). Patch the module so the import succeeds but
        # .get_all_indicators() returns {} (simulating TV not running).
        tv_mock = MagicMock()
        tv_mock.return_value.get_all_indicators.return_value = {}
        with patch.dict("sys.modules", {"data.tradingview_feed": MagicMock(TradingViewFeed=tv_mock)}):
            report = asyncio.run(
                agent.analyze("MES", timeframe="15m", is_futures=True)
            )

        rv = report.indicators.get("rv_20_ann_pct")
        assert rv is not None, "rv_20_ann_pct must be non-None for 60-bar intraday data"
        assert isinstance(rv, float)
        assert rv > 0.0, "annualised realized vol must be positive"


# ---------------------------------------------------------------------------
# (b) _compute_indicators raises -> analyze() degrades gracefully (empty report)
# ---------------------------------------------------------------------------

class TestComputeIndicatorsErrorDegradation:
    """
    When asyncio.to_thread(_compute_indicators, df) raises, the top-level
    analyze() method must:
      - NOT re-raise
      - Return a TechnicalReport that is 'empty/safe' (signal=0, confidence=0)
    """

    def _make_llm(self):
        llm = MagicMock()
        llm.call = AsyncMock(side_effect=RuntimeError("LLM should not be called"))
        return llm

    def _make_data_manager_with_bars(self, df: pd.DataFrame):
        dm = MagicMock()
        dm.get_bars = AsyncMock(return_value=df)
        price_val = float(df["close"].iloc[-1])
        dm.get_current_price = AsyncMock(return_value={"last_price": price_val, "source": "mock"})
        return dm

    def test_exception_in_compute_indicators_degrades_gracefully(self):
        """
        REGRESSION GUARD: a crash inside _compute_indicators (run via
        asyncio.to_thread at agents/technical_analyst.py:182) must NOT propagate
        out of analyze(). The offload is wrapped in try/except Exception that
        degrades to self._empty_report(symbol, timeframe) — same contract as the
        daily-fallback path above it.

        Previously this path was unguarded and the exception crashed the pipeline
        caller; the fix makes the failure mode an empty/safe report instead.
        The LLM must never be reached on this path.
        """
        df = _make_synthetic_ohlcv(60)
        llm = self._make_llm()  # llm.call raises if invoked
        dm = self._make_data_manager_with_bars(df)
        agent = _make_agent(llm, dm)

        with patch.object(
            agent,
            "_compute_indicators",
            side_effect=RuntimeError("simulated indicator crash"),
        ):
            try:
                report = asyncio.run(
                    agent.analyze("MES", timeframe="15m", is_futures=True)
                )
            except Exception as exc:  # noqa: BLE001
                pytest.fail(
                    "analyze() must degrade gracefully when _compute_indicators "
                    f"raises, but it propagated: {exc!r}"
                )

        assert isinstance(report, TechnicalReport)
        assert report.signal == pytest.approx(0.0)
        assert report.confidence == pytest.approx(0.0)
        # LLM must not have been consulted on the degraded path.
        llm.call.assert_not_called()

    def test_empty_data_manager_returns_safe_report(self):
        """
        When data_manager returns an empty DataFrame for both intraday and daily
        fallback, analyze() must return a safe report — not crash.
        This also covers the to_thread path being skipped entirely.
        """
        llm = self._make_llm()
        dm = MagicMock()
        dm.get_bars = AsyncMock(return_value=pd.DataFrame())
        dm.get_current_price = AsyncMock(return_value={"last_price": 0.0, "source": "mock"})
        agent = _make_agent(llm, dm)

        try:
            report = asyncio.run(
                agent.analyze("MES", timeframe="15m", is_futures=True)
            )
        except Exception as exc:
            pytest.fail(f"analyze() must handle empty data gracefully, but raised: {exc}")

        assert isinstance(report, TechnicalReport)
        assert report.signal == pytest.approx(0.0)
        assert report.confidence == pytest.approx(0.0)
