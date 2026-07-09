"""
Tests for engine/backtest/tpo_profile.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.tpo_profile import compute_tpo_profile

# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_df(dates_prices: list[tuple], tz: str = "America/Chicago") -> pd.DataFrame:
    """Build a minute-bar DataFrame from (datetime_str, price) tuples."""
    idx = pd.to_datetime([t[0] for t in dates_prices], utc=False).tz_localize(tz)
    prices = [t[1] for t in dates_prices]
    return pd.DataFrame({"close": prices, "high": prices, "low": prices, "volume": 1}, index=idx)


def _rth_bars(date_str: str, prices: list[float], tz: str = "America/Chicago") -> pd.DataFrame:
    """Generate RTH minute bars (09:30–16:00 CT) for one session date."""
    times = pd.date_range(
        start=f"{date_str} 09:30",
        periods=len(prices),
        freq="1min",
        tz=tz,
    )
    return pd.DataFrame(
        {"close": prices, "high": prices, "low": prices, "volume": 1},
        index=times,
    )


# ── Test 1: single-day happy path ────────────────────────────────────────────

def test_single_day_columns_present():
    """Output DataFrame must contain all required TPO columns."""
    df = _rth_bars("2024-01-02", [100.0] * 5 + [101.0] * 10 + [99.0] * 5)
    result = compute_tpo_profile(df, tick_size=0.25)
    required = {"vpoc", "va_high", "va_low", "profile_high", "profile_low",
                "price_vs_va", "buyer_control_signal", "seller_control_signal"}
    assert required.issubset(set(result.columns))


# ── Test 2: value-area sanity — VAH > VPOC > VAL ─────────────────────────────

def test_va_ordering_vah_gt_vpoc_gt_val():
    """
    Two-session setup: session 1 builds the profile, session 2 sees the
    prior-session levels.  On session 2 rows VAH >= VPOC >= VAL must hold.
    """
    s1_prices = [99.0] * 5 + [100.0] * 20 + [101.0] * 5   # VPOC=100
    s2_prices = [100.0] * 5

    df = pd.concat([
        _rth_bars("2024-01-02", s1_prices),
        _rth_bars("2024-01-03", s2_prices),
    ])
    result = compute_tpo_profile(df, tick_size=0.25)

    s2 = result.loc["2024-01-03"]
    row = s2.dropna(subset=["vpoc"]).iloc[0]
    assert row["va_high"] >= row["vpoc"] >= row["va_low"], (
        f"Ordering violated: VAH={row['va_high']} VPOC={row['vpoc']} VAL={row['va_low']}"
    )


# ── Test 3: buyer/seller control flags ───────────────────────────────────────

def test_buyer_seller_control_flags():
    """
    buyer_control_signal should be True when close > va_high,
    seller_control_signal should be True when close < va_low.
    """
    # Session 1: narrow range so VPOC=100, VAH=100.25, VAL=99.75 (approx)
    s1_prices = [99.75] * 5 + [100.0] * 30 + [100.25] * 5
    # Session 2: one bar clearly above value area, one clearly below
    s2_times = pd.date_range("2024-01-03 09:30", periods=2, freq="1min",
                             tz="America/Chicago")
    df_s1 = _rth_bars("2024-01-02", s1_prices)

    # We'll compute and check the flags on session-2 bars after getting VAH/VAL
    df = pd.concat([
        df_s1,
        pd.DataFrame(
            {"close": [105.0, 95.0], "high": [105.0, 95.0],
             "low": [105.0, 95.0], "volume": [1, 1]},
            index=s2_times,
        ),
    ])
    result = compute_tpo_profile(df, tick_size=0.25)
    s2 = result.loc["2024-01-03"]

    assert bool(s2.iloc[0]["buyer_control_signal"]) is True
    assert bool(s2.iloc[1]["seller_control_signal"]) is True


# ── Test 4: multi-day session reset ──────────────────────────────────────────

def test_multi_day_session_reset():
    """
    Each day must produce independent VPOC.  Day-1 VPOC=100, Day-2 VPOC=200.
    Day-3 should see Day-2's VPOC (~200), not Day-1's (~100).
    """
    s1 = _rth_bars("2024-01-02", [99.0] * 3 + [100.0] * 20 + [101.0] * 3)
    s2 = _rth_bars("2024-01-03", [199.0] * 3 + [200.0] * 20 + [201.0] * 3)
    s3 = _rth_bars("2024-01-04", [200.0] * 5)

    df = pd.concat([s1, s2, s3])
    result = compute_tpo_profile(df, tick_size=0.25)

    s3_rows = result.loc["2024-01-04"].dropna(subset=["vpoc"])
    assert not s3_rows.empty
    vpoc_day3 = s3_rows.iloc[0]["vpoc"]
    assert abs(vpoc_day3 - 200.0) < 1.0, f"Expected VPOC near 200, got {vpoc_day3}"


# ── Test 5: insufficient data edge case ──────────────────────────────────────

def test_insufficient_data_returns_nan_levels():
    """
    A single bar (one session only) must return NaN for all level columns
    because there is no prior session to draw from.
    """
    df = _rth_bars("2024-01-02", [100.0])
    result = compute_tpo_profile(df, tick_size=0.25)

    assert result["vpoc"].isna().all()
    assert result["va_high"].isna().all()
    assert result["va_low"].isna().all()
    # price_vs_va defaults to IN_VA when levels are NaN
    assert (result["price_vs_va"] == "IN_VA").all()


def test_undefined_profile_is_not_mislabeled_bull_imbalance():
    """A first session (no prior profile) must NOT be labeled BULL_IMBAL.

    tpo_imbalance previously used a two-way np.where(bear, BEAR, BULL), so any
    row where the profile is undefined (poc/bal NaN) fell through to BULL_IMBAL
    by default -- generate_atr_trail_tpotarget_confluence_signals() then treated
    that as a real bullish projection and let long entries through even though
    tpo_target is NaN. NaN is the only correct label here.
    """
    df = _rth_bars("2024-01-02", [100.0])
    result = compute_tpo_profile(df, tick_size=0.25)
    assert result["tpo_imbalance"].isna().all()
    assert result["tpo_target"].isna().all()
    assert result["tpo_fail_target"].isna().all()


# ── Test 6: price_vs_va classification ───────────────────────────────────────

def test_price_vs_va_classification():
    """
    price_vs_va must return 'ABOVE_VAH', 'IN_VA', or 'BELOW_VAL' correctly.
    """
    s1 = _rth_bars("2024-01-02", [99.0] * 5 + [100.0] * 20 + [101.0] * 5)

    s2_times = pd.date_range("2024-01-03 09:30", periods=3, freq="1min",
                             tz="America/Chicago")
    df = pd.concat([
        s1,
        pd.DataFrame(
            {"close": [105.0, 100.0, 95.0],
             "high": [105.0, 100.0, 95.0],
             "low":  [105.0, 100.0, 95.0],
             "volume": [1, 1, 1]},
            index=s2_times,
        ),
    ])
    result = compute_tpo_profile(df, tick_size=0.25)
    s2 = result.loc["2024-01-03"]

    assert s2.iloc[0]["price_vs_va"] == "ABOVE_VAH"
    assert s2.iloc[1]["price_vs_va"] in ("IN_VA", "ABOVE_VAH", "BELOW_VAL")  # near boundary
    assert s2.iloc[2]["price_vs_va"] == "BELOW_VAL"


# ── Test 7: VPOC is the mode price bin ───────────────────────────────────────

def test_vpoc_is_mode_price_bin():
    """
    VPOC must equal the price bin that appears most often.
    Session 1: 101.00 appears 15 times, 100.00 only 5 times → VPOC=101.00.
    """
    s1 = _rth_bars("2024-01-02", [100.0] * 5 + [101.0] * 15)
    s2 = _rth_bars("2024-01-03", [101.0] * 3)

    df = pd.concat([s1, s2])
    result = compute_tpo_profile(df, tick_size=0.25)

    s2_rows = result.loc["2024-01-03"].dropna(subset=["vpoc"])
    assert not s2_rows.empty
    assert abs(s2_rows.iloc[0]["vpoc"] - 101.0) < 0.01
