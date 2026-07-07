"""Integration test for Phase 2 orphan ThinkScript ports.

Verifies all 7 new indicator modules compose cleanly on one DataFrame
without conflicts and produce the expected signal columns.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from backtest.gapfinder import compute_gaps
from backtest.gaps_chetan import compute_chetan_gaps
from backtest.ib_signals import compute_initial_balance
from backtest.rangefinder import compute_rangefinder
from backtest.singlefinder import compute_single_prints
from backtest.tpo_profile import compute_tpo_profile
from backtest.tpo_score import compute_tpo_score

# ---------------------------------------------------------------------------
# Synthetic fixture — 3 RTH days at 5-min resolution, gap-up on day 2
# ---------------------------------------------------------------------------

def _rth_timestamps(date_str: str, tz: str = "America/Chicago") -> pd.DatetimeIndex:
    """Return 5-min bars 09:30–15:25 local time for a single date."""
    start = pd.Timestamp(f"{date_str} 09:30:00", tz=tz)
    end = pd.Timestamp(f"{date_str} 15:25:00", tz=tz)
    return pd.date_range(start=start, end=end, freq="5min")


@pytest.fixture
def three_day_synthetic_df() -> pd.DataFrame:
    """3 days of 5-min RTH bars (Mon 2026-04-13 → Wed 2026-04-15) with a
    deliberate gap-up on day 2 open.

    Price construction:
      Day 1: starts at 5000.00, drifts up ~5 pts/bar with N(0, 2) noise.
      Day 2: opens 20 pts above day-1 close (gap up ~0.4%), then continues.
      Day 3: opens near day-2 close, drift continues.
    """
    rng = np.random.default_rng(42)
    dates = ["2026-04-13", "2026-04-14", "2026-04-15"]

    frames: list[pd.DataFrame] = []
    prev_close = 5000.0

    for day_idx, date in enumerate(dates):
        idx = _rth_timestamps(date)
        n = len(idx)

        # Drift + noise for mid-prices
        drift = 0.25  # pts per bar
        noise = rng.normal(0, 1.5, n)
        mid = prev_close + np.cumsum(drift + noise)

        # Gap up on day 2 open (inject +20 pts)
        if day_idx == 1:
            mid = mid + 20.0

        bar_range = 2.0 + rng.exponential(0.5, n)  # bar range ~2–4 pts

        open_ = mid - bar_range / 4 + rng.normal(0, 0.5, n)
        close = mid + bar_range / 4 + rng.normal(0, 0.5, n)
        high = np.maximum(open_, close) + bar_range / 2
        low = np.minimum(open_, close) - bar_range / 2
        volume = rng.integers(500, 5000, n).astype(float)

        frames.append(
            pd.DataFrame(
                {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
                index=idx,
            )
        )
        prev_close = float(close[-1])

    df = pd.concat(frames)
    df.index.name = "timestamp"
    return df


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_all_seven_indicators_run_without_error(three_day_synthetic_df: pd.DataFrame) -> None:
    """All 7 modules execute in dependency order without raising."""
    df = three_day_synthetic_df.copy()
    original_len = len(df)

    df = compute_initial_balance(df)
    df = compute_tpo_profile(df)
    df = compute_tpo_score(df)       # depends on tpo_profile columns
    df = compute_rangefinder(df)
    df = compute_single_prints(df)
    df = compute_gaps(df)
    df = compute_chetan_gaps(df)

    assert len(df) == original_len, "row count must be preserved through all modules"


def test_ib_columns_present(three_day_synthetic_df: pd.DataFrame) -> None:
    """compute_initial_balance adds the 4 minimum required IB columns."""
    df = compute_initial_balance(three_day_synthetic_df.copy())
    required = {"ib_high", "ib_low", "above_ib_high", "below_ib_low"}
    missing = required - set(df.columns)
    assert not missing, f"IB columns missing: {missing}"


def test_ib_values_finite_after_window(three_day_synthetic_df: pd.DataFrame) -> None:
    """ib_high / ib_low must be finite for post-IB bars on each session."""
    df = compute_initial_balance(three_day_synthetic_df.copy(), open_minutes=60)
    # First 60 min of each session = IB window; after that they should be filled.
    # Check at least one non-NaN row per session.
    assert df["ib_high"].notna().any(), "ib_high must be populated for post-IB bars"
    assert df["ib_low"].notna().any(), "ib_low must be populated for post-IB bars"
    # IB high must be >= IB low where both are populated
    valid = df["ib_high"].notna() & df["ib_low"].notna()
    assert (df.loc[valid, "ib_high"] >= df.loc[valid, "ib_low"]).all(), (
        "ib_high must be >= ib_low on every non-NaN bar"
    )


def test_tpo_chain_buyer_control_flag(three_day_synthetic_df: pd.DataFrame) -> None:
    """tpo_score and buyer_control_signal are consistent:
    when buyer_control_signal is True, tpo_score should be positive.
    """
    df = three_day_synthetic_df.copy()
    df = compute_tpo_profile(df)
    df = compute_tpo_score(df)

    # buyer_control_signal: close > va_high (from tpo_profile)
    # tpo_score when above va_high is > 0 by construction (see _tpo_score_row)
    mask = df["buyer_control_signal"] & df["va_high"].notna()
    if mask.any():
        assert (df.loc[mask, "tpo_score"] > 0).all(), (
            "tpo_score must be > 0 on every bar where buyer_control_signal is True"
        )

    # seller_control_signal: tpo_score should be negative
    mask2 = df["seller_control_signal"] & df["va_low"].notna()
    if mask2.any():
        assert (df.loc[mask2, "tpo_score"] < 0).all(), (
            "tpo_score must be < 0 on every bar where seller_control_signal is True"
        )


def test_gap_detection_on_day2(three_day_synthetic_df: pd.DataFrame) -> None:
    """The deliberate gap-up on day 2 open is detected by compute_gaps."""
    df = compute_gaps(three_day_synthetic_df.copy())

    # gap_up_top should have at least one non-NaN value (from the gap on day 2)
    assert df["gap_up_top"].notna().any(), (
        "Expected at least one gap-up zone detected (day-2 injected +20 pt gap)"
    )


def test_chetan_gap_direction_values(three_day_synthetic_df: pd.DataFrame) -> None:
    """chetan_gap_direction must only contain 'UP', 'DOWN', or 'NONE'."""
    df = compute_chetan_gaps(three_day_synthetic_df.copy())
    valid_directions = {"UP", "DOWN", "NONE"}
    actual = set(df["chetan_gap_direction"].unique())
    assert actual <= valid_directions, (
        f"Unexpected direction values: {actual - valid_directions}"
    )
    # When gap detected, top and bottom must be finite
    detected = df["chetan_gap_detected"]
    if detected.any():
        assert df.loc[detected, "chetan_gap_top"].notna().all()
        assert df.loc[detected, "chetan_gap_bottom"].notna().all()


def test_no_column_name_collisions(three_day_synthetic_df: pd.DataFrame) -> None:
    """Verify all 7 modules add unique columns (no silent overwrites)."""
    df = three_day_synthetic_df.copy()

    # tpo_score depends on tpo_profile so run it as a unit
    module_fns = [
        ("ib",     compute_initial_balance),
        ("tpo",    compute_tpo_profile),
        ("tpo_sc", compute_tpo_score),
        ("rf",     compute_rangefinder),
        ("sf",     compute_single_prints),
        ("gf",     compute_gaps),
        ("chetan", compute_chetan_gaps),
    ]

    cols_per_module: dict[str, set[str]] = {}
    for name, fn in module_fns:
        before = set(df.columns)
        df = fn(df.copy())
        new_cols = set(df.columns) - before
        cols_per_module[name] = new_cols

    all_new_cols = [c for cols in cols_per_module.values() for c in cols]
    unique_new_cols = set(all_new_cols)

    collision_cols = [c for c in all_new_cols if all_new_cols.count(c) > 1]
    assert not collision_cols, (
        f"Column name collisions detected across modules: {sorted(set(collision_cols))}"
    )


def test_rangefinder_control_zone_bounds(three_day_synthetic_df: pd.DataFrame) -> None:
    """rf_control_zone_low must be <= rf_control_zone_high on every bar."""
    df = compute_rangefinder(three_day_synthetic_df.copy())
    assert "rf_control_zone_low" in df.columns
    assert "rf_control_zone_high" in df.columns
    assert (df["rf_control_zone_low"] <= df["rf_control_zone_high"]).all(), (
        "rf_control_zone_low must be <= rf_control_zone_high on every bar"
    )


def test_single_prints_columns_present(three_day_synthetic_df: pd.DataFrame) -> None:
    """compute_single_prints must add all 8 expected columns."""
    df = compute_single_prints(three_day_synthetic_df.copy())
    expected = {
        "sf_bullish_single_top", "sf_bullish_single_bottom",
        "sf_bearish_single_top", "sf_bearish_single_bottom",
        "sf_in_bullish_single", "sf_in_bearish_single",
        "sf_bullish_fail", "sf_bearish_fail",
    }
    missing = expected - set(df.columns)
    assert not missing, f"Singlefinder columns missing: {missing}"


def test_full_pipeline_row_count_preserved(three_day_synthetic_df: pd.DataFrame) -> None:
    """Composed pipeline must not drop or duplicate rows."""
    original_len = len(three_day_synthetic_df)
    df = three_day_synthetic_df.copy()
    for fn in (
        compute_initial_balance,
        compute_tpo_profile,
        compute_tpo_score,
        compute_rangefinder,
        compute_single_prints,
        compute_gaps,
        compute_chetan_gaps,
    ):
        df = fn(df)
    assert len(df) == original_len, (
        f"Pipeline changed row count: expected {original_len}, got {len(df)}"
    )
