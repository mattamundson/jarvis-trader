"""
Point-in-time pins for open validation defects #751 (IB) and #752 (VWAP).

Each test states the CORRECT causal behaviour and is marked
``xfail(strict=True)`` because current code violates it. That is deliberate:

* while the defect exists the test is an expected failure (suite stays green);
* the moment someone changes the production function so the behaviour becomes
  causal, the test XPASSes and strict mode FAILS the suite. That forces the
  fixer to delete the marker in the same PR -- and the issues require any such
  fix to re-run the affected WFO / gate-v2 verdicts rather than silently keep
  prior certifications.

Impact quantification: ``engine/scripts/audit_lookahead_defects_751_752.py``.
All frames are synthetic; no data files or network.
"""

from __future__ import annotations

import pandas as pd
import pytest

from backtest.ib_signals import compute_initial_balance
from backtest.vwap_signals import generate_vwap_signals

CT = "America/Chicago"
ET = "America/New_York"


def _bars(rows: list[tuple[str, float, float, float]], tz: str) -> pd.DataFrame:
    """rows: (HH:MM, high, low, close) on 2026-01-05 in *tz*."""
    idx = pd.DatetimeIndex([pd.Timestamp(f"2026-01-05 {t}", tz=tz) for t, *_ in rows])
    return pd.DataFrame(
        {
            "open": [c for *_, c in rows],
            "high": [h for _, h, _, _ in rows],
            "low": [lo for _, _, lo, _ in rows],
            "close": [c for *_, c in rows],
            "volume": [100.0] * len(rows),
        },
        index=idx,
    )


# ---------------------------------------------------------------------------
# #751 -- Initial Balance
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason="#751: completed IB is joined onto premarket rows (future leak)",
)
def test_ib_not_visible_before_market_open():
    # Minimal example from the issue: 08:00 premarket, 09:30/10:00 IB bars (CT).
    df = _bars(
        [("08:00", 101.0, 99.0, 100.0), ("09:30", 105.0, 99.0, 104.0), ("10:00", 104.0, 98.0, 99.0)],
        CT,
    )
    out = compute_initial_balance(df, open_minutes=60, tz=CT)
    premarket = out.loc[pd.Timestamp("2026-01-05 08:00", tz=CT)]
    assert pd.isna(premarket["ib_high"]) and pd.isna(premarket["ib_low"])


@pytest.mark.xfail(
    strict=True,
    reason="#751: premarket close vs future IB consumes the session's fresh-breakout flag",
)
def test_rth_breakout_not_suppressed_by_premarket_cross():
    # Premarket 08:00 closes at 106, above the IB high (105) that only
    # completes at 10:30. The first *post-IB* close above 105 (10:30 bar)
    # must be the fresh breakout; with the leak, the 08:00 bar takes it.
    df = _bars(
        [
            ("08:00", 107.0, 105.0, 106.0),
            ("09:30", 105.0, 99.0, 104.0),
            ("10:00", 104.0, 98.0, 99.0),
            ("10:30", 108.0, 104.0, 107.0),
        ],
        CT,
    )
    out = compute_initial_balance(df, open_minutes=60, tz=CT)
    assert bool(out.loc[pd.Timestamp("2026-01-05 10:30", tz=CT), "ib_high_fresh_breakout"])


def test_ib_levels_frozen_after_window_close():
    """Non-defect control: post-IB behaviour is correct today and must stay so."""
    df = _bars(
        [("09:30", 105.0, 99.0, 104.0), ("10:00", 104.0, 98.0, 99.0), ("10:30", 108.0, 104.0, 107.0)],
        CT,
    )
    out = compute_initial_balance(df, open_minutes=60, tz=CT)
    post = out.loc[pd.Timestamp("2026-01-05 10:30", tz=CT)]
    assert (post["ib_high"], post["ib_low"]) == (105.0, 98.0)
    assert bool(post["ib_high_fresh_breakout"])


# ---------------------------------------------------------------------------
# #752 -- VWAP
# ---------------------------------------------------------------------------


def _overnight_frame_with_premarket_stretch() -> pd.DataFrame:
    """20 flat overnight hourly bars, then a premarket bar far below VWAP."""
    idx = pd.date_range("2026-01-04 12:00", periods=20, freq="h", tz=ET)  # ends 07:00 ET
    df = pd.DataFrame(
        {"open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0, "volume": 100.0}, index=idx
    )
    stretch = pd.Timestamp("2026-01-05 08:00", tz=ET)
    df.loc[stretch] = {"open": 95.0, "high": 95.5, "low": 90.0, "close": 90.5, "volume": 100.0}
    return df.sort_index()


@pytest.mark.xfail(
    strict=True,
    reason="#752: VWAP signals are eligible 00:00-08:59 ET on near-continuous Globex bars",
)
def test_vwap_no_entry_before_rth_open():
    out = generate_vwap_signals(
        _overnight_frame_with_premarket_stretch(), band_mult=1.5, require_reversal_bar=False
    )
    et_hour = out.index.tz_convert(ET).hour
    premarket_entries = out.loc[et_hour < 9, "vwap_signal"].isin(["LONG_ENTRY", "SHORT_ENTRY"])
    assert not premarket_entries.any()


def test_vwap_premarket_fixture_actually_stretches_below_band():
    """Guard that the xfail above fails for the defect, not for a flat fixture."""
    out = generate_vwap_signals(
        _overnight_frame_with_premarket_stretch(), band_mult=1.5, require_reversal_bar=False
    )
    row = out.loc[pd.Timestamp("2026-01-05 08:00", tz=ET)]
    assert row["close"] < row["vwap_lower"]
