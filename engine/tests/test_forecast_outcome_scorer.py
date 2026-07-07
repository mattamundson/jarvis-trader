"""Tests for the evening forecast outcome scorer (Phase D).

Pure grading functions (grade_levels, grade_read) need no DB/LLM. score_date is
exercised end-to-end against a tmp_path DB seeded with a forecast row and a
monkeypatched actual-OHLC fetch.
"""

from __future__ import annotations

from datetime import date

import pytest

from scripts.forecast_outcome_scorer import (
    grade_levels,
    grade_read,
    render_report,
    score_date,
)

_LEVELS = {
    "pivot": 100.0,
    "r1": 110.0,
    "s1": 90.0,
    "r2": 120.0,
    "s2": 80.0,
    "atr": 10.0,
    "targets_up": [105.0, 112.0, 125.0],
    "targets_down": [95.0, 88.0, 70.0],
}


# ---------------------------------------------------------------------------
# grade_levels
# ---------------------------------------------------------------------------


def test_grade_levels_touch_and_targets():
    actual = {"open": 100.0, "high": 113.0, "low": 92.0, "close": 111.0}
    out = grade_levels(_LEVELS, actual)
    assert out["graded"] is True
    # pivot 100, r1 110, s1 90? low 92 so s1 90 NOT touched; r2 120 not touched
    assert out["touched"]["pivot"] is True
    assert out["touched"]["r1"] is True
    assert out["touched"]["s1"] is False
    assert out["touched"]["r2"] is False
    # up targets <=113: 105,112 hit; 125 not -> 2
    assert out["up_targets_hit"] == 2
    # down targets >=92: 95 hit (low 92<=95); 88,70 not -> 1
    assert out["down_targets_hit"] == 1
    assert out["range_vs_atr"] == pytest.approx((113.0 - 92.0) / 10.0, rel=1e-3)
    assert out["close_vs_pivot"] == "above"


def test_grade_levels_no_levels():
    assert grade_levels(None, {"open": 1, "high": 2, "low": 0, "close": 1})["graded"] is False


def test_grade_levels_close_below_pivot():
    actual = {"open": 100.0, "high": 101.0, "low": 95.0, "close": 96.0}
    out = grade_levels(_LEVELS, actual)
    assert out["close_vs_pivot"] == "below"


# ---------------------------------------------------------------------------
# grade_read
# ---------------------------------------------------------------------------


def test_grade_read_bullish_correct():
    read = {"bias": "bullish", "conviction": 0.8}
    actual = {"open": 100.0, "high": 110.0, "low": 99.0, "close": 108.0}  # up
    score, brier = grade_read(read, actual)
    assert score == 1.0
    assert brier == pytest.approx((0.8 - 1.0) ** 2, rel=1e-6)


def test_grade_read_bearish_wrong():
    read = {"bias": "bearish", "conviction": 0.9}
    actual = {"open": 100.0, "high": 110.0, "low": 99.0, "close": 108.0}  # up, but called down
    score, brier = grade_read(read, actual)
    assert score == 0.0
    assert brier == pytest.approx((0.9 - 0.0) ** 2, rel=1e-6)


def test_grade_read_neutral_not_scored():
    read = {"bias": "neutral", "conviction": 0.5}
    actual = {"open": 100.0, "high": 110.0, "low": 99.0, "close": 108.0}
    assert grade_read(read, actual) == (None, None)


def test_grade_read_absent():
    assert grade_read(None, {"open": 1, "high": 2, "low": 0, "close": 1}) == (None, None)


def test_grade_read_flat_session():
    read = {"bias": "bullish", "conviction": 0.6}
    actual = {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0}  # flat
    score, brier = grade_read(read, actual)
    assert score == 0.5
    assert brier == pytest.approx((0.6 - 0.5) ** 2, rel=1e-6)


# ---------------------------------------------------------------------------
# score_date end-to-end (tmp DB + monkeypatched OHLC)
# ---------------------------------------------------------------------------


def test_score_date_persists_outcome(tmp_path, monkeypatch):
    import scripts.forecast_outcome_scorer as scorer
    from analysis.forecast_journal import get_forecast, upsert_forecast

    db = tmp_path / "j.db"
    d = "2026-06-25"
    read = {"bias": "bearish", "conviction": 0.7}
    upsert_forecast(d, "MES", _LEVELS, "2026-06-25T12:00:00Z", read=read, db_path=db)

    # Bearish call; make the session go DOWN so the read is correct.
    actual = {"open": 100.0, "high": 101.0, "low": 88.0, "close": 90.0}
    monkeypatch.setattr(scorer, "fetch_actual_ohlc", lambda sym, td, db_path=None: actual)

    results = score_date(date(2026, 6, 25), symbols=("MES",), db_path=db)
    assert len(results) == 1
    assert results[0]["read_score"] == 1.0  # bearish + down = correct

    row = get_forecast(d, "MES", db_path=db)
    assert row["actual_close"] == 90.0
    assert row["read_score"] == 1.0
    assert row["level_scores"]["close_vs_pivot"] == "below"

    md = render_report(date(2026, 6, 25), results)
    assert "Forecast Scorecard" in md
    assert "CORRECT" in md


def test_default_score_date_picks_latest_completed(tmp_path):
    from datetime import datetime, timedelta

    import scripts.forecast_outcome_scorer as scorer
    from analysis.forecast_journal import upsert_forecast

    today = datetime.now(scorer._ET).date()
    yest = today - timedelta(days=1)
    two = today - timedelta(days=2)
    db = tmp_path / "j.db"
    lv = {"pivot": 1.0}
    upsert_forecast(two.isoformat(), "MES", lv, "t", db_path=db)
    upsert_forecast(yest.isoformat(), "MES", lv, "t", db_path=db)
    upsert_forecast(today.isoformat(), "MES", lv, "t", db_path=db)  # today excluded (partial)
    assert scorer._default_score_date(db_path=db) == yest


def test_default_score_date_empty_journal_falls_back_yesterday(tmp_path):
    from datetime import datetime, timedelta

    import scripts.forecast_outcome_scorer as scorer

    today = datetime.now(scorer._ET).date()
    assert scorer._default_score_date(db_path=tmp_path / "empty.db") == today - timedelta(days=1)


def test_score_date_no_actual(tmp_path, monkeypatch):
    import scripts.forecast_outcome_scorer as scorer
    from analysis.forecast_journal import upsert_forecast

    db = tmp_path / "j.db"
    upsert_forecast("2026-06-25", "MES", _LEVELS, "2026-06-25T12:00:00Z", db_path=db)
    monkeypatch.setattr(scorer, "fetch_actual_ohlc", lambda sym, td, db_path=None: None)
    results = score_date(date(2026, 6, 25), symbols=("MES",), db_path=db)
    assert results[0]["graded"] is False
