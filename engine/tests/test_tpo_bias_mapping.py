"""Tests for the tpo_profile -> auction_bias "tpo" dict mapping.

Fixture derived algebraically from the 2026-07-08 chart (see
analysis/tpo_bias_mapping.py docstring): poc=7550, bull-imbalance,
target=up_move=7624.25, fail_target=down_move=7529.75.
"""

from __future__ import annotations

import pandas as pd

from analysis.tpo_bias_mapping import (
    derive_tpo_failed,
    row_to_tpo_dict,
    session_extreme_since_open,
)

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


def _profile_df(rows):
    """rows: list of (tpo_fail_target, low, high) across bars in chrono order."""
    return pd.DataFrame(rows, columns=["tpo_fail_target", "low", "high"])


def test_session_extreme_finds_breach_that_later_bounced_back():
    # Codex review finding (PR #315): a bull-imbalanced profile (fail_target
    # breach = low <= fail_target) that dipped to 7525 and recovered to 7535
    # must still report the breach -- the LAST bar's low (7534) alone would miss it.
    df = _profile_df(
        [
            (7530.0, 7540, 7545),  # session open
            (7530.0, 7525, 7538),  # breach: low 7525 <= fail_target 7530
            (7530.0, 7534, 7536),  # bounced back above -- last bar
        ]
    )
    extreme = session_extreme_since_open(df, "BULL_IMBAL")
    assert extreme == 7525.0
    assert derive_tpo_failed("BULL_IMBAL", extreme, 7530.0) is True
    # Confirms the bug: using only the last bar's low would have missed it.
    assert derive_tpo_failed("BULL_IMBAL", float(df["low"].iloc[-1]), 7530.0) is False


def test_session_extreme_bear_imbalance_uses_session_high():
    df = _profile_df(
        [
            (7530.0, 7520, 7525),
            (7530.0, 7522, 7534),  # breach: high 7534 >= fail_target 7530
            (7530.0, 7521, 7526),  # pulled back -- last bar
        ]
    )
    extreme = session_extreme_since_open(df, "BEAR_IMBAL")
    assert extreme == 7534.0
    assert derive_tpo_failed("BEAR_IMBAL", extreme, 7530.0) is True


def test_session_extreme_excludes_prior_session_with_different_fail_target():
    # Prior session's fail_target (7500.0) must not leak into the current
    # session's (7530.0) extreme calculation.
    df = _profile_df(
        [
            (7500.0, 7400, 7410),  # prior session -- would wrongly dominate the min
            (7530.0, 7532, 7538),  # current session starts here
            (7530.0, 7531, 7536),
        ]
    )
    assert session_extreme_since_open(df, "BULL_IMBAL") == 7531.0


def test_session_extreme_none_when_profile_undefined():
    df = _profile_df([(float("nan"), 7500, 7510)])
    assert session_extreme_since_open(df, "BULL_IMBAL") is None


def test_session_extreme_none_for_unknown_imbalance():
    df = _profile_df([(7530.0, 7500, 7510)])
    assert session_extreme_since_open(df, "flat") is None
