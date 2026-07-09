"""Maps raw backtest.tpo_profile.compute_tpo_profile() output onto the
analysis.auction_bias "tpo" input shape.

Derives the "failed" boolean from the module's own target/fail_target algebra
rather than inventing a new concept: for a bull-imbalanced profile the target is
the up-move and the fail_target is the down-move (the direction the profile says
NOT to go); the profile is "failed" once price has actually traded through that
fail_target, i.e. against its own prediction. Symmetric for bear-imbalance.

Verified against the 2026-07-08 chart fixture (poc=7550, bull-imbalance,
target=7624.25, fail_target=7529.75, last=7526.75 -> failed=True) — see
tests/test_tpo_bias_mapping.py.

NOTE — this maps ONLY the engine's own generic backtest.tpo_profile columns. It
is NOT a reproduction of Corey's proprietary AA_CoreyTscorev2 ThinkScript study
(the chart's "Sellers in Control below X / Buyers offsides below Y" shelves) —
that study runs client-side in ThinkOrSwim with no API. The closest engine-native
analog to those shelves is the TPO value-area bounds (va_high/va_low), which this
module surfaces as va_high/va_low, NOT as sellers_in_control_below/
buyers_offside_below — do not conflate the two. See the design doc's "Host
implementation guide" for the full caveat.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

__all__ = [
    "derive_tpo_failed",
    "row_to_tpo_dict",
    "session_extreme_since_open",
    "session_range",
    "current_session_block",
]


def derive_tpo_failed(imbalance: str, close: float, fail_target: float) -> bool:
    """True once price has traded through its own profile's fail_target.

    Args:
        imbalance: "BULL_IMBAL" or "BEAR_IMBAL" (tpo_profile.py's tpo_imbalance).
        close: the price to test against fail_target. Pass the session extreme
            (see session_extreme_since_open) for a since-open breach check that
            survives a bounce back across the level before the request; pass
            the raw last price only for a snapshot ("is it beyond it right
            now") check.
        fail_target: tpo_profile.py's tpo_fail_target for the current session.
    """
    if imbalance == "BULL_IMBAL":
        return close <= fail_target
    if imbalance == "BEAR_IMBAL":
        return close >= fail_target
    return False


def _bar_session_dates(
    profile_df: pd.DataFrame,
    session_start_hour: int = 9,
    session_start_minute: int = 30,
    tz: str = "America/Chicago",
) -> pd.Series:
    """Per-bar trading-session date, using the IDENTICAL bucketing rule as
    backtest.tpo_profile.compute_tpo_profile's internal _session_tpo grouping
    (bars before the session open belong to the previous calendar date's
    session). Duplicated verbatim here rather than exporting a new public
    helper from tpo_profile.py, which is a shared, heavily-used module with
    many other callers -- MUST be kept in sync with that function's
    session_start_hour/session_start_minute/tz defaults if either changes.

    Requires profile_df to have a tz-aware (or naive-as-UTC) DatetimeIndex,
    which compute_tpo_profile's output always does (it operates on and
    preserves its input's index).
    """
    idx = profile_df.index
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    idx_local = idx.tz_convert(tz)
    session_open = idx_local.hour * 60 + idx_local.minute
    open_cutoff = session_start_hour * 60 + session_start_minute
    session_date = idx_local.normalize()
    pre_open_mask = session_open < open_cutoff
    return pd.Series(
        session_date - pd.to_timedelta(pre_open_mask.astype(int), unit="D"), index=profile_df.index
    )


def current_session_block(profile_df: pd.DataFrame) -> pd.DataFrame:
    """The trailing block of profile_df rows belonging to the current session,
    identified by REAL session-date bucketing (see _bar_session_dates), not by
    value-equality on tpo_fail_target.

    Codex review finding (PR #319, second pass): the original implementation
    treated a run of equal tpo_fail_target values as "one session" -- but two
    genuinely DIFFERENT adjacent sessions can coincidentally compute the exact
    same fail_target (it's a function of that session's own poc/profile
    bounds), which would wrongly merge a prior session's high/low into
    session_range()'s "today's range" and could falsely trip range_exhausted.
    Bucketing by actual session date (matching compute_tpo_profile's own rule)
    has no such collision risk.

    Used as the single shared session-boundary definition for both
    session_extreme_since_open (breach check) and session_range (day_range)
    so the two never disagree about what "today's session" means.

    Returns an empty DataFrame if the profile is undefined or the required
    column is absent.
    """
    if profile_df is None or profile_df.empty or "tpo_fail_target" not in profile_df.columns:
        return pd.DataFrame()
    if pd.isna(profile_df["tpo_fail_target"].iloc[-1]):
        return pd.DataFrame()

    session_dates = _bar_session_dates(profile_df)
    last_session_date = session_dates.iloc[-1]
    return profile_df[(session_dates == last_session_date).to_numpy()]


def session_extreme_since_open(profile_df: pd.DataFrame, imbalance: Optional[str]) -> Optional[float]:
    """The session low (BULL_IMBAL) or high (BEAR_IMBAL) since the current
    session's profile was established, so a fail_target breach is not silently
    forgotten if price bounces back across it before the request.

    Codex review finding (PR #315): checking only the current last price against
    fail_target means a bull-imbalanced profile that traded below fail_target and
    then recovered above it reports failed=False, even though the breach
    happened. Uses current_session_block's trailing same-session run and takes
    the extreme of the ORIGINAL high/low columns compute_tpo_profile preserves
    from its input df.

    Returns None if the profile is undefined (mirrors row_to_tpo_dict) or the
    required columns are absent.
    """
    if imbalance not in ("BULL_IMBAL", "BEAR_IMBAL"):
        return None
    block = current_session_block(profile_df)
    if block.empty:
        return None
    if imbalance == "BULL_IMBAL" and "low" in block.columns:
        return float(block["low"].min())
    if imbalance == "BEAR_IMBAL" and "high" in block.columns:
        return float(block["high"].max())
    return None


def session_range(profile_df: pd.DataFrame) -> Optional[float]:
    """Today's session high-low so far, from the same current-session block
    session_extreme_since_open uses.

    Codex review finding (PR #315): using a daily bar's high-low for
    range_exhausted breaks when the 1d feed returns only completed sessions
    (a case _prior_close_from_daily explicitly supports) -- that daily bar is
    then yesterday's, not today's actively-forming range, even though fresh
    5m bars (which this reads instead) are already being fetched for TPO.
    """
    block = current_session_block(profile_df)
    if block.empty or "high" not in block.columns or "low" not in block.columns:
        return None
    return float(block["high"].max() - block["low"].min())


def row_to_tpo_dict(
    close: float,
    va_high: Optional[float],
    va_low: Optional[float],
    profile_target: Optional[float],
    fail_target: Optional[float],
    imbalance: Optional[str],
) -> Optional[dict]:
    """Build the analysis.auction_bias "tpo" input from one compute_tpo_profile row.

    ``close`` is passed straight through to derive_tpo_failed — callers doing a
    since-open breach check should pass session_extreme_since_open's result
    here, not the raw last price (see derive_tpo_failed's docstring).

    Returns None when the profile is undefined for this session (NaN target/
    fail_target — compute_tpo_profile leaves these null until a prior session
    exists), so the caller can omit "tpo" entirely rather than pass garbage.
    """
    if fail_target is None or profile_target is None or imbalance is None:
        return None
    return {
        "value_area": {"va_high": va_high, "va_low": va_low},
        "profile_target": round(float(profile_target), 2),
        "fail_target": round(float(fail_target), 2),
        "failed": derive_tpo_failed(imbalance, close, float(fail_target)),
    }
