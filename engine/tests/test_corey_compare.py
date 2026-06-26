"""Tests for JARVIS vs Corey comparison (Phase F).

The live feed is dry, so fetch_corey_bias returns None in practice. These tests
exercise the pure compare/render logic with a synthetic Corey bias and assert the
dormant path renders nothing.
"""

from __future__ import annotations

from analysis.corey_compare import compare, render_corey_compare

_READ = {"bias": "bearish", "conviction": 0.6}
_COREY = {
    "directional_bias": "bearish",
    "key_levels": [7460.0, 7425.0],
    "conviction": 0.7,
    "corey_quote": "Below 7460 I'm leaning short toward 7425.",
    "data_quality": "fresh",
}


def test_compare_dormant_returns_none():
    assert compare(_READ, None) is None


def test_compare_agreement():
    out = compare(_READ, _COREY, jarvis_levels=[7460.92, 7425.33])
    assert out["agree"] is True
    assert out["jarvis_bias"] == "bearish"
    assert out["corey_bias"] == "bearish"
    # 7460.0 aligns with 7460.92 within tol -> agree True
    align = {p["corey"]: p for p in out["level_alignment"]}
    assert align[7460.0]["agree"] is True


def test_compare_divergence_and_scoring():
    read = {"bias": "bullish", "conviction": 0.8}
    actual = {"open": 100.0, "high": 101.0, "low": 90.0, "close": 92.0}  # down
    out = compare(read, _COREY, jarvis_levels=[], actual=actual)
    assert out["agree"] is False
    assert out["jarvis_correct"] == 0.0  # bullish, market down
    assert out["corey_correct"] == 1.0  # bearish, market down
    # no jarvis levels -> corey levels report no match
    assert out["level_alignment"][0]["jarvis"] is None


def test_render_dormant_is_empty():
    assert render_corey_compare(None) == []


def test_render_live_section():
    out = compare(_READ, _COREY, jarvis_levels=[7460.92, 7425.33])
    md = "\n".join(render_corey_compare(out))
    assert "## JARVIS vs Corey" in md
    assert "AGREE" in md
    assert "leaning short" in md  # quote rendered


def test_render_divergence_outcome():
    read = {"bias": "bullish", "conviction": 0.8}
    actual = {"open": 100.0, "high": 101.0, "low": 90.0, "close": 92.0}
    out = compare(read, _COREY, jarvis_levels=[], actual=actual)
    md = "\n".join(render_corey_compare(out))
    assert "DIVERGE" in md
    assert "JARVIS WRONG" in md
    assert "Corey CORRECT" in md
