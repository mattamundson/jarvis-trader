"""Tests for engine/agents/kronos_classifier.py.

Covered:
  - is_kronos_enabled() returns False when env var is absent / non-"1"
  - is_kronos_enabled() returns True when ENABLE_KRONOS="1"
  - classify([]) returns neutral VisionClassification when flag is off
  - classify([]) returns neutral VisionClassification when flag is on (stub)
  - classify_to_verdict([]) direction field is "neutral" for zero signal
  - KronosVerdict.to_vision_classification() preserves signal/confidence

Design:
  - Never touches production .env or any real API.
  - Uses monkeypatch.setenv / monkeypatch.delenv — no permanent env writes.
  - pytest-asyncio in auto mode (asyncio_mode = auto in pyproject.toml).
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ENV_FLAG = "ENABLE_KRONOS"


# ---------------------------------------------------------------------------
# is_kronos_enabled() gating tests
# ---------------------------------------------------------------------------


def test_kronos_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Flag absent -> is_kronos_enabled() is False."""
    monkeypatch.delenv(_ENV_FLAG, raising=False)

    from agents.kronos_classifier import is_kronos_enabled

    assert is_kronos_enabled() is False


def test_kronos_disabled_for_non_one_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """Values other than the exact string '1' must not enable Kronos."""
    from agents.kronos_classifier import is_kronos_enabled

    for bad_value in ("0", "true", "True", "yes", "on", "1 ", " 1", ""):
        monkeypatch.setenv(_ENV_FLAG, bad_value)
        assert (
            is_kronos_enabled() is False
        ), f"Expected is_kronos_enabled() == False for ENABLE_KRONOS={bad_value!r}"


def test_kronos_enabled_when_flag_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """ENABLE_KRONOS='1' -> is_kronos_enabled() is True."""
    monkeypatch.setenv(_ENV_FLAG, "1")

    from agents.kronos_classifier import is_kronos_enabled

    assert is_kronos_enabled() is True


# ---------------------------------------------------------------------------
# classify() interface tests
# ---------------------------------------------------------------------------


async def test_classify_returns_neutral_stub_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When flag is off, classify([]) returns a neutral VisionClassification."""
    monkeypatch.delenv(_ENV_FLAG, raising=False)

    from agents.kronos_classifier import KronosClassifier
    from agents.pattern_vision_analyst import VisionClassification

    clf = KronosClassifier()
    result = await clf.classify([])

    assert isinstance(result, VisionClassification)
    assert result.signal == 0.0
    assert result.confidence == 0.0
    assert result.pattern_type == "no_clear_pattern"
    # Reasoning string must mention "disabled" or "not set" so callers can tell
    # this is an intentional abstention, not a model output.
    assert (
        "disabled" in result.reasoning.lower() or "not set" in result.reasoning.lower()
    ), f"Expected disabled-related message in reasoning; got: {result.reasoning!r}"


async def test_classify_returns_neutral_stub_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When flag is on (stub mode), classify([]) returns neutral VisionClassification."""
    monkeypatch.setenv(_ENV_FLAG, "1")

    from agents.kronos_classifier import KronosClassifier
    from agents.pattern_vision_analyst import VisionClassification

    clf = KronosClassifier()
    result = await clf.classify([])

    assert isinstance(result, VisionClassification)
    assert result.signal == 0.0
    assert result.confidence == 0.0
    assert result.pattern_type == "no_clear_pattern"
    # Reasoning string must mention "stub" so debate stack can detect un-wired model.
    assert (
        "stub" in result.reasoning.lower()
    ), f"Expected 'stub' in reasoning; got: {result.reasoning!r}"


async def test_classify_returns_neutral_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    """Primary contract test: neutral + low confidence + sensible reasoning string."""
    monkeypatch.delenv(_ENV_FLAG, raising=False)

    from agents.kronos_classifier import KronosClassifier

    clf = KronosClassifier()
    result = await clf.classify([])

    # Signal neutral
    assert result.signal == 0.0, f"Expected signal=0.0, got {result.signal}"
    # Low confidence (must be 0.0 for stub — contributes zero weight to debate)
    assert result.confidence == 0.0, f"Expected confidence=0.0, got {result.confidence}"
    # Reasoning is a non-empty string — debate stack logs it
    assert (
        isinstance(result.reasoning, str) and len(result.reasoning) > 0
    ), "reasoning must be a non-empty string"


# ---------------------------------------------------------------------------
# classify_to_verdict() direction field
# ---------------------------------------------------------------------------


