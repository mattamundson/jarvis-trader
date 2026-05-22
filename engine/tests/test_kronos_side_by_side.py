"""Unit tests for the Kronos side-by-side diff logic.

Tests the ``_diff_verdicts`` and ``_render_report`` functions from
``scripts/kronos_side_by_side.py`` using synthetic verdicts — no engine
connection required.

Import path: the scripts/ directory is added to sys.path inside the test so
the module can be imported directly without installation.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make scripts/ importable from the engine test runner
_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from kronos_side_by_side import _diff_verdicts, _render_report

# ---------------------------------------------------------------------------
# _diff_verdicts — correctness tests
# ---------------------------------------------------------------------------


def test_diff_identical_verdicts_no_change() -> None:
    """Two identical neutral verdicts produce zero deltas and no direction change."""
    verdict = {"signal": 0.0, "confidence": 0.0, "summary": "disabled"}
    result = _diff_verdicts(verdict, verdict)

    assert result["signal_delta"] == pytest.approx(0.0)
    assert result["confidence_delta"] == pytest.approx(0.0)
    assert result["direction_change"] is False
    assert result["summary_changed"] is False


def test_diff_neutral_off_bullish_on_direction_change() -> None:
    """Neutral OFF, bullish ON → direction_change=True, positive signal_delta."""
    off_v = {"signal": 0.0, "confidence": 0.0, "summary": "disabled"}
    on_v = {"signal": 0.5, "confidence": 0.4, "summary": "predicted +80 bps over 5 bars"}

    result = _diff_verdicts(off_v, on_v)

    assert result["signal_delta"] == pytest.approx(0.5)
    assert result["confidence_delta"] == pytest.approx(0.4)
    assert result["direction_change"] is True
    assert result["summary_changed"] is True


def test_diff_bullish_off_bearish_on_direction_change() -> None:
    """Bullish OFF, bearish ON → direction_change=True."""
    off_v = {"signal": 0.3, "confidence": 0.2, "summary": "+60 bps"}
    on_v = {"signal": -0.4, "confidence": 0.3, "summary": "-80 bps"}

    result = _diff_verdicts(off_v, on_v)

    assert result["direction_change"] is True
    assert result["signal_delta"] == pytest.approx(-0.7)


def test_diff_both_bullish_no_direction_change() -> None:
    """Both verdicts bullish → direction_change=False even if magnitude differs."""
    off_v = {"signal": 0.2, "confidence": 0.1, "summary": "a"}
    on_v = {"signal": 0.8, "confidence": 0.7, "summary": "b"}

    result = _diff_verdicts(off_v, on_v)

    assert result["direction_change"] is False
    assert result["signal_delta"] == pytest.approx(0.6)


def test_diff_missing_keys_handled_gracefully() -> None:
    """Verdicts with missing keys default to 0.0 without raising."""
    off_v: dict = {}
    on_v: dict = {}

    result = _diff_verdicts(off_v, on_v)

    assert result["signal_delta"] == pytest.approx(0.0)
    assert result["confidence_delta"] == pytest.approx(0.0)
    assert result["direction_change"] is False


# ---------------------------------------------------------------------------
# _render_report — smoke tests
# ---------------------------------------------------------------------------


def test_render_report_empty_rows() -> None:
    """Empty rows list renders without raising and contains 'No rows' sentinel."""
    report = _render_report("MES", 3, [], "2026-05-20_1200")
    assert "No rows" in report
    assert "MES" in report


def test_render_report_with_rows_contains_expected_sections() -> None:
    """Non-empty rows render the summary stats and per-run detail table."""
    rows = [
        {
            "signal_delta": 0.5,
            "confidence_delta": 0.4,
            "direction_change": True,
            "off_signal": 0.0,
            "on_signal": 0.5,
            "off_confidence": 0.0,
            "on_confidence": 0.4,
        },
        {
            "signal_delta": 0.0,
            "confidence_delta": 0.0,
            "direction_change": False,
            "off_signal": 0.0,
            "on_signal": 0.0,
            "off_confidence": 0.0,
            "on_confidence": 0.0,
        },
    ]
    report = _render_report("MNQ", 7, rows, "2026-05-20_1300")

    assert "MNQ" in report
    assert "Summary stats" in report
    assert "Per-run detail" in report
    # Direction change count should appear
    assert "1 / 2" in report


def test_render_report_direction_change_flagged_as_yes() -> None:
    """A direction change row is rendered with 'YES' in the table."""
    rows = [
        {
            "signal_delta": -0.8,
            "confidence_delta": 0.3,
            "direction_change": True,
            "off_signal": 0.4,
            "on_signal": -0.4,
            "off_confidence": 0.2,
            "on_confidence": 0.5,
        }
    ]
    report = _render_report("MCL", 1, rows, "2026-05-20_1400")
    assert "YES" in report
