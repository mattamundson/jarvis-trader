"""
Tests for StrategyTuner.generate_hypothesis (ResearchAgent integration).

Covers:
  - Returns None when ENABLE_RESEARCH_AGENT is unset (feature-flag gate)
  - Returns a StrategyHypothesis when the flag is set
  - Returns None and logs a warning when ResearchAgent.propose raises
  - Passes a context dict with the expected keys to ResearchAgent.propose
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agents.research_agent import StrategyHypothesis
from learning._experimental.strategy_tuner import StrategyTuner

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_hypothesis(symbol: str = "MES") -> StrategyHypothesis:
    """Return a minimal valid StrategyHypothesis for use in mocks."""
    return StrategyHypothesis(
        name="test-hyp-v1",
        symbol=symbol,
        timeframe="1h",
        entry_rules=["RSI(14) < 30"],
        exit_rules=["Price crosses VWAP"],
        signal_weights={"rsi": 1.0},
        risk_params={"stop_atr_mult": 1.5},
        rationale="Test hypothesis.",
        confidence=0.75,
    )


# ---------------------------------------------------------------------------
# test_generate_hypothesis_disabled
# ---------------------------------------------------------------------------


async def test_generate_hypothesis_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """When ENABLE_RESEARCH_AGENT is not set, generate_hypothesis returns None."""
    monkeypatch.delenv("ENABLE_RESEARCH_AGENT", raising=False)
    tuner = StrategyTuner()
    result = await tuner.generate_hypothesis("MES")
    assert result is None


# ---------------------------------------------------------------------------
# test_generate_hypothesis_enabled_returns_hypothesis
# ---------------------------------------------------------------------------


async def test_generate_hypothesis_enabled_returns_hypothesis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ENABLE_RESEARCH_AGENT=1, a StrategyHypothesis is returned with the correct symbol."""
    monkeypatch.setenv("ENABLE_RESEARCH_AGENT", "1")

    expected = _make_hypothesis("MNQ")
    mock_propose = AsyncMock(return_value=expected)

    with patch("learning._experimental.strategy_tuner.ResearchAgent") as MockAgent:
        MockAgent.return_value.propose = mock_propose
        tuner = StrategyTuner()
        result = await tuner.generate_hypothesis("MNQ")

    assert isinstance(result, StrategyHypothesis)
    assert result.symbol == "MNQ"


# ---------------------------------------------------------------------------
# test_generate_hypothesis_handles_propose_exception
# ---------------------------------------------------------------------------


async def test_generate_hypothesis_handles_propose_exception(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When ResearchAgent.propose raises, generate_hypothesis returns None and logs a warning."""
    monkeypatch.setenv("ENABLE_RESEARCH_AGENT", "1")

    mock_propose = AsyncMock(side_effect=RuntimeError("LLM unavailable"))

    with patch("learning._experimental.strategy_tuner.ResearchAgent") as MockAgent:
        MockAgent.return_value.propose = mock_propose
        tuner = StrategyTuner()

        import logging

        with caplog.at_level(logging.WARNING, logger="learning._experimental.strategy_tuner"):
            result = await tuner.generate_hypothesis("MCL")

    assert result is None
    assert any("hypothesis generation failed" in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# test_generate_hypothesis_passes_context
# ---------------------------------------------------------------------------


async def test_generate_hypothesis_passes_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The context dict passed to ResearchAgent.propose has the expected keys."""
    monkeypatch.setenv("ENABLE_RESEARCH_AGENT", "1")

    recent_trades = [{"won": True, "pnl": 100, "risk": 50}] * 5
    current_params = {"STC_OS": 15, "STOP_ATR": 0.7}

    expected = _make_hypothesis("MES")
    mock_propose = AsyncMock(return_value=expected)

    with patch("learning._experimental.strategy_tuner.ResearchAgent") as MockAgent:
        MockAgent.return_value.propose = mock_propose
        tuner = StrategyTuner()
        await tuner.generate_hypothesis(
            "MES", recent_trades=recent_trades, current_params=current_params
        )

    mock_propose.assert_awaited_once()
    _symbol_arg, kwargs = mock_propose.call_args.args[0], mock_propose.call_args.kwargs
    context = kwargs.get(
        "context", mock_propose.call_args.args[1] if len(mock_propose.call_args.args) > 1 else None
    )

    assert context is not None, "context kwarg must be passed to propose"
    assert "recent_trades" in context
    assert "current_params" in context
    assert "suggestions" in context
    assert "symbol" in context
    assert context["symbol"] == "MES"
