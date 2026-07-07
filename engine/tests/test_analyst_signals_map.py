"""build_analyst_signals_map -- the open-path extraction that feeds calibration.

Regression guard for the 2026-06-05 wiring bug: scanner-opened trades had no
analyst_signals in strategy_params, so every close silently no-op'd at
tracker.py:_record_agent_feedback and trade_outcomes never filled.
"""

from __future__ import annotations

from analytics.agent_feedback import build_analyst_signals_map


def test_extracts_seven_agents_as_floats():
    reports = {
        "technical": {"signal": 0.8},
        "news": {"signal": -0.3},
        "social": {"signal": 0.0},
        "fundamental": {"signal": 0.5},
        "corey": {"signal": -0.9},
        "breakout": {"signal": 0.2},
        "harmonic": {"signal": 0.1},
        "regime": {"signal": 0.4},  # not an agent -> ignored
        "_meta": "x",  # non-dict -> ignored
    }
    out = build_analyst_signals_map(reports)
    assert set(out) == {
        "technical",
        "news",
        "social",
        "fundamental",
        "corey",
        "breakout",
        "harmonic",
    }
    assert out["technical"] == 0.8
    assert out["corey"] == -0.9
    assert all(isinstance(v, float) for v in out.values())


def test_missing_signal_defaults_zero():
    out = build_analyst_signals_map({"technical": {}, "news": {"signal": 0.5}})
    assert out["technical"] == 0.0
    assert out["news"] == 0.5


def test_none_or_nondict_returns_empty():
    assert build_analyst_signals_map(None) == {}
    assert build_analyst_signals_map("nope") == {}
    assert build_analyst_signals_map({}) == {}
