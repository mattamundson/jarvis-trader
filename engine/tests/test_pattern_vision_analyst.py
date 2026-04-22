"""Unit tests for the Pattern Vision Analyst scaffold.

Exercises the orchestration layer (capture -> classify -> report) with
Protocol-based fakes. No Chrome, no Anthropic API, no network. Live-wiring
tests belong in a separate integration suite (pending per scaffold module
docstring).
"""

from __future__ import annotations

import json

import pytest

from agents.pattern_vision_analyst import (
    KNOWN_PATTERNS,
    PatternVisionAnalyst,
    PatternVisionReport,
    VisionClassification,
    parse_vision_json,
)


class _FakeCapture:
    def __init__(self, payload: bytes | None = b"PNG_FAKE", raises: Exception | None = None):
        self.payload = payload
        self.raises = raises
        self.calls: list[tuple[str, str]] = []

    async def capture(self, symbol: str, timeframe: str) -> bytes:
        self.calls.append((symbol, timeframe))
        if self.raises is not None:
            raise self.raises
        assert self.payload is not None
        return self.payload


class _FakeClassifier:
    def __init__(
        self,
        result: VisionClassification | None = None,
        raises: Exception | None = None,
    ):
        self.result = result
        self.raises = raises
        self.seen_context: str = ""

    async def classify(self, png_bytes: bytes, context: str) -> VisionClassification:
        self.seen_context = context
        if self.raises is not None:
            raise self.raises
        assert self.result is not None
        return self.result


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_analyze_happy_path_returns_structured_report():
    classifier = _FakeClassifier(
        result=VisionClassification(
            pattern_type="bull_flag",
            signal=0.6,
            confidence=0.75,
            reasoning="Pennant after a strong leg up; tight consolidation.",
            raw='{"pattern_type": "bull_flag"}',
        )
    )
    analyst = PatternVisionAnalyst(chart_capture=_FakeCapture(), classifier=classifier)

    report = await analyst.analyze(symbol="MCL", timeframe="1h")

    assert isinstance(report, PatternVisionReport)
    assert report.pattern_type == "bull_flag"
    assert report.signal == pytest.approx(0.6)
    assert report.confidence == pytest.approx(0.75)
    assert report.indicators.get("weight") != 0.0
    d = report.to_dict()
    assert d["symbol"] == "MCL"
    assert d["pattern_type"] == "bull_flag"


async def test_analyze_passes_symbol_timeframe_to_capture():
    capture = _FakeCapture()
    classifier = _FakeClassifier(
        result=VisionClassification(
            pattern_type="no_clear_pattern",
            signal=0.0,
            confidence=0.0,
            reasoning="",
        )
    )
    analyst = PatternVisionAnalyst(chart_capture=capture, classifier=classifier)

    await analyst.analyze(symbol="MNQ", timeframe="5m")

    assert capture.calls == [("MNQ", "5m")]


async def test_analyze_injects_context_hint_into_classifier_prompt():
    classifier = _FakeClassifier(
        result=VisionClassification(
            pattern_type="no_clear_pattern",
            signal=0.0,
            confidence=0.0,
            reasoning="",
        )
    )
    analyst = PatternVisionAnalyst(chart_capture=_FakeCapture(), classifier=classifier)

    await analyst.analyze(symbol="MCL", timeframe="1h", context_hint="STC oversold cross-above")

    assert "Context hint: STC oversold cross-above" in classifier.seen_context


# ---------------------------------------------------------------------------
# Abstention / graceful degradation
# ---------------------------------------------------------------------------


async def test_capture_failure_returns_abstention_not_exception():
    analyst = PatternVisionAnalyst(
        chart_capture=_FakeCapture(raises=RuntimeError("MCP connection refused")),
        classifier=_FakeClassifier(),
    )

    report = await analyst.analyze(symbol="MCL", timeframe="1h")

    assert report.confidence == 0.0
    assert report.signal == 0.0
    assert report.indicators.get("weight") == 0.0
    assert report.indicators.get("reason") == "chart_capture_failed"


async def test_classify_failure_returns_abstention():
    analyst = PatternVisionAnalyst(
        chart_capture=_FakeCapture(),
        classifier=_FakeClassifier(raises=TimeoutError("vision API timed out")),
    )

    report = await analyst.analyze(symbol="MCL", timeframe="1h")

    assert report.indicators.get("reason") == "vision_classify_failed"
    assert report.confidence == 0.0


async def test_unknown_pattern_label_returns_abstention():
    analyst = PatternVisionAnalyst(
        chart_capture=_FakeCapture(),
        classifier=_FakeClassifier(
            result=VisionClassification(
                pattern_type="spaghetti_monster",
                signal=0.9,
                confidence=0.9,
                reasoning="made up",
            )
        ),
    )

    report = await analyst.analyze(symbol="MCL", timeframe="1h")

    assert report.indicators.get("reason") == "unknown_pattern_type"
    assert report.signal == 0.0