async def test_classify_to_verdict_direction_neutral(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """classify_to_verdict([]) -> KronosVerdict with direction='neutral'."""
    monkeypatch.delenv(_ENV_FLAG, raising=False)

    from agents.kronos_classifier import KronosClassifier, KronosVerdict

    clf = KronosClassifier()
    verdict = await clf.classify_to_verdict([])

    assert isinstance(verdict, KronosVerdict)
    assert verdict.direction == "neutral"
    assert verdict.signal == 0.0
    assert verdict.confidence == 0.0


# ---------------------------------------------------------------------------
# KronosVerdict.to_vision_classification() round-trip
# ---------------------------------------------------------------------------


def test_kronos_verdict_to_vision_classification() -> None:
    """KronosVerdict.to_vision_classification() preserves signal and confidence."""
    from agents.kronos_classifier import KronosVerdict

    verdict = KronosVerdict(
        signal=0.42,
        confidence=0.75,
        direction="bullish",
        reasoning="test round-trip",
    )
    vc = verdict.to_vision_classification()

    assert vc.signal == pytest.approx(0.42)
    assert vc.confidence == pytest.approx(0.75)
    assert vc.pattern_type == "no_clear_pattern"
    assert vc.reasoning == "test round-trip"


def test_kronos_verdict_clamps_out_of_range_values() -> None:
    """VisionClassification from KronosVerdict must clamp signal/confidence."""
    from agents.kronos_classifier import KronosVerdict

    # Over-range signal and confidence
    verdict = KronosVerdict(signal=5.0, confidence=3.0, direction="bullish", reasoning="x")
    vc = verdict.to_vision_classification()

    assert vc.signal == pytest.approx(1.0), "signal should be clamped to 1.0"
    assert vc.confidence == pytest.approx(1.0), "confidence should be clamped to 1.0"

    # Under-range
    verdict2 = KronosVerdict(signal=-5.0, confidence=-1.0, direction="bearish", reasoning="x")
    vc2 = verdict2.to_vision_classification()

    assert vc2.signal == pytest.approx(-1.0), "signal should be clamped to -1.0"
    assert vc2.confidence == pytest.approx(0.0), "confidence should be clamped to 0.0"


# ---------------------------------------------------------------------------
# Pipeline helper — _call_agent_analyze_kronos
# ---------------------------------------------------------------------------


async def test_pipeline_kronos_disabled_returns_neutral(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ENABLE_KRONOS is unset, _call_agent_analyze_kronos returns neutral dict."""
    monkeypatch.delenv(_ENV_FLAG, raising=False)

    import sys

    # Re-import pipeline with the env flag absent so _kronos is None
    if "agents.pipeline" in sys.modules:
        del sys.modules["agents.pipeline"]

    from agents.pipeline import TradingPipeline

    pipeline = TradingPipeline.__new__(TradingPipeline)
    pipeline._agents = {}
    pipeline._kronos = None  # explicitly disabled

    result = await pipeline._call_agent_analyze_kronos("MES", True, "1h")

    assert result == {"signal": 0.0, "confidence": 0.0, "summary": "Kronos disabled"}


async def test_pipeline_kronos_enabled_returns_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ENABLE_KRONOS=1 and bars are available, classify() result propagates."""
    import asyncio
    import pandas as pd
    from unittest.mock import AsyncMock, MagicMock

    monkeypatch.setenv(_ENV_FLAG, "1")

    from agents.kronos_classifier import KronosClassifier
    from agents.pattern_vision_analyst import VisionClassification
    from agents.pipeline import TradingPipeline

    # Build minimal fake bar DataFrame (20 rows required)
    df = pd.DataFrame(
        {
            "open": [100.0] * 20,
            "high": [101.0] * 20,
            "low": [99.0] * 20,
            "close": [100.5] * 20,
            "volume": [1000] * 20,
        }
    )

    fake_data_mgr = MagicMock()
    fake_data_mgr.get_bars = AsyncMock(return_value=df)

    fake_tech = MagicMock()
    fake_tech._data = fake_data_mgr

    kronos = KronosClassifier()
    # Stub classify to return a known verdict
    expected_vc = VisionClassification(
        pattern_type="no_clear_pattern",
        signal=0.0,
        confidence=0.0,
        reasoning="stub — Kronos not yet wired",
        raw="",
    )
    kronos.classify = AsyncMock(return_value=expected_vc)

    pipeline = TradingPipeline.__new__(TradingPipeline)
    pipeline._agents = {"technical": fake_tech}
    pipeline._kronos = kronos

    result = await pipeline._call_agent_analyze_kronos("MES", True, "1h")

    assert result["signal"] == pytest.approx(0.0)
    assert result["confidence"] == pytest.approx(0.0)
    assert result["summary"] == "stub — Kronos not yet wired"
    assert result["pattern_type"] == "no_clear_pattern"


async def test_pipeline_kronos_handles_missing_data_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When technical agent has no _data attribute, returns 'data unavailable' dict."""
    from unittest.mock import MagicMock

    monkeypatch.setenv(_ENV_FLAG, "1")

    from agents.kronos_classifier import KronosClassifier
    from agents.pipeline import TradingPipeline

    fake_tech = MagicMock(spec=[])  # no _data attribute

    pipeline = TradingPipeline.__new__(TradingPipeline)
    pipeline._agents = {"technical": fake_tech}
    pipeline._kronos = KronosClassifier()

    result = await pipeline._call_agent_analyze_kronos("MES", True, "1h")

    assert result == {"signal": 0.0, "confidence": 0.0, "summary": "data unavailable"}
