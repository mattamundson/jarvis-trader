"""
Tests for utils.llm_json.parse_llm_json — tolerant JSON extraction.

Verifies the recoverable cases that the old inline ``split("```")[1]`` pattern
turned into zero-signal failures (markdown fences anywhere, leading/trailing
prose, trailing commas, braces inside strings) now parse, while genuinely
unparseable input still raises so callers keep their safe-fallback behavior.
"""

import json

import pytest

from utils.llm_json import LLMJsonError, parse_llm_json


class TestExceptionHierarchy:
    """LLMJsonError must be catchable by every adopter's existing except clause."""

    def test_is_json_decode_error(self):
        # Adopters that catch json.JSONDecodeError specifically still handle it.
        assert issubclass(LLMJsonError, json.JSONDecodeError)

    def test_is_value_error(self):
        # JSONDecodeError is a ValueError; adopters catching ValueError still work.
        assert issubclass(LLMJsonError, ValueError)

    def test_caught_as_json_decode_error(self):
        with pytest.raises(json.JSONDecodeError):
            parse_llm_json("no json here")


class TestRecoverable:
    def test_clean_object(self):
        assert parse_llm_json('{"signal": 0.5, "confidence": 0.8}') == {
            "signal": 0.5,
            "confidence": 0.8,
        }

    def test_fenced_json_tag(self):
        text = '```json\n{"signal": -0.3, "trend": "downtrend"}\n```'
        assert parse_llm_json(text) == {"signal": -0.3, "trend": "downtrend"}

    def test_fenced_no_tag(self):
        text = '```\n{"a": 1}\n```'
        assert parse_llm_json(text) == {"a": 1}

    def test_leading_prose(self):
        text = 'Here is the analysis:\n{"signal": 0.2}'
        assert parse_llm_json(text) == {"signal": 0.2}

    def test_trailing_prose(self):
        text = '{"signal": 0.2}\n\nLet me know if you need more detail.'
        assert parse_llm_json(text) == {"signal": 0.2}

    def test_prose_then_fence(self):
        # Fence not at index 0 — the old startswith("```") check missed this.
        text = 'Sure thing.\n```json\n{"confidence": 0.9}\n```'
        assert parse_llm_json(text) == {"confidence": 0.9}

    def test_trailing_comma_repaired(self):
        text = '{"signal": 0.1, "confidence": 0.7,}'
        assert parse_llm_json(text) == {"signal": 0.1, "confidence": 0.7}

    def test_trailing_comma_in_nested(self):
        text = '{"levels": [1, 2, 3,], "ok": true,}'
        assert parse_llm_json(text) == {"levels": [1, 2, 3], "ok": True}

    def test_braces_inside_string_value(self):
        text = '{"summary": "range is {tight}", "signal": 0.0}'
        assert parse_llm_json(text) == {"summary": "range is {tight}", "signal": 0.0}

    def test_escaped_quote_inside_string(self):
        text = '{"reasoning": "he said \\"buy\\" now", "signal": 0.4}'
        assert parse_llm_json(text) == {
            "reasoning": 'he said "buy" now',
            "signal": 0.4,
        }

    def test_nested_object(self):
        text = 'prefix {"a": {"b": 2}, "c": 3} suffix'
        assert parse_llm_json(text) == {"a": {"b": 2}, "c": 3}

    def test_whitespace_only_padding(self):
        assert parse_llm_json('   \n  {"x": 1}  \n ') == {"x": 1}

    def test_realistic_analyst_shape(self):
        text = (
            "```json\n"
            "{\n"
            '  "signal": 0.65,\n'
            '  "confidence": 0.72,\n'
            '  "trend": "uptrend",\n'
            '  "regime": "trending",\n'
            '  "summary": "Bullish momentum with MTF alignment",\n'
            '  "regime_readiness": "READY",\n'
            "}\n"  # trailing comma
            "```\n"
            "Hope that helps!"
        )
        result = parse_llm_json(text)
        assert result["signal"] == 0.65
        assert result["regime_readiness"] == "READY"


class TestUnrecoverable:
    def test_none_raises(self):
        with pytest.raises(LLMJsonError):
            parse_llm_json(None)

    def test_empty_string_raises(self):
        with pytest.raises(LLMJsonError):
            parse_llm_json("")

    def test_pure_prose_raises(self):
        with pytest.raises(LLMJsonError):
            parse_llm_json("I could not complete the analysis at this time.")

    def test_array_not_dict_raises(self):
        # Top-level array is not an object; analysts expect a dict.
        with pytest.raises(LLMJsonError):
            parse_llm_json("[1, 2, 3]")

    def test_bare_number_raises(self):
        with pytest.raises(LLMJsonError):
            parse_llm_json("0.5")

    def test_unfilled_template_placeholder_raises(self):
        # The 2026-06-04 failure class: model echoed the template literally.
        text = '{"signal": <float -1.0 to 1.0>, "confidence": <float>}'
        with pytest.raises(LLMJsonError):
            parse_llm_json(text)