async def test_abstention_reason_text_rejects_bearish_misread():
    analyst = PatternVisionAnalyst(
        chart_capture=_FakeCapture(raises=RuntimeError("boom")),
        classifier=_FakeClassifier(),
    )

    report = await analyst.analyze(symbol="MCL", timeframe="1h")

    assert "NOT a bearish signal" in report.reasoning


# ---------------------------------------------------------------------------
# Clamping
# ---------------------------------------------------------------------------


async def test_signal_is_clamped_to_unit_range():
    classifier = _FakeClassifier(
        result=VisionClassification(
            pattern_type="bull_flag",
            signal=5.0,
            confidence=0.5,
            reasoning="",
        )
    )
    analyst = PatternVisionAnalyst(chart_capture=_FakeCapture(), classifier=classifier)

    report = await analyst.analyze(symbol="MCL", timeframe="1h")

    assert report.signal == 1.0


async def test_confidence_is_clamped_to_zero_one():
    classifier = _FakeClassifier(
        result=VisionClassification(
            pattern_type="bear_flag",
            signal=-0.5,
            confidence=3.0,
            reasoning="",
        )
    )
    analyst = PatternVisionAnalyst(chart_capture=_FakeCapture(), classifier=classifier)

    report = await analyst.analyze(symbol="MCL", timeframe="1h")

    assert report.confidence == 1.0


async def test_negative_confidence_clamped_to_zero():
    classifier = _FakeClassifier(
        result=VisionClassification(
            pattern_type="double_top",
            signal=-0.3,
            confidence=-0.2,
            reasoning="",
        )
    )
    analyst = PatternVisionAnalyst(chart_capture=_FakeCapture(), classifier=classifier)

    report = await analyst.analyze(symbol="MCL", timeframe="1h")

    assert report.confidence == 0.0


# ---------------------------------------------------------------------------
# parse_vision_json
# ---------------------------------------------------------------------------


def test_parse_vision_json_plain():
    raw = json.dumps(
        {
            "pattern_type": "ascending_triangle",
            "signal": 0.4,
            "confidence": 0.6,
            "reasoning": "horizontal resistance, rising lows",
        }
    )
    out = parse_vision_json(raw)
    assert out.pattern_type == "ascending_triangle"
    assert out.signal == pytest.approx(0.4)
    assert out.confidence == pytest.approx(0.6)
    assert out.raw == raw


def test_parse_vision_json_strips_markdown_fence():
    raw = '```json\n{"pattern_type": "bear_flag", "signal": -0.5, "confidence": 0.7, "reasoning": "r"}\n```'
    out = parse_vision_json(raw)
    assert out.pattern_type == "bear_flag"
    assert out.signal == pytest.approx(-0.5)


def test_parse_vision_json_strips_plain_fence():
    raw = '```\n{"pattern_type": "bull_flag", "signal": 0.3, "confidence": 0.4, "reasoning": ""}\n```'
    out = parse_vision_json(raw)
    assert out.pattern_type == "bull_flag"


def test_parse_vision_json_bad_json_returns_no_clear_pattern():
    out = parse_vision_json("this is not json at all")
    assert out.pattern_type == "no_clear_pattern"
    assert out.signal == 0.0
    assert out.confidence == 0.0


def test_parse_vision_json_non_object_returns_no_clear_pattern():
    out = parse_vision_json("[1, 2, 3]")
    assert out.pattern_type == "no_clear_pattern"


def test_parse_vision_json_clamps_out_of_range():
    out = parse_vision_json(
        '{"pattern_type": "bull_flag", "signal": 99.0, "confidence": -0.5, "reasoning": ""}'
    )
    assert out.signal == 1.0
    assert out.confidence == 0.0


# ---------------------------------------------------------------------------
# Schema guard
# ---------------------------------------------------------------------------


def test_known_patterns_includes_expected_labels():
    must_have = {
        "head_and_shoulders",
        "double_top",
        "double_bottom",
        "bull_flag",
        "bear_flag",
        "no_clear_pattern",
    }
    assert must_have.issubset(KNOWN_PATTERNS)


async def test_report_to_dict_is_json_serializable():
    classifier = _FakeClassifier(
        result=VisionClassification(
            pattern_type="inverse_head_and_shoulders",
            signal=0.5,
            confidence=0.55,
            reasoning="test",
        )
    )
    analyst = PatternVisionAnalyst(chart_capture=_FakeCapture(), classifier=classifier)
    report = await analyst.analyze(symbol="MNQ", timeframe="1h")
    blob = json.dumps(report.to_dict())
    restored = json.loads(blob)
    assert restored["pattern_type"] == "inverse_head_and_shoulders"
