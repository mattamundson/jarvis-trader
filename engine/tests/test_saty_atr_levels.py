"""Tests for the Saty ATR Levels port (backtest/indicators.py)."""

from __future__ import annotations

import math

from backtest.indicators import (
    SATY_ATR_RATIOS,
    SATY_CHASE_DISPLACEMENT_ATR,
    SATY_CHASE_RANGE_PCT_ATR,
    saty_atr_context,
    saty_atr_levels,
    saty_bias,
    saty_nearest_target,
    saty_trigger_state,
)

# Anchor to the live 2026-06-12 /ES screenshot: prior_close 7398.25, ATR 111.82.
PC = 7398.25
ATR = 111.82


def test_levels_match_live_screenshot():
    lv = saty_atr_levels(PC, ATR)
    assert math.isclose(lv["call_trigger"], 7424.64, abs_tol=0.01)
    assert math.isclose(lv["put_trigger"], 7371.86, abs_tol=0.01)
    assert math.isclose(lv["upper_trigger"], 7424.64, abs_tol=0.01)
    assert math.isclose(lv["lower_trigger"], 7371.86, abs_tol=0.01)
    assert math.isclose(lv["upper"][1.0], 7510.07, abs_tol=0.01)
    assert math.isclose(lv["lower"][1.0], 7286.43, abs_tol=0.01)


def test_triggers_are_symmetric_around_prior_close():
    lv = saty_atr_levels(PC, ATR)
    assert math.isclose(
        lv["call_trigger"] - PC, PC - lv["put_trigger"], rel_tol=1e-9
    )


def test_all_ratios_present_both_sides():
    lv = saty_atr_levels(PC, ATR)
    assert set(lv["upper"]) == set(SATY_ATR_RATIOS)
    assert set(lv["lower"]) == set(SATY_ATR_RATIOS)
    assert 0.5 in lv["upper"]
    assert 1.5 in lv["upper"]
    assert 3.0 in lv["upper"]
    for r in SATY_ATR_RATIOS:
        assert lv["upper"][r] > PC
        assert lv["lower"][r] < PC


def test_tick_rounding_for_futures_levels():
    lv = saty_atr_levels(PC, ATR, tick_size=0.25)
    assert lv["prior_close"] == PC
    assert lv["upper_trigger"] == 7424.75
    assert lv["lower_trigger"] == 7371.75
    assert all(math.isclose(price * 4, round(price * 4), abs_tol=1e-9) for price in lv["upper"].values())


def test_zero_atr_is_safe():
    lv = saty_atr_levels(PC, 0.0)
    assert lv["atr"] == 0.0
    assert saty_bias(PC + 50, lv) == "neutral"
    assert saty_trigger_state(PC + 50, lv) == "neutral"
    assert saty_nearest_target(PC, "long", lv) is None


def test_bias_long_short_neutral_legacy_wrapper():
    lv = saty_atr_levels(PC, ATR)
    assert saty_bias(lv["call_trigger"] + 1, lv) == "long"
    assert saty_bias(lv["put_trigger"] - 1, lv) == "short"
    # Inside the trigger band -> no edge.
    assert saty_bias(PC, lv) == "neutral"


def test_trigger_state_uses_neutral_dashboard_language():
    lv = saty_atr_levels(PC, ATR)
    assert saty_trigger_state(lv["upper_trigger"] + 1, lv) == "upside_trigger"
    assert saty_trigger_state(lv["lower_trigger"] - 1, lv) == "downside_trigger"
    assert saty_trigger_state(PC, lv) == "inside_trigger_band"


def test_bias_at_live_price_is_long():
    lv = saty_atr_levels(PC, ATR)
    assert saty_bias(7427.5, lv) == "long"  # just above the call trigger


def test_nearest_target_is_next_level_in_direction():
    lv = saty_atr_levels(PC, ATR)
    # Long from 7427.5 -> next overhead level is +0.382 ATR (7440.97).
    t = saty_nearest_target(7427.5, "long", lv)
    assert math.isclose(t, lv["upper"][0.382], rel_tol=1e-9)
    # Short from 7360 -> next level below is -0.382 ATR.
    t2 = saty_nearest_target(7360.0, "short", lv)
    assert t2 < 7360.0
    assert math.isclose(t2, lv["lower"][0.382], rel_tol=1e-9)


def test_nearest_target_none_beyond_band():
    lv = saty_atr_levels(PC, ATR)
    # Above the +3.0 ATR ceiling -> nothing higher.
    assert saty_nearest_target(lv["upper"][3.0] + 10, "long", lv) is None


def test_context_reports_displacement_range_gap_and_next_levels():
    ctx = saty_atr_context(
        price=7445.0,
        prior_close=PC,
        atr=ATR,
        period_high=7448.0,
        period_low=7385.0,
        session_open=7420.0,
    )
    assert ctx["state"]["trigger_state"] == "upside_trigger"
    assert ctx["state"]["range_state"] == "initiative_up"
    assert ctx["metrics"]["atr_displacement"] == 0.418
    assert ctx["metrics"]["range_pct_atr"] == 56.3
    assert ctx["metrics"]["gap_atr"] == 0.195
    assert math.isclose(ctx["next_levels"]["up"], ctx["levels"]["upper"][0.5], rel_tol=1e-9)
    assert math.isclose(ctx["next_levels"]["down"], ctx["levels"]["lower"][0.236], rel_tol=1e-9)


def test_context_tags_chase_risk_after_large_atr_move():
    price = PC + (SATY_CHASE_DISPLACEMENT_ATR + 0.02) * ATR
    ctx = saty_atr_context(
        price=price,
        prior_close=PC,
        atr=ATR,
        period_high=PC + 1.0 * ATR,
        period_low=PC,
    )
    assert ctx["metrics"]["range_pct_atr"] == SATY_CHASE_RANGE_PCT_ATR + 10.0
    assert ctx["state"]["chase_risk"] is True
    assert ctx["context_score"]["up"] <= 0  # chase risk offsets an otherwise-valid trigger


def test_context_score_uses_vwap_trend_and_opening_range_confluence():
    ctx = saty_atr_context(
        price=7468.0,
        prior_close=PC,
        atr=ATR,
        period_high=7468.0,
        period_low=7390.0,
        vwap=7425.0,
        fast_ema=7450.0,
        pivot_ema=7430.0,
        slow_ema=7410.0,
        opening_range_high=7440.0,
        opening_range_low=7380.0,
    )
    assert ctx["state"]["trigger_state"] == "upside_trigger"
    assert ctx["state"]["vwap_state"] == "above"
    assert ctx["state"]["trend_ribbon"] == "bullish"
    assert ctx["state"]["opening_range_state"] == "above_orh"
    assert ctx["context_score"] == {"up": 4, "down": 0}


def test_context_zero_atr_shape_is_stable():
    ctx = saty_atr_context(price=PC, prior_close=PC, atr=0.0)
    assert ctx["state"]["range_state"] == "invalid_atr"
    assert ctx["metrics"]["atr_displacement"] == 0.0
    assert ctx["next_levels"] == {"up": None, "down": None}
    assert ctx["context_score"] == {"up": 0, "down": 0}
