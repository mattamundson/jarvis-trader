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
