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

__all__ = ["derive_tpo_failed", "row_to_tpo_dict", "session_extreme_since_open"]


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


def session_extreme_since_open(profile_df: pd.DataFrame, imbalance: Optional[str]) -> Optional[float]:
    """The session low (BULL_IMBAL) or high (BEAR_IMBAL) since the current
    session's profile was established, so a fail_target breach is not silently
    forgotten if price bounces back across it before the request.

    Codex review finding (PR #315): checking only the current last price against
    fail_target means a bull-imbalanced profile that traded below fail_target and
    then recovered above it reports failed=False, even though the breach
    happened. This instead scans back across the trailing block of profile_df
    rows that share the current session's fail_target (compute_tpo_profile
    forward-fills that value for the whole session, so a run of equal values
    marks "this session"), and takes the extreme of the ORIGINAL high/low
    columns compute_tpo_profile preserves from its input df.

    Returns None if the profile is undefined (mirrors row_to_tpo_dict) or the
    required columns are absent.
    """
    if profile_df is None or profile_df.empty or imbalance not in ("BULL_IMBAL", "BEAR_IMBAL"):
        return None
    if "tpo_fail_target" not in profile_df.columns:
        return None

    last_fail = profile_df["tpo_fail_target"].iloc[-1]
    if pd.isna(last_fail):
        return None

    same_session = profile_df["tpo_fail_target"] == last_fail
    mismatches = same_session.index[~same_session]
    if len(mismatches) > 0:
        start_pos = profile_df.index.get_loc(mismatches[-1]) + 1
    else:
        start_pos = 0
    block = profile_df.iloc[start_pos:]

    if imbalance == "BULL_IMBAL" and "low" in block.columns:
        return float(block["low"].min())
    if imbalance == "BEAR_IMBAL" and "high" in block.columns:
        return float(block["high"].max())
    return None


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
