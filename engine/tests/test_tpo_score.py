"""
JARVIS TRADER — TPO Score Unit Tests
Tests for engine/backtest/tpo_score.py

Mock DataFrames supply vpoc/va_high/va_low directly;
no dependency on engine/backtest/tpo_profile.py computation.
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backtest.tpo_score import compute_tpo_score


def _make_df(**kwargs) -> pd.DataFrame:
    base = {"vpoc": [100.0], "va_high": [105.0], "va_low": [95.0], "close": [100.0]}
    base.update(kwargs)
    return pd.DataFrame(base)


# ── score at VPOC is 0 ────────────────────────────────────────────────────────

def test_score_at_vpoc_is_zero():
    df = _make_df(close=[100.0], vpoc=[100.0], va_high=[105.0], va_low=[95.0])
    result = compute_tpo_score(df)
    assert result["tpo_score"].iloc[0] == pytest.approx(0.0, abs=1e-9)


# ── close above VAH → positive score ─────────────────────────────────────────

def test_score_above_vah_is_positive():
    df = _make_df(close=[110.0], vpoc=[100.0], va_high=[105.0], va_low=[95.0])
    result = compute_tpo_score(df)
    assert result["tpo_score"].iloc[0] > 0.0


def test_score_above_vah_capped_at_one():
    # very far above VAH — score should not exceed 1.0
    df = _make_df(close=[999.0], vpoc=[100.0], va_high=[105.0], va_low=[95.0])
    result = compute_tpo_score(df)
    assert result["tpo_score"].iloc[0] == pytest.approx(1.0)


# ── close below VAL → negative score ─────────────────────────────────────────

def test_score_below_val_is_negative():
    df = _make_df(close=[90.0], vpoc=[100.0], va_high=[105.0], va_low=[95.0])
    result = compute_tpo_score(df)
    assert result["tpo_score"].iloc[0] < 0.0


def test_score_below_val_capped_at_minus_one():
    df = _make_df(close=[-999.0], vpoc=[100.0], va_high=[105.0], va_low=[95.0])
    result = compute_tpo_score(df)
    assert result["tpo_score"].iloc[0] == pytest.approx(-1.0)


# ── tpo_score_label thresholds ────────────────────────────────────────────────

def test_label_buyers_control_at_high_positive():
    # score == 1.0 → BUYERS_CONTROL
    df = _make_df(close=[999.0], vpoc=[100.0], va_high=[105.0], va_low=[95.0])
    result = compute_tpo_score(df)
    assert result["tpo_score_label"].iloc[0] == "BUYERS_CONTROL"


def test_label_sellers_control_at_minus_one():
    df = _make_df(close=[-999.0], vpoc=[100.0], va_high=[105.0], va_low=[95.0])
    result = compute_tpo_score(df)
    assert result["tpo_score_label"].iloc[0] == "SELLERS_CONTROL"


def test_label_neutral_at_vpoc():
    df = _make_df(close=[100.0], vpoc=[100.0], va_high=[105.0], va_low=[95.0])
    result = compute_tpo_score(df)
    assert result["tpo_score_label"].iloc[0] == "NEUTRAL"


def test_label_buyers_lean_in_upper_value_area():
    # close between VPOC and VAH but not past 0.66 threshold
    # va_range=10, vpoc=100, close=102 → score = 0.5*(2/10)=0.1 → NEUTRAL
    # to get BUYERS_LEAN: score in [0.33, 0.66)
    # inside VA: score = 0.5*(close-vpoc)/va_range
    # 0.5*(close-100)/10 = 0.5 → close = 110, but 110 > va_high=105, switches branch
    # Use wider range: vpoc=100, va_high=120, va_low=80, close=115
    # inside VA: score=0.5*(115-100)/(120-80)=0.5*(15/40)=0.1875 → NEUTRAL
    # Need close > va_high but score < 0.66:
    # score = (close-va_high)/(va_high-vpoc) = (close-120)/20 in [0.33,0.66)
    # close-120 in [6.6, 13.2) → close in [126.6, 133.2)
    df = _make_df(close=[130.0], vpoc=[100.0], va_high=[120.0], va_low=[80.0])
    result = compute_tpo_score(df)
    assert result["tpo_score_label"].iloc[0] == "BUYERS_LEAN"


def test_label_sellers_lean_below_val():
    # score in (-0.66, -0.33]: (close-va_low)/(vpoc-va_low)
    # vpoc=100, va_low=80, close below val:
    # score = (close-80)/(100-80) = (close-80)/20 in (-0.66,-0.33]
    # close in (80-13.2, 80-6.6] = (66.8, 73.4]
    df = _make_df(close=[70.0], vpoc=[100.0], va_high=[120.0], va_low=[80.0])
    result = compute_tpo_score(df)
    assert result["tpo_score_label"].iloc[0] == "SELLERS_LEAN"


# ── price_zone_label ──────────────────────────────────────────────────────────

def test_zone_above_value():
    df = _make_df(close=[115.0], vpoc=[100.0], va_high=[105.0], va_low=[95.0])
    result = compute_tpo_score(df)
    assert result["price_zone_label"].iloc[0] == "ABOVE_VALUE"


def test_zone_below_value():
    df = _make_df(close=[85.0], vpoc=[100.0], va_high=[105.0], va_low=[95.0])
    result = compute_tpo_score(df)
    assert result["price_zone_label"].iloc[0] == "BELOW_VALUE"


def test_zone_in_value():
    df = _make_df(close=[100.0], vpoc=[100.0], va_high=[105.0], va_low=[95.0])
    result = compute_tpo_score(df)
    assert result["price_zone_label"].iloc[0] == "IN_VALUE"


# ── missing columns raises ValueError ────────────────────────────────────────

def test_missing_columns_raises():
    df = pd.DataFrame({"close": [100.0], "vpoc": [100.0]})  # missing va_high, va_low
    with pytest.raises(ValueError, match="missing columns"):
        compute_tpo_score(df)


def test_missing_close_raises():
    df = pd.DataFrame({"vpoc": [100.0], "va_high": [105.0], "va_low": [95.0]})
    with pytest.raises(ValueError, match="missing columns"):
        compute_tpo_score(df)


# ── output shape and columns ──────────────────────────────────────────────────

def test_output_has_three_new_columns():
    df = _make_df()
    result = compute_tpo_score(df)
    for col in ("tpo_score", "tpo_score_label", "price_zone_label"):
        assert col in result.columns


def test_output_length_unchanged():
    rows = 10
    df = pd.DataFrame({
        "vpoc": np.full(rows, 100.0),
        "va_high": np.full(rows, 105.0),
        "va_low": np.full(rows, 95.0),
        "close": np.linspace(90, 115, rows),
    })
    result = compute_tpo_score(df)
    assert len(result) == rows


def test_score_range_clamped():
    rows = 50
    df = pd.DataFrame({
        "vpoc": np.full(rows, 100.0),
        "va_high": np.full(rows, 105.0),
        "va_low": np.full(rows, 95.0),
        "close": np.linspace(50, 150, rows),
    })
    result = compute_tpo_score(df)
    assert result["tpo_score"].between(-1.0, 1.0).all()


def test_original_df_not_mutated():
    df = _make_df()
    original_cols = set(df.columns)
    compute_tpo_score(df)
    assert set(df.columns) == original_cols


def test_tos_score_sign_matches_thinkscript_logic():
    """compute_tpo_score_tos reproduces the TOS 5-component sign."""
    import pandas as pd

    from backtest.tpo_score import compute_tpo_score_tos

    # close above VAH and POC, bull-imbalanced (vabal<poc) -> all bullish -> POSITIVE
    df = pd.DataFrame(
        {"close": [110.0], "vpoc": [100.0], "va_high": [105.0], "va_low": [99.0]}
    )
    out = compute_tpo_score_tos(df)
    assert out["tpo_score_tos_sign"].iloc[0] == "POSITIVE"
    assert out["tpo_score_tos"].iloc[0] > 0

    # close below VAL and POC -> NEGATIVE
    df2 = pd.DataFrame(
        {"close": [90.0], "vpoc": [100.0], "va_high": [105.0], "va_low": [95.0]}
    )
    out2 = compute_tpo_score_tos(df2)
    assert out2["tpo_score_tos_sign"].iloc[0] == "NEGATIVE"
    assert out2["tpo_score_tos"].iloc[0] < 0


def test_tos_score_handles_nan_profile():
    import numpy as np
    import pandas as pd

    from backtest.tpo_score import compute_tpo_score_tos

    df = pd.DataFrame(
        {"close": [100.0], "vpoc": [np.nan], "va_high": [np.nan], "va_low": [np.nan]}
    )
    out = compute_tpo_score_tos(df)
    assert out["tpo_score_tos_sign"].iloc[0] == "NEUTRAL"
    assert np.isnan(out["tpo_score_tos"].iloc[0])
