"""Unit tests for the SEPA regime-confirmation wiring into debate.py.

Covers the three new helpers added to ``engine/agents/debate.py``:

  * ``_is_sepa_enabled`` — env-var gate
  * ``_compute_sepa_nudge`` — raw signal from a SEPA evaluation or context
  * ``_apply_sepa_nudge`` — direction-aligned application guard

The integration path (``DebateOrchestrator.run_debate`` with a sepa_context)
is covered indirectly by exercising ``_compute_sepa_nudge`` on both raw OHLC
bars and a pre-built ``SEPAResult``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import agents.debate as debate
from analytics.sepa_trend_template import SEPAResult, evaluate_sepa

# ── Env-var gate: _is_sepa_enabled ──────────────────────────────────────────


@pytest.mark.parametrize("val,expected", [
    ("1", True), ("true", True), ("TRUE", True), ("yes", True), ("on", True),
    ("0", False), ("false", False), ("", False), ("no", False), ("off", False),
])
def test_is_sepa_enabled_parses_truthy_values(monkeypatch, val, expected):
    monkeypatch.setenv("REGIME_USE_SEPA", val)
    assert debate._is_sepa_enabled() is expected


def test_is_sepa_enabled_defaults_false(monkeypatch):
    monkeypatch.delenv("REGIME_USE_SEPA", raising=False)
    assert debate._is_sepa_enabled() is False


# ── Pure helper: _compute_sepa_nudge ────────────────────────────────────────


def _make_result(score: float, evaluated: int = 8) -> SEPAResult:
    r = SEPAResult()
    r.score = score
    r.evaluated_count = evaluated
    r.passed_count = int(round(score * evaluated))
    return r


def test_compute_sepa_nudge_none_context_returns_zero():
    assert debate._compute_sepa_nudge(None) == (None, 0.0)


def test_compute_sepa_nudge_empty_context_returns_zero():
    assert debate._compute_sepa_nudge({}) == (None, 0.0)


def test_compute_sepa_nudge_stage2_uptrend_gives_bull_nudge():
    ctx = {"result": _make_result(0.875)}
    score, nudge = debate._compute_sepa_nudge(ctx)
    assert score == pytest.approx(0.875)
    assert nudge == pytest.approx(debate._SEPA_NUDGE_MAGNITUDE)


def test_compute_sepa_nudge_at_bull_threshold_exactly_is_bullish():
    """Boundary: score == 0.75 is inclusive of the bullish branch."""
    ctx = {"result": _make_result(0.75)}
    _, nudge = debate._compute_sepa_nudge(ctx)
    assert nudge == pytest.approx(debate._SEPA_NUDGE_MAGNITUDE)


def test_compute_sepa_nudge_bearish_gives_negative_nudge():
    ctx = {"result": _make_result(0.125)}
    score, nudge = debate._compute_sepa_nudge(ctx)
    assert score == pytest.approx(0.125)
    assert nudge == pytest.approx(-debate._SEPA_NUDGE_MAGNITUDE)


def test_compute_sepa_nudge_at_bear_threshold_exactly_is_bearish():
    """Boundary: score == 0.25 is inclusive of the bearish branch."""
    ctx = {"result": _make_result(0.25)}
    _, nudge = debate._compute_sepa_nudge(ctx)
    assert nudge == pytest.approx(-debate._SEPA_NUDGE_MAGNITUDE)


def test_compute_sepa_nudge_range_gives_zero_nudge():
    """Scores in the dead zone (0.25, 0.75) produce no nudge."""
    ctx = {"result": _make_result(0.5)}
    score, nudge = debate._compute_sepa_nudge(ctx)
    assert score == pytest.approx(0.5)
    assert nudge == 0.0


def test_compute_sepa_nudge_thin_data_returns_zero():
    """When fewer than _SEPA_MIN_EVALUATED criteria were checked, skip the nudge."""
    ctx = {"result": _make_result(0.9, evaluated=3)}  # would be strong bull but thin
    score, nudge = debate._compute_sepa_nudge(ctx)
    assert score is None
    assert nudge == 0.0


def test_compute_sepa_nudge_from_raw_ohlc_integration_path():
    """End-to-end: pass close/high/low series and let the helper compute SEPA."""
    # Construct a strong synthetic uptrend: 260 bars, monotonic 100 → 200
    n = 260
    close = pd.Series(np.linspace(100.0, 200.0, n))
    high = close * 1.01
    low = close * 0.99
    ctx = {"close": close, "high": high, "low": low}
    score, nudge = debate._compute_sepa_nudge(ctx)
    assert score is not None
    assert score >= 0.75  # should be full Stage 2
    assert nudge == pytest.approx(debate._SEPA_NUDGE_MAGNITUDE)


def test_compute_sepa_nudge_handles_evaluate_failure_gracefully(monkeypatch):
    """If evaluate_sepa raises, the helper must return (None, 0.0) — no leaks."""
    def _boom(*a, **k):
        raise RuntimeError("synthetic SEPA failure")
    monkeypatch.setattr("analytics.sepa_trend_template.evaluate_sepa", _boom)
    ctx = {"close": pd.Series([1.0, 2.0, 3.0])}
    score, nudge = debate._compute_sepa_nudge(ctx)
    assert score is None
    assert nudge == 0.0


# ── Direction-alignment guard: _apply_sepa_nudge ────────────────────────────


def test_apply_sepa_nudge_zero_raw_is_noop():
    assert debate._apply_sepa_nudge(0.18, 0.0) == (0.18, 0.0)


def test_apply_sepa_nudge_aligned_bull_adds_nudge():
    new_score, applied = debate._apply_sepa_nudge(0.17, 0.03)
    assert new_score == pytest.approx(0.20)
    assert applied == pytest.approx(0.03)


def test_apply_sepa_nudge_aligned_bear_adds_negative_nudge():
    new_score, applied = debate._apply_sepa_nudge(-0.17, -0.03)
    assert new_score == pytest.approx(-0.20)
    assert applied == pytest.approx(-0.03)


def test_apply_sepa_nudge_contradicting_bull_signal_is_dropped():
    """SEPA says not-uptrend (-0.03) but debate is bullish (+0.20) — ignore SEPA."""
    new_score, applied = debate._apply_sepa_nudge(0.20, -0.03)
    assert new_score == pytest.approx(0.20)
    assert applied == 0.0


def test_apply_sepa_nudge_contradicting_bear_signal_is_dropped():
    """SEPA says Stage 2 uptrend (+0.03) but debate is bearish (-0.20) — ignore SEPA."""
    new_score, applied = debate._apply_sepa_nudge(-0.20, 0.03)
    assert new_score == pytest.approx(-0.20)
    assert applied == 0.0


def test_apply_sepa_nudge_tied_debate_score_drops_nudge():
    """A 0.00 debate score has no direction — SEPA cannot manufacture one."""
    assert debate._apply_sepa_nudge(0.0, 0.03) == (0.0, 0.0)
    assert debate._apply_sepa_nudge(0.0, -0.03) == (0.0, 0.0)


# ── Parameter sanity checks ──────────────────────────────────────────────────


def test_sepa_nudge_magnitude_below_all_regime_thresholds():
    """The nudge magnitude must be strictly less than every regime threshold
    so that SEPA alone cannot flip a 0.00 score into a verdict."""
    for regime, threshold in debate.REGIME_DEBATE_THRESHOLDS.items():
        assert debate._SEPA_NUDGE_MAGNITUDE < threshold, (
            f"Nudge {debate._SEPA_NUDGE_MAGNITUDE} must be < threshold "
            f"{threshold} for regime {regime} (otherwise SEPA alone can "
            "produce a verdict, which violates the confirmation-only contract)"
        )
    assert debate._SEPA_NUDGE_MAGNITUDE < debate.DEFAULT_DEBATE_THRESHOLD


def test_sepa_bull_threshold_gt_bear_threshold():
    """The dead zone must be non-empty and ordered."""
    assert debate._SEPA_BULL_THRESHOLD > debate._SEPA_BEAR_THRESHOLD
