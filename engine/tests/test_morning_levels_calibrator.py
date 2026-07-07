"""Tests for the morning-forecast calibrator (Phase E) and its Read feedback loop."""

from __future__ import annotations

import asyncio
from datetime import date

from analysis.jarvis_read import generate_read
from analytics.morning_levels_calibrator import (
    build_state,
    calibration_hint,
    render_report,
    summarize_level_stats,
    summarize_read_calibration,
)


def _read_row(conviction, score, brier):
    return {"conviction": conviction, "read_score": score, "read_brier": brier}


def _level_row(touched, up_hit, up_tot, down_hit, down_tot, rva):
    return {
        "level_scores": {
            "graded": True,
            "touched": touched,
            "up_targets_hit": up_hit,
            "up_targets_total": up_tot,
            "down_targets_hit": down_hit,
            "down_targets_total": down_tot,
            "range_vs_atr": rva,
        }
    }


# ---------------------------------------------------------------------------
# summarize_read_calibration
# ---------------------------------------------------------------------------


def test_read_calibration_tiers_and_overall():
    rows = [
        _read_row(0.2, 1.0, 0.64),  # low
        _read_row(0.5, 0.0, 0.25),  # mid
        _read_row(0.8, 1.0, 0.04),  # high
    ]
    out = summarize_read_calibration(rows)
    assert out["n_scored"] == 3
    assert out["overall_accuracy"] == round(2 / 3, 3)
    assert out["tiers"]["low"]["n"] == 1
    assert out["tiers"]["high"]["accuracy"] == 1.0


def test_read_calibration_detects_overconfidence_and_shrinks():
    # 6 high-conviction reads, mostly wrong -> overconfident, shrink < 1.
    rows = [_read_row(0.9, 0.0, 0.81) for _ in range(5)] + [_read_row(0.9, 1.0, 0.01)]
    out = summarize_read_calibration(rows)
    assert out["overconfident"] is True
    assert 0.3 <= out["conviction_shrink"] < 1.0


def test_read_calibration_muted_below_min_samples():
    rows = [_read_row(0.9, 0.0, 0.81) for _ in range(3)]  # < _MIN_SAMPLES
    out = summarize_read_calibration(rows)
    assert out["overconfident"] is False
    assert out["conviction_shrink"] == 1.0


# ---------------------------------------------------------------------------
# summarize_level_stats + recommendations
# ---------------------------------------------------------------------------


def test_level_stats_touch_and_target_rates():
    rows = [
        _level_row({"pivot": True, "r1": False, "s1": True}, 3, 3, 0, 3, 1.6),
        _level_row({"pivot": True, "r1": True, "s1": False}, 3, 3, 1, 3, 1.4),
    ]
    out = summarize_level_stats(rows)
    assert out["n"] == 2
    assert out["touch_rates"]["pivot"] == 1.0
    assert out["up_target_hit_rate"] == 1.0  # 6/6
    assert out["mean_range_vs_atr"] == 1.5


def test_level_stats_empty():
    assert summarize_level_stats([])["n"] == 0


def test_build_state_and_render():
    rows = [
        _read_row(0.8, 1.0, 0.04) | _level_row({"pivot": True}, 1, 3, 0, 3, 1.0) for _ in range(6)
    ]
    state = build_state(rows, 30, date(2026, 6, 25))
    assert state["n_graded_rows"] == 6
    md = render_report(state)
    assert "Forecast Calibration" in md
    assert "Conviction tier" in md


# ---------------------------------------------------------------------------
# calibration_hint
# ---------------------------------------------------------------------------


def test_calibration_hint_empty_below_min():
    state = build_state([_read_row(0.8, 1.0, 0.04) for _ in range(3)], 30, date(2026, 6, 25))
    assert calibration_hint(state) == ""


def test_calibration_hint_mentions_overconfidence():
    rows = [_read_row(0.9, 0.0, 0.81) for _ in range(6)]
    state = build_state(rows, 30, date(2026, 6, 25))
    hint = calibration_hint(state)
    assert "OVERCONFIDENT" in hint


# ---------------------------------------------------------------------------
# end-to-end calibrate over a tmp DB
# ---------------------------------------------------------------------------


def test_calibrate_end_to_end(tmp_path):
    from analysis.forecast_journal import update_outcome, upsert_forecast
    from analytics.morning_levels_calibrator import calibrate

    db = tmp_path / "j.db"
    levels = {"pivot": 100.0, "atr": 10.0, "targets_up": [105.0], "targets_down": [95.0]}
    # Seed 6 graded MES rows in late June 2026.
    for i in range(6):
        d = f"2026-06-{10 + i:02d}"
        upsert_forecast(
            d,
            "MES",
            levels,
            f"{d}T12:00:00Z",
            read={"bias": "bullish", "conviction": 0.8},
            db_path=db,
        )
        actual = {"open": 100.0, "high": 106.0, "low": 98.0, "close": 104.0}
        update_outcome(
            d,
            "MES",
            actual,
            f"{d}T21:00:00Z",
            level_scores={
                "graded": True,
                "touched": {"pivot": True},
                "up_targets_hit": 1,
                "up_targets_total": 1,
                "down_targets_hit": 0,
                "down_targets_total": 1,
                "range_vs_atr": 0.8,
            },
            read_score=1.0,
            read_brier=0.04,
            db_path=db,
        )
    state = calibrate(60, end_date=date(2026, 6, 25), db_path=db)
    assert state["n_graded_rows"] == 6
    assert state["read_calibration"]["overall_accuracy"] == 1.0


# ---------------------------------------------------------------------------
# Read consumes calibration feedback
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, content):
        self.success = True
        self.content = content


class _FakeClient:
    def __init__(self, content):
        self._content = content
        self.calls = []

    async def call(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeResult(self._content)


def test_generate_read_applies_conviction_shrink():
    import json

    client = _FakeClient(json.dumps({"bias": "bullish", "conviction": 0.8}))
    out = asyncio.run(
        generate_read(
            "2026-06-25", {"MES": {"pivot": 1.0}}, None, llm_client=client, conviction_shrink=0.5
        )
    )
    assert out["conviction"] == 0.4  # 0.8 * 0.5
    assert out["conviction_shrunk"] is True


def test_generate_read_hint_in_prompt():
    import json

    client = _FakeClient(json.dumps({"bias": "neutral", "conviction": 0.3}))
    asyncio.run(
        generate_read(
            "2026-06-25",
            {"MES": {"pivot": 1.0}},
            None,
            llm_client=client,
            calibration_hint="You have been OVERCONFIDENT.",
        )
    )
    sent = client.calls[0]["messages"][0]["content"]
    assert "OVERCONFIDENT" in sent
