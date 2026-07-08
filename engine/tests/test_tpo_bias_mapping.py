"""Tests for the tpo_profile -> auction_bias "tpo" dict mapping.

Fixture derived algebraically from the 2026-07-08 chart (see
analysis/tpo_bias_mapping.py docstring): poc=7550, bull-imbalance,
target=up_move=7624.25, fail_target=down_move=7529.75.
"""

from __future__ import annotations

from analysis.tpo_bias_mapping import derive_tpo_failed, row_to_tpo_dict

TARGET = 7624.25
FAIL_TARGET = 7529.75


def test_bull_imbalance_failed_once_price_trades_through_fail_target():
    # Matches the chart: last 7526.75 <= fail_target 7529.75 -> failed.
    assert derive_tpo_failed("BULL_IMBAL", close=7526.75, fail_target=FAIL_TARGET) is True


def test_bull_imbalance_not_failed_while_above_fail_target():
    assert derive_tpo_failed("BULL_IMBAL", close=7535.0, fail_target=FAIL_TARGET) is False


def test_bear_imbalance_failed_once_price_trades_through_fail_target():
    # Symmetric case: bear-imbalance fails when price rallies through fail_target.
    assert derive_tpo_failed("BEAR_IMBAL", close=7535.0, fail_target=7530.0) is True


def test_bear_imbalance_not_failed_while_below_fail_target():
    assert derive_tpo_failed("BEAR_IMBAL", close=7520.0, fail_target=7530.0) is False


def test_unknown_imbalance_is_not_failed():
    assert derive_tpo_failed("", close=7526.75, fail_target=FAIL_TARGET) is False


def test_row_to_tpo_dict_matches_chart_fixture():
    tpo = row_to_tpo_dict(
        close=7526.75,
        va_high=7560.0,
        va_low=7530.0,
        profile_target=TARGET,
        fail_target=FAIL_TARGET,
        imbalance="BULL_IMBAL",
    )
    assert tpo is not None
    assert tpo["profile_target"] == TARGET
    assert tpo["fail_target"] == FAIL_TARGET
    assert tpo["failed"] is True


def test_row_to_tpo_dict_none_when_profile_undefined():
    # compute_tpo_profile leaves target/fail_target NaN until a prior session
    # exists (first session in the loaded window) -> caller passes None.
    assert row_to_tpo_dict(7526.75, None, None, None, None, None) is None
