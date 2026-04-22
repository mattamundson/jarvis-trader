"""
JARVIS TRADER — Gap Finder
Port of thinkorswim-scripts/AA_CoreyGapfinderv1STUDY.ts by Corey Surles.
Spec: thinkorswim-scripts/docs/corey_gapfinder_v1.md

Identifies open-to-close overnight gaps at RTH session open.
Gap zones extend forward until price fills them (Layer 2 structure signal).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_gaps(
    df: pd.DataFrame,
    min_gap_pct: float = 0.001,
    session_start_hour: int = 9,
    session_start_minute: int = 30,
    tz: str = "America/Chicago",
) -> pd.DataFrame:
    """
    Compute gap-up / gap-down zones for each bar in *df*.

    Parameters
    ----------
    df : DataFrame with DatetimeIndex (UTC or tz-aware) and columns
         ``open``, ``high``, ``low``, ``close``.
    min_gap_pct : minimum gap size as a fraction of prior close (default 0.1 %).
    session_start_hour / session_start_minute : RTH open in *tz* local time.
    tz : timezone used to detect session opens (default America/Chicago).

    Returns
    -------
    Original DataFrame with eight new columns appended:

    ``gap_up_top``, ``gap_up_bottom``
        Float boundaries of the most recent unfilled gap-up zone (NaN when none active).
    ``gap_down_top``, ``gap_down_bottom``
        Mirror for gap-down zones.
    ``gap_up_filled_on_bar``
        True on the exact bar that closes an active gap-up zone.
    ``gap_down_filled_on_bar``
        Mirror.
    ``price_in_gap_up``
        True when bar's close is inside an active gap-up zone.
    ``price_in_gap_down``
        Mirror.

    Notes
    -----
    Gap direction follows the ThinkScript convention:
      * Gap Up  : prior_close < current_open  (bullish overnight acceptance)
      * Gap Down: prior_close > current_open  (bearish overnight rejection)
    Zone boundaries:
      * Gap Up  : bottom = prior_close, top = current_open
      * Gap Down: top = prior_close,    bottom = current_open
    A gap is "filled" when a subsequent bar's [low, high] range reaches the far
    boundary of the zone (low <= gap_up_bottom or high >= gap_down_top).
    Only the **most recent** unfilled gap of each type is tracked; a new gap of
    the same direction replaces the previous one.

    Source: AA_CoreyGapfinderv1STUDY.ts (GapUpStart=close, GapUpEnd=open)
    Spec  : thinkorswim-scripts/docs/corey_gapfinder_v1.md
    """
    out = df.copy()

    # Ensure tz-aware index for session detection
    idx = out.index
    if idx.tzinfo is None:
        idx = idx.tz_localize("UTC")
    local_idx = idx.tz_convert(tz)

    n = len(out)
    gap_up_top = np.full(n, np.nan)
    gap_up_bottom = np.full(n, np.nan)
    gap_down_top = np.full(n, np.nan)
    gap_down_bottom = np.full(n, np.nan)
    gap_up_filled = np.zeros(n, dtype=bool)
    gap_down_filled = np.zeros(n, dtype=bool)

    # Active gap state
    active_up_top: float = np.nan
    active_up_bottom: float = np.nan
    active_dn_top: float = np.nan
    active_dn_bottom: float = np.nan

    opens = out["open"].to_numpy(dtype=float)
    highs = out["high"].to_numpy(dtype=float)
    lows = out["low"].to_numpy(dtype=float)
    closes = out["close"].to_numpy(dtype=float)

    prev_session_close: float = np.nan

    for i in range(n):
        bar_time = local_idx[i]
        is_session_open = (
            bar_time.hour == session_start_hour
            and bar_time.minute == session_start_minute
        )

        # --- Detect new gap on first RTH bar ---------------------------------
        if is_session_open and not np.isnan(prev_session_close):
            prior_close = prev_session_close
            cur_open = opens[i]
            gap_size = abs(cur_open - prior_close) / prior_close

            if gap_size >= min_gap_pct:
                if cur_open > prior_close:
                    # Gap Up: zone between prior_close (bottom) and cur_open (top)
                    active_up_top = cur_open
                    active_up_bottom = prior_close
                    # New gap up resets any previous gap up
                    active_dn_top = active_dn_top  # gap down unaffected
                elif cur_open < prior_close:
                    # Gap Down: zone between cur_open (bottom) and prior_close (top)
                    active_dn_top = prior_close
                    active_dn_bottom = cur_open

        # --- Check fills before recording state for this bar -----------------
        hi = highs[i]
        lo = lows[i]

        if not np.isnan(active_up_bottom):
            # Gap up is filled when price pulls back to the bottom of the zone
            if lo <= active_up_bottom:
                gap_up_filled[i] = True
                active_up_top = np.nan
                active_up_bottom = np.nan

        if not np.isnan(active_dn_top):
            # Gap down is filled when price rallies to the top of the zone
            if hi >= active_dn_top:
                gap_down_filled[i] = True
                active_dn_top = np.nan
                active_dn_bottom = np.nan

        # --- Persist active zone levels --------------------------------------
        gap_up_top[i] = active_up_top
        gap_up_bottom[i] = active_up_bottom
        gap_down_top[i] = active_dn_top
        gap_down_bottom[i] = active_dn_bottom

        # --- Track prior session close: update on every non-session-open bar -
        # The final bar of the session becomes prev_session_close for the next
        # session's first bar.  We capture close on every bar; the value at the
        # last bar before the next session_open is what we want, so simply
        # overwrite on each bar that is NOT the opening bar (or always update
        # and let the opening-bar logic read the value from the previous iter).
        # Simplest correct approach: always update; the opening-bar comparison
        # reads the value written by the last bar of the prior session.
        prev_session_close = closes[i]

    out["gap_up_top"] = gap_up_top
    out["gap_up_bottom"] = gap_up_bottom
    out["gap_down_top"] = gap_down_top
    out["gap_down_bottom"] = gap_down_bottom
    out["gap_up_filled_on_bar"] = gap_up_filled
    out["gap_down_filled_on_bar"] = gap_down_filled
    out["price_in_gap_up"] = np.where(
        ~np.isnan(gap_up_top),
        (closes >= gap_up_bottom) & (closes <= gap_up_top),
        False,
    )
    out["price_in_gap_down"] = np.where(
        ~np.isnan(gap_down_top),
        (closes >= gap_down_bottom) & (closes <= gap_down_top),
        False,
    )

    return out
