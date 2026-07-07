"""Tests for the Saty ATR Levels port (backtest/indicators.py)."""

from __future__ import annotations

import math

from backtest.indicators import (
    SATY_ATR_RATIOS,
    saty_atr_levels,
    saty_bias,
    saty_nearest_target,
)

# Anchor to the live 2026-06-12 /ES screenshot: prior_close 7398.25, ATR 111.82.
PC = 7398.25
ATR = 111.82


def test_levels_match_live_screenshot():
    lv = saty_atr_levels(PC, ATR)
    assert math.isclose(lv["call_trigger"], 7424.64, abs_tol=0.01)
    assert math.isclose(lv["put_trigger"], 7371.86, abs_tol=0.01)
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
    for r in SATY_ATR_RATIOS:
        assert lv["upper"][r] > PC
        assert lv["lower"][r] < PC


def test_zero_atr_is_safe():
    lv = saty_atr_levels(PC, 0.0)
    assert lv["atr"] == 0.0
    assert saty_bias(PC + 50, lv) == "neutral"
    assert saty_nearest_target(PC, "long", lv) is None


def test_bias_long_short_neutral():
    lv = saty_atr_levels(PC, ATR)
    assert saty_bias(lv["call_trigger"] + 1, lv) == "long"
    assert saty_bias(lv["put_trigger"] - 1, lv) == "short"
    # Inside the trigger band -> no edge.
    assert saty_bias(PC, lv) == "neutral"


def test_bias_at_live_price_is_long():
    lv = saty_atr_levels(PC, ATR)
    assert saty_bias(7427.5, lv) == "long"  # just above the call trigger


def test_nearest_target_is_next_level_in_direction():
    lv = saty_atr_levels(PC, ATR)
    # Long from 7427.5 -> next overhead level is +0.382 ATR (7440.97).
    t = saty_nearest_target(7427.5, "long", lv)
    assert math.isclose(t, lv["upper"][0.382], rel_tol=1e-9)
    # Short from 7360 -> next level below is -0.618 ATR.
    t2 = saty_nearest_target(7360.0, "short", lv)
    assert t2 < 7360.0
    assert t2 in lv["lower"].values()


def test_nearest_target_none_beyond_band():
    lv = saty_atr_levels(PC, ATR)
    # Above the +2.0 ATR ceiling -> nothing higher.
    assert saty_nearest_target(lv["upper"][2.0] + 10, "long", lv) is None
