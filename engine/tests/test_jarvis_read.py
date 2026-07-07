"""Tests for JARVIS's Read (engine/analysis/jarvis_read.py) and its brief section.

No real LLM calls — the success path uses a mock client; the fallback paths
assert the honest 'no read' stub. Also covers the parser, prompt builder, and
the render_jarvis_read markdown section in the morning brief.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from analysis.jarvis_read import (
    ANCHOR_SYMBOL,
    _fallback_read,
    build_prompt,
    generate_read,
    parse_read,
)
from scripts.daily_morning_briefing import render_jarvis_read

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_LEVELS = {
    "MES": {
        "prior_close": 7450.0,
        "pivot": 7460.92,
        "r1": 7512.33,
        "s1": 7425.33,
        "atr": 92.68,
        "targets_up": [7512.15, 7534.02],
        "targets_down": [7441.35, 7419.48],
    },
    "MGC": None,  # missing-bars symbol must be skipped gracefully
}

_REGIME = {"MES": {"regime": "RANGE_BOUND", "bias": "STRONG_BEAR", "close": 7418.5}}

_VALID_JSON = json.dumps(
    {
        "bias": "bearish",
        "conviction": 0.6,
        "key_levels_committed": [7460.92, 7425.33],
        "scenario_if_above": "reclaim pivot opens 7512",
        "scenario_if_below": "lose 7425 targets 7419",
        "narrative": "Leaning bearish under the pivot with the SMA stack down.",
    }
)


class _FakeResult:
    def __init__(self, success: bool, content: str = "", error: str = ""):
        self.success = success
        self.content = content
        self.error = error


class _FakeClient:
    """Mimics JarvisLLMClient.call (async)."""

    def __init__(self, result: _FakeResult):
        self._result = result
        self.calls: list[dict] = []

    async def call(self, **kwargs):
        self.calls.append(kwargs)
        return self._result


# ---------------------------------------------------------------------------
# parse_read
# ---------------------------------------------------------------------------


def test_parse_read_valid():
    out = parse_read(_VALID_JSON)
    assert out["bias"] == "bearish"
    assert out["conviction"] == 0.6
    assert out["key_levels_committed"] == [7460.92, 7425.33]
    assert out["data_quality"] == "fresh"


def test_parse_read_strips_code_fence():
    fenced = "```json\n" + _VALID_JSON + "\n```"
    out = parse_read(fenced)
    assert out["bias"] == "bearish"
    assert out["narrative"].startswith("Leaning bearish")


def test_parse_read_clamps_conviction_and_normalizes_bias():
    raw = json.dumps({"bias": "MOON", "conviction": 5.0})
    out = parse_read(raw)
    assert out["bias"] == "neutral"  # invalid bias normalized
    assert out["conviction"] == 1.0  # clamped to [0,1]


def test_parse_read_drops_non_numeric_levels():
    raw = json.dumps({"bias": "bullish", "key_levels_committed": [1.5, "x", None, 2]})
    out = parse_read(raw)
    assert out["key_levels_committed"] == [1.5, 2.0]


def test_parse_read_raises_on_garbage():
    with pytest.raises(json.JSONDecodeError):
        parse_read("not json at all")


# ---------------------------------------------------------------------------
# build_prompt
# ---------------------------------------------------------------------------


def test_build_prompt_includes_levels_and_regime():
    prompt = build_prompt("2026-06-25", _LEVELS, _REGIME)
    assert "2026-06-25" in prompt
    assert "MES" in prompt
    assert "7460.92" in prompt  # pivot rendered
    assert "RANGE_BOUND" in prompt  # regime block included
    assert "MGC" not in prompt  # None symbol skipped


def test_build_prompt_handles_no_levels():
    prompt = build_prompt("2026-06-25", {"MGC": None}, None)
    assert "(no levels available)" in prompt


# ---------------------------------------------------------------------------
# _fallback_read
# ---------------------------------------------------------------------------


def test_fallback_read_shape():
    fb = _fallback_read("LLM unavailable")
    assert fb["data_quality"] == "none"
    assert fb["bias"] == "neutral"
    assert fb["conviction"] == 0.0
    assert "LLM unavailable" in fb["narrative"]


# ---------------------------------------------------------------------------
# generate_read (async)
# ---------------------------------------------------------------------------


def test_generate_read_no_key_no_client_returns_fallback():
    out = asyncio.run(generate_read("2026-06-25", _LEVELS, _REGIME, api_key=""))
    assert out["data_quality"] == "none"


def test_generate_read_with_mock_client_success():
    client = _FakeClient(_FakeResult(success=True, content=_VALID_JSON))
    out = asyncio.run(generate_read("2026-06-25", _LEVELS, _REGIME, llm_client=client))
    assert out["bias"] == "bearish"
    assert out["data_quality"] == "fresh"
    # routed through the client with the right agent name
    assert client.calls[0]["agent_name"] == "jarvis_read"


def test_generate_read_with_mock_client_failure_returns_fallback():
    client = _FakeClient(_FakeResult(success=False, error="rate limited"))
    out = asyncio.run(generate_read("2026-06-25", _LEVELS, _REGIME, llm_client=client))
    assert out["data_quality"] == "none"


def test_generate_read_bad_json_returns_fallback():
    client = _FakeClient(_FakeResult(success=True, content="garbage not json"))
    out = asyncio.run(generate_read("2026-06-25", _LEVELS, _REGIME, llm_client=client))
    assert out["data_quality"] == "none"


# ---------------------------------------------------------------------------
# render_jarvis_read (brief section)
# ---------------------------------------------------------------------------


def test_render_read_full():
    read = parse_read(_VALID_JSON)
    md = "\n".join(render_jarvis_read(read))
    assert "## JARVIS's Read" in md
    assert "BEARISH" in md
    assert "6/10" in md  # conviction 0.6 -> 6/10
    assert "Leaning bearish" in md
    assert "Watching:" in md


def test_render_read_fallback():
    md = "\n".join(render_jarvis_read(_fallback_read("LLM unavailable")))
    assert "## JARVIS's Read" in md
    assert "No read available" in md
    assert "BEARISH" not in md and "BULLISH" not in md


def test_render_read_none():
    md = "\n".join(render_jarvis_read(None))
    assert "## JARVIS's Read" in md


def test_anchor_symbol_is_mes():
    assert ANCHOR_SYMBOL == "MES"
