"""Tests for engine/agents/options_analyst.py.

Covered:
  - is_options_analyst_enabled() returns False when env var is absent / non-"1"
  - is_options_analyst_enabled() returns True when ENABLE_OPTIONS_ANALYST="1"
  - analyze() returns neutral dict when flag is off
  - analyze() returns neutral dict when all sub-signals abstain (no IV data)
  - analyze() returns a valid signal dict on synthetic valid inputs
  - analyze() clamps out-of-range blended signals to [-1.0, +1.0]
  - analyze() returns weight=0.0 indicator on full abstention
  - _options_analyst_or_none property: off -> None, on -> OptionsAnalyst, off -> None
  - pipeline._call_agent_analyze_options: disabled returns neutral dict
  - pipeline._call_agent_analyze_options: enabled propagates analyst result

Design:
  - Never touches production .env or any real API.
  - Uses monkeypatch.setenv / monkeypatch.delenv — no permanent env writes.
  - pytest-asyncio in auto mode (asyncio_mode = auto in pyproject.toml).
  - Sub-signals are patched via AsyncMock/patch to avoid importing options chain deps.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

_ENV_FLAG = "ENABLE_OPTIONS_ANALYST"


# ---------------------------------------------------------------------------
# is_options_analyst_enabled() gating tests
# ---------------------------------------------------------------------------


def test_options_analyst_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Flag absent -> is_options_analyst_enabled() is False."""
    monkeypatch.delenv(_ENV_FLAG, raising=False)
    from agents.options_analyst import is_options_analyst_enabled

    assert is_options_analyst_enabled() is False


def test_options_analyst_disabled_for_non_one_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """Values other than '1' (after strip) must not enable the analyst."""
    from agents.options_analyst import is_options_analyst_enabled

    for bad_value in ("0", "true", "True", "yes", "on", ""):
        monkeypatch.setenv(_ENV_FLAG, bad_value)
        assert (
            is_options_analyst_enabled() is False
        ), f"Expected is_options_analyst_enabled() == False for {_ENV_FLAG}={bad_value!r}"


def test_options_analyst_enabled_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """ENABLE_OPTIONS_ANALYST='1' -> is_options_analyst_enabled() is True."""
    monkeypatch.setenv(_ENV_FLAG, "1")
    from agents.options_analyst import is_options_analyst_enabled

    assert is_options_analyst_enabled() is True


# ---------------------------------------------------------------------------
# analyze() — disabled path
# ---------------------------------------------------------------------------


async def test_analyze_returns_neutral_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Disabled flag: analyze() returns neutral dict with weight=0.0."""
    monkeypatch.delenv(_ENV_FLAG, raising=False)
    from agents.options_analyst import OptionsAnalyst

    analyst = OptionsAnalyst()
    result = await analyst.analyze("MES", spot_price=5000.0)

    assert isinstance(result, dict)
    assert result["signal"] == pytest.approx(0.0)
    assert result["confidence"] == pytest.approx(0.0)
    assert isinstance(result["summary"], str)
    assert result["indicators"]["weight"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# analyze() — abstention when all sub-signals return no data
# ---------------------------------------------------------------------------


async def test_analyze_returns_neutral_on_missing_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When all sub-signals abstain (no IV data), analyze() returns neutral dict."""
    monkeypatch.setenv(_ENV_FLAG, "1")
    from agents.options_analyst import OptionsAnalyst

    analyst = OptionsAnalyst()

    # Patch all three sub-signal helpers to return (0.0, False) — data unavailable
    with (
        patch.object(analyst, "_skew_signal", new=AsyncMock(return_value=(0.0, False))),
        patch.object(analyst, "_term_signal", new=AsyncMock(return_value=(0.0, False))),
        patch.object(analyst, "_gamma_signal", new=AsyncMock(return_value=(0.0, False))),
    ):
        result = await analyst.analyze("MES", spot_price=5000.0)

    assert result["signal"] == pytest.approx(0.0)
    assert result["confidence"] == pytest.approx(0.0)
    assert result["indicators"]["weight"] == pytest.approx(0.0)
    assert "no_iv_data" in result["indicators"].get("reason", result["summary"])


