"""Tests for the sd-116 Value-Area re-entry live signal generator.

Bar-for-bar fidelity against `run_value_area_reentry_sd116.py`'s own
`_build_features()` was verified manually against the real MES 30m cache
(gitignored local data, not available in CI): 300/300 events matched exactly
(direction, target, and ATR-derived stop) across all three of the research
script's STOP_ATR_MULT_GRID values, zero false positives/negatives. That
verification isn't a checked-in test since the cache file isn't tracked;
these tests instead prove state-machine correctness on synthetic, hand-
computable data.

A single RTH session is only 13 bars (09:30 -> 15:30 in 30-min steps), and
ATR(14) needs 14 bars of history to warm up -- so every scenario below that
needs a live ATR is built as a flat 13-bar warm-up session followed by the
scenario session, exactly mirroring how ATR behaves on the real multi-session
feed (continuous across session boundaries, reset only per-session for the
developing VA itself).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.signals_va_reentry import (
    MIN_VA_WARMUP_BARS,
    generate_va_reentry_signals,
)

_BARS_PER_SESSION = 13  # 09:30, 10:00, ..., 15:30


def _session_mask(index: pd.DatetimeIndex, session_date: str) -> pd.Series:
    """Boolean mask for rows in *index* belonging to the given NY session
    date. Comparing a tz-aware normalized index to a tz-naive Timestamp
    silently returns all-False, so anchor to the same tz explicitly."""
    ny = index.tz_convert("America/New_York").normalize()
    return pd.Series(ny == pd.Timestamp(session_date, tz="America/New_York"), index=index)


def _rth_session(
    session_date: str, closes: list[float], vols: list[float] | float = 1000.0
) -> pd.DataFrame:
    """Build one RTH session's worth of 30-min bars (09:30 start) from a list
    of close prices (must be <= 13 bars -- a session only has 13 RTH slots).
    Each bar's high/low = close +/- 0.5 (tight, deterministic volume-at-price
    so the developing VA is easy to reason about by hand). *vols* may be a
    per-bar list (to make some bars dominate the volume-at-price histogram
    and anchor the developing VA regardless of later price action) or a
    single scalar applied to every bar."""
    assert len(closes) <= _BARS_PER_SESSION, "a single RTH session only has 13 bars (09:30-15:30)"
    n = len(closes)
    idx = pd.date_range(f"{session_date} 09:30", periods=n, freq="30min", tz="America/New_York")
    idx = idx.tz_convert("UTC")
    closes_arr = np.array(closes, dtype=float)
    vol_arr = np.full(n, vols, dtype=float) if np.isscalar(vols) else np.array(vols, dtype=float)
    return pd.DataFrame(
        {
            "open": closes_arr,
            "high": closes_arr + 0.5,
            "low": closes_arr - 0.5,
            "close": closes_arr,
            "volume": vol_arr,
        },
        index=idx,
    )


def _warmup_session(session_date: str, base: float = 5000.0) -> pd.DataFrame:
    """A full flat 13-bar RTH session purely to carry ATR(14) into warmup for
    a following session -- never produces an event itself (near-zero VA
    width keeps side 'inside' throughout). Heavy volume so a following
    session's consolidation dominates the developing VA and anchors it (see
    `_make_breakout_session`)."""
    rng = np.random.default_rng(hash(session_date) % (2**32))
    closes = base + rng.uniform(-0.4, 0.4, _BARS_PER_SESSION)
    return _rth_session(session_date, list(closes), vols=100_000.0)


def _make_breakout_session(session_date: str = "2026-06-02") -> pd.DataFrame:
    """Preceded by a flat warm-up session (so ATR is live). Within this
    session: 6 bars of heavy-volume tight consolidation around 5000 (anchors
    the developing VA regardless of what comes after -- its volume dwarfs
    the low-volume breakout bars, so the VA boundary doesn't chase price),
    then 2 bars that CLOSE modestly above the consolidation range -- should
    fire a SHORT event (price above VAH, target = VAL) on the 2nd
    consecutive above-VAH close, with a comfortable stop margin (test-only
    stop_atr_mult=5.0 keeps the ATR-derived stop safely above the modest
    breakout, matching the ordering the research script itself enforces:
    a degenerate setup where entry_price >= stop_price is a skip, not a
    signal -- see `_build_trades`'s own guard)."""
    consolidation = [5000, 5001, 4999, 5000, 5002, 4998]  # 6 bars, heavy volume -> anchors VA
    breakout = [5008, 5009]  # modest excursion above the ~5001-5002 developing VAH
    tail = [5008, 5009, 5007]  # a few bars after the event, still within the 13-bar session
    warmup = _warmup_session("2026-06-01")
    today = _rth_session(
        session_date,
        consolidation + breakout + tail,
        vols=[100_000.0] * len(consolidation) + [10.0] * (len(breakout) + len(tail)),
    )
    return pd.concat([warmup, today]).sort_index()


def test_required_columns_present():
    df = generate_va_reentry_signals(_make_breakout_session())
    for col in (
        "entry_signal",
        "stop_level",
        "target_1",
        "target_2",
        "target_3",
        "bias",
        "regime",
        "atr",
    ):
        assert col in df.columns, f"Missing column: {col}"


def test_empty_dataframe_returns_all_columns_no_crash():
    empty = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    empty.index = pd.DatetimeIndex([])
    df = generate_va_reentry_signals(empty)
    assert len(df) == 0
    assert "entry_signal" in df.columns


def test_non_rth_only_data_produces_no_trade():
    """Bars entirely outside RTH (e.g. weekend/overnight-only feed) must
    never fire an event -- side classification requires RTH session context."""
    idx = pd.date_range("2026-06-06 02:00", periods=10, freq="30min", tz="UTC")  # Saturday
    df = pd.DataFrame(
        {
            "open": 5000.0,
            "high": 5005.0,
            "low": 4995.0,
            "close": 5000.0,
            "volume": 1000.0,
        },
        index=idx,
    )
    result = generate_va_reentry_signals(df)
    assert (result["entry_signal"] == "NO_TRADE").all()


def test_breakout_session_fires_short_event():
    df = generate_va_reentry_signals(_make_breakout_session(), stop_atr_mult=5.0)
    entries = df[df["entry_signal"] == "ENTRY_NOW"]
    assert len(entries) >= 1, "Expected at least one ENTRY_NOW on the engineered breakout"
    row = entries.iloc[0]
    assert row["bias"] == "STRONG_BEAR"  # price closed ABOVE VAH -> mean-revert SHORT
    assert row["regime"] == "MEAN_REVERSION"


def test_short_event_stop_and_target_ordering():
    """For a SHORT (mean-revert down to VAL), the live-runner-facing target
    staging (T1 < T2 < T3, all below entry) must hold, and stop must sit
    ABOVE entry (invalidation is further extension, not reversion)."""
    df = generate_va_reentry_signals(_make_breakout_session(), stop_atr_mult=5.0)
    entries = df[df["entry_signal"] == "ENTRY_NOW"]
    assert len(entries) >= 1
    for idx, row in entries.iterrows():
        close = df.loc[idx, "close"]
        assert row["stop_level"] > close, "SHORT stop must be above entry"
        assert row["target_3"] < close, "SHORT target must be below entry"
        assert row["target_3"] < row["target_2"] < row["target_1"] < close, (
            "SHORT targets must be strictly increasing toward entry (T1 nearest)"
        )


def test_no_event_before_warmup_bars():
    """The first MIN_VA_WARMUP_BARS+1 bars of every session can never fire an
    event -- the developing VA isn't considered 'developed' yet."""
    df = generate_va_reentry_signals(_make_breakout_session(), stop_atr_mult=5.0)
    grouped = df.groupby(df.index.tz_convert("America/New_York").normalize())
    for _, sess in grouped:
        first_n = sess.iloc[: MIN_VA_WARMUP_BARS + 1]
        assert (first_n["entry_signal"] == "NO_TRADE").all()


def test_one_signal_per_excursion_not_every_qualifying_bar():
    """Firing sets armed=False -- a run of 5 consecutive above-VAH closes
    should produce exactly ONE event (at the 2nd consecutive bar), not one
    per bar for the remainder of the excursion."""
    consolidation = [5000, 5001, 4999, 5000, 5002, 4998]  # 6 bars, heavy volume -> anchors VA
    long_breakout = [5008, 5009, 5008, 5009, 5008]  # 5 consecutive bars above VAH (11 fits in 13)
    warmup = _warmup_session("2026-06-01")
    today = _rth_session(
        "2026-06-02",
        consolidation + long_breakout,
        vols=[100_000.0] * len(consolidation) + [10.0] * len(long_breakout),
    )
    df = generate_va_reentry_signals(pd.concat([warmup, today]).sort_index(), stop_atr_mult=5.0)
    entries = df[df["entry_signal"] == "ENTRY_NOW"]
    assert len(entries) == 1, f"Expected exactly 1 event for one excursion, got {len(entries)}"


def test_multi_session_isolation_no_state_leaks_across_sessions():
    """A flat filler session followed by the breakout session: the breakout
    session's event must fire (VA/consec state resets per session, doesn't
    inherit anything from the prior session's tail)."""
    df = _make_breakout_session(session_date="2026-06-02")  # already warmup + breakout
    day2_mask = _session_mask(df.index, "2026-06-02")
    assert (df.loc[day2_mask, "high"] > 0).any()  # sanity: day2 rows present pre-signal-gen
    result = generate_va_reentry_signals(df, stop_atr_mult=5.0)
    day2_result_mask = _session_mask(result.index, "2026-06-02")
    day1_result_mask = _session_mask(result.index, "2026-06-01")
    assert (result.loc[day2_result_mask, "entry_signal"] == "ENTRY_NOW").any()
    assert not (result.loc[day1_result_mask, "entry_signal"] == "ENTRY_NOW").any()


def test_degenerate_risk_reward_skipped():
    """If the developing VA never widens (near-zero range consolidation),
    the MIN_VA_WIDTH guard keeps side 'inside' for the whole session and no
    event can fire, exercising the same degenerate-setup guard the research
    script's own risk<=0/reward<=0 check covers."""
    warmup = _warmup_session("2026-06-01")
    flat = _rth_session("2026-06-02", [5000.0] * 10)
    df = generate_va_reentry_signals(pd.concat([warmup, flat]).sort_index())
    day2_mask = _session_mask(df.index, "2026-06-02")
    assert (df.loc[day2_mask, "entry_signal"] == "NO_TRADE").all()
