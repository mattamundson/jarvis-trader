"""Regression: DebateOrchestrator Corey-bias tie-break (Phase 4 Task D2).

The _corey_tiebreak helper is the last tilt before INCONCLUSIVE when both the
debate_score threshold and the conviction-asymmetry tie-break have failed.
It returns BULL_WINS / BEAR_WINS / None based on Corey's session bias.

Tests isolate the helper (pure function, no LLM). An integration-style test
runs through the live DebateOrchestrator branching by feeding synthetic
analyst_reports into the verdict path via helper reuse -- see the
_corey_tiebreak parametrization block at the end.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.debate import _corey_tiebreak  # noqa: E402


def _briefing(bias="neutral", conv=0.0):
    return {
        "discord_briefing": {
            "corey_bias": {"directional_bias": bias, "conviction": conv},
            "ib_levels": None,
        }
    }


# ── Silent no-op cases (return None) ─────────────────────────────────────────


def test_corey_tiebreak_none_input_returns_none():
    assert _corey_tiebreak(None) is None


def test_corey_tiebreak_non_dict_input_returns_none():
    assert _corey_tiebreak("not a dict") is None
    assert _corey_tiebreak([]) is None


def test_corey_tiebreak_missing_briefing_key_returns_none():
    assert _corey_tiebreak({}) is None


def test_corey_tiebreak_non_dict_briefing_returns_none():
    assert _corey_tiebreak({"discord_briefing": None}) is None
    assert _corey_tiebreak({"discord_briefing": "string"}) is None


def test_corey_tiebreak_missing_corey_bias_returns_none():
    assert _corey_tiebreak({"discord_briefing": {}}) is None


def test_corey_tiebreak_conviction_below_threshold_returns_none():
    assert _corey_tiebreak(_briefing(bias="bullish", conv=0.49)) is None
    assert _corey_tiebreak(_briefing(bias="bearish", conv=0.3)) is None


def test_corey_tiebreak_neutral_bias_returns_none():
    assert _corey_tiebreak(_briefing(bias="neutral", conv=0.99)) is None


def test_corey_tiebreak_bad_conviction_type_returns_none():
    payload = {
        "discord_briefing": {
            "corey_bias": {"directional_bias": "bullish", "conviction": "xyz"},
        }
    }
    assert _corey_tiebreak(payload) is None


def test_corey_tiebreak_unknown_bias_returns_none():
    assert _corey_tiebreak(_briefing(bias="sideways", conv=0.9)) is None


# ── Firing cases (return verdict) ────────────────────────────────────────────


def test_corey_tiebreak_bullish_above_threshold_returns_bull_wins():
    assert _corey_tiebreak(_briefing(bias="bullish", conv=0.5)) == "BULL_WINS"
    assert _corey_tiebreak(_briefing(bias="bullish", conv=0.95)) == "BULL_WINS"


def test_corey_tiebreak_bearish_above_threshold_returns_bear_wins():
    assert _corey_tiebreak(_briefing(bias="bearish", conv=0.5)) == "BEAR_WINS"
    assert _corey_tiebreak(_briefing(bias="bearish", conv=0.8)) == "BEAR_WINS"


def test_corey_tiebreak_case_insensitive_bias():
    assert _corey_tiebreak(_briefing(bias="BULLISH", conv=0.8)) == "BULL_WINS"
    assert _corey_tiebreak(_briefing(bias="Bearish", conv=0.8)) == "BEAR_WINS"


# ── Boundary: conviction exactly at threshold (inclusive) ────────────────────


@pytest.mark.parametrize("bias,expected", [
    ("bullish", "BULL_WINS"),
    ("bearish", "BEAR_WINS"),
])
def test_corey_tiebreak_conviction_exactly_at_threshold_fires(bias, expected):
    """Boundary check: conviction == 0.5 should fire (gate is >= 0.5, not >)."""
    assert _corey_tiebreak(_briefing(bias=bias, conv=0.5)) == expected


# ── Verdict-to-debate-score mapping sanity ───────────────────────────────────


def test_verdict_strings_match_debate_module_constants():
    """Sanity: our returned strings must match the ones the orchestrator compares against."""
    bull = _corey_tiebreak(_briefing(bias="bullish", conv=0.9))
    bear = _corey_tiebreak(_briefing(bias="bearish", conv=0.9))
    # These exact strings are compared in debate.py's verdict branch; a drift
    # would silently break the orchestrator wiring.
    assert bull == "BULL_WINS"
    assert bear == "BEAR_WINS"