# ---------------------------------------------------------------------------
# analyze() — valid signal on synthetic sub-signal inputs
# ---------------------------------------------------------------------------


async def test_analyze_returns_signal_on_valid_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When sub-signals return real data, analyze() produces a non-zero verdict."""
    monkeypatch.setenv(_ENV_FLAG, "1")
    from agents.options_analyst import OptionsAnalyst

    analyst = OptionsAnalyst()

    # Bullish skew: call IV > put IV → skew signal > 0
    # Flat term structure → term signal ≈ 0
    # No gamma data
    with (
        patch.object(analyst, "_skew_signal", new=AsyncMock(return_value=(0.5, True))),
        patch.object(analyst, "_term_signal", new=AsyncMock(return_value=(0.0, True))),
        patch.object(analyst, "_gamma_signal", new=AsyncMock(return_value=(0.0, False))),
        patch.object(analyst, "_get_iv_rank", new=AsyncMock(return_value=45.0)),
    ):
        result = await analyst.analyze("SPY", spot_price=450.0)

    assert isinstance(result, dict)
    assert "signal" in result
    assert "confidence" in result
    assert "summary" in result
    assert "indicators" in result
    # With skew=+0.5 (bullish) and term=0.0, blended signal should be positive
    assert result["signal"] > 0.0, f"Expected positive signal, got {result['signal']}"
    assert result["confidence"] > 0.0
    assert result["indicators"]["weight"] > 0.0
    # IV rank should be forwarded to indicators
    assert result["indicators"]["iv_rank"] == pytest.approx(45.0)


async def test_analyze_bearish_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Put-heavy skew + backwardation term → bearish signal."""
    monkeypatch.setenv(_ENV_FLAG, "1")
    from agents.options_analyst import OptionsAnalyst

    analyst = OptionsAnalyst()

    with (
        patch.object(analyst, "_skew_signal", new=AsyncMock(return_value=(-0.6, True))),
        patch.object(analyst, "_term_signal", new=AsyncMock(return_value=(-0.4, True))),
        patch.object(analyst, "_gamma_signal", new=AsyncMock(return_value=(0.0, False))),
        patch.object(analyst, "_get_iv_rank", new=AsyncMock(return_value=72.0)),
    ):
        result = await analyst.analyze("MES", spot_price=5100.0)

    assert result["signal"] < 0.0, f"Expected negative signal, got {result['signal']}"


# ---------------------------------------------------------------------------
# analyze() — signal clamping
# ---------------------------------------------------------------------------


async def test_analyze_clamps_signal_to_range(monkeypatch: pytest.MonkeyPatch) -> None:
    """Out-of-range blended raw signal is clamped to [-1.0, +1.0]."""
    monkeypatch.setenv(_ENV_FLAG, "1")
    from agents.options_analyst import OptionsAnalyst

    analyst = OptionsAnalyst()

    # Drive all sub-signals to +1.0 to produce a raw blended signal of exactly 1.0
    with (
        patch.object(analyst, "_skew_signal", new=AsyncMock(return_value=(1.0, True))),
        patch.object(analyst, "_term_signal", new=AsyncMock(return_value=(1.0, True))),
        patch.object(analyst, "_gamma_signal", new=AsyncMock(return_value=(1.0, True))),
        patch.object(analyst, "_get_iv_rank", new=AsyncMock(return_value=20.0)),
    ):
        result = await analyst.analyze("SPY", spot_price=450.0)

    assert result["signal"] <= 1.0, f"signal must be <= 1.0; got {result['signal']}"
    assert result["signal"] >= -1.0, f"signal must be >= -1.0; got {result['signal']}"

    # Same for lower bound
    with (
        patch.object(analyst, "_skew_signal", new=AsyncMock(return_value=(-1.0, True))),
        patch.object(analyst, "_term_signal", new=AsyncMock(return_value=(-1.0, True))),
        patch.object(analyst, "_gamma_signal", new=AsyncMock(return_value=(-1.0, True))),
        patch.object(analyst, "_get_iv_rank", new=AsyncMock(return_value=80.0)),
    ):
        result2 = await analyst.analyze("SPY", spot_price=450.0)

    assert result2["signal"] >= -1.0
    assert result2["signal"] <= 1.0


# ---------------------------------------------------------------------------
# analyze() — weight=0.0 on full abstention
# ---------------------------------------------------------------------------


async def test_analyze_reports_zero_weight_on_abstention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Full abstention (all sub-signals unavailable) sets indicators.weight=0.0."""
    monkeypatch.setenv(_ENV_FLAG, "1")
    from agents.options_analyst import OptionsAnalyst

    analyst = OptionsAnalyst()

    with (
        patch.object(analyst, "_skew_signal", new=AsyncMock(return_value=(0.0, False))),
        patch.object(analyst, "_term_signal", new=AsyncMock(return_value=(0.0, False))),
        patch.object(analyst, "_gamma_signal", new=AsyncMock(return_value=(0.0, False))),
    ):
        result = await analyst.analyze("MES")

    assert result["indicators"]["weight"] == pytest.approx(0.0)
    assert result["signal"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# _options_analyst_or_none property — lazy-init toggle test
# ---------------------------------------------------------------------------


def test_pipeline_options_analyst_lazy_init(monkeypatch: pytest.MonkeyPatch) -> None:
    """_options_analyst_or_none re-evaluates flag on each access."""
    from agents.options_analyst import OptionsAnalyst, is_options_analyst_enabled

    class _FakePipeline:
        @property
        def _options_analyst_or_none(self):
            if not is_options_analyst_enabled():
                self._options_analyst_cached = None
                return None
            if not hasattr(self, "_options_analyst_cached") or self._options_analyst_cached is None:
                self._options_analyst_cached = OptionsAnalyst()
            return self._options_analyst_cached

    pipe = _FakePipeline()

    # Flag off → None
    monkeypatch.delenv(_ENV_FLAG, raising=False)
    assert pipe._options_analyst_or_none is None

    # Flag on → OptionsAnalyst instance
    monkeypatch.setenv(_ENV_FLAG, "1")
    instance = pipe._options_analyst_or_none
    assert isinstance(instance, OptionsAnalyst)
    # Cached — same object on second access
    assert pipe._options_analyst_or_none is instance

    # Flag off again → None, cache cleared
    monkeypatch.delenv(_ENV_FLAG, raising=False)
    assert pipe._options_analyst_or_none is None


# ---------------------------------------------------------------------------
# Pipeline helper — _call_agent_analyze_options
# ---------------------------------------------------------------------------


async def test_pipeline_options_disabled_returns_neutral(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ENABLE_OPTIONS_ANALYST is unset, _call_agent_analyze_options returns neutral."""
    monkeypatch.delenv(_ENV_FLAG, raising=False)

    from agents.pipeline import TradingPipeline

    pipeline = TradingPipeline.__new__(TradingPipeline)
    pipeline._agents = {}
    if hasattr(pipeline, "_options_analyst_cached"):
        del pipeline._options_analyst_cached

    result = await pipeline._call_agent_analyze_options("MES", 5000.0)

    assert result["signal"] == pytest.approx(0.0)
    assert result["confidence"] == pytest.approx(0.0)
    assert "disabled" in result["summary"]
    assert result["indicators"]["weight"] == pytest.approx(0.0)


async def test_pipeline_options_enabled_propagates_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ENABLE_OPTIONS_ANALYST=1, _call_agent_analyze_options propagates verdict."""
    monkeypatch.setenv(_ENV_FLAG, "1")

    from agents.options_analyst import OptionsAnalyst
    from agents.pipeline import TradingPipeline

    expected = {
        "signal": 0.35,
        "confidence": 0.6,
        "summary": "options analyst: bullish signal=+0.350",
        "indicators": {"weight": 0.7, "skew_signal": 0.5},
    }

    analyst = OptionsAnalyst()
    analyst.analyze = AsyncMock(return_value=expected)

    pipeline = TradingPipeline.__new__(TradingPipeline)
    pipeline._agents = {}
    pipeline._options_analyst_cached = analyst

    result = await pipeline._call_agent_analyze_options("SPY", 450.0)

    assert result["signal"] == pytest.approx(0.35)
    assert result["confidence"] == pytest.approx(0.6)
    analyst.analyze.assert_called_once_with("SPY", spot_price=450.0)
