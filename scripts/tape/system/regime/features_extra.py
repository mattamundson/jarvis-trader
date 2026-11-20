"""Extra predictors from external research (Dalton open type, OTF, NR/inside)."""
from __future__ import annotations

from typing import Optional, Tuple

import pandas as pd


def dalton_open_type(
    rth: pd.DataFrame,
    *,
    minutes: int = 30,
) -> Tuple[Optional[str], Optional[float]]:
    """Classify open from first `minutes` of RTH.

    Returns (open_type, open_drive_pts) where open_drive_pts = close_Nm - open.
    Types (simplified Dalton):
      open_drive            — strong directional move, close near extreme, little reclaim
      open_test_drive       — drive then modest pullback still on same side of open
      open_rejection_reverse— trades one side then closes back through open opposite
      open_auction          — two-sided, close near open / mid of opening range
    """
    if rth is None or len(rth) < 5:
        return None, None
    start = rth.index[0]
    win = rth[rth.index < start + pd.Timedelta(minutes=minutes)]
    if len(win) < 3:
        return None, None
    o = float(win["open"].iloc[0])
    c = float(win["close"].iloc[-1])
    h = float(win["high"].max())
    l = float(win["low"].min())
    rng = h - l
    drive = c - o
    if rng <= 0:
        return "open_auction", 0.0

    # location of close in opening range
    pos = (c - l) / rng
    # rejection: traded both sides of open AND closed opposite the initial probe
    first_half = win.iloc[: max(1, len(win) // 2)]
    fh_mid = float(first_half["close"].iloc[-1])
    initial_side = 1 if fh_mid >= o else -1
    close_side = 1 if c >= o else -1
    traded_above = h > o + 0.05 * rng
    traded_below = l < o - 0.05 * rng

    if traded_above and traded_below and initial_side != close_side and abs(drive) > 0.15 * rng:
        return "open_rejection_reverse", drive

    # drive: close in outer 20% of opening range, |drive| >= 50% of opening range
    if (pos >= 0.80 or pos <= 0.20) and abs(drive) >= 0.50 * rng:
        return "open_drive", drive

    # test-drive: directional but close pulled back toward mid (still same side)
    if abs(drive) >= 0.25 * rng and close_side == initial_side and 0.30 < pos < 0.70:
        return "open_test_drive", drive

    if abs(drive) >= 0.35 * rng and close_side == (1 if drive > 0 else -1):
        return "open_test_drive", drive

    return "open_auction", drive


def one_timeframing_count(rth: pd.DataFrame, bar_minutes: int = 30, max_bars: int = 6) -> Optional[int]:
    """Count consecutive one-timeframing 30m bars from the open (HH+HL or LH+LL streak).

    Returns streak length (0 if first comparison fails). None if insufficient bars.
    """
    if rth is None or len(rth) < bar_minutes * 2:
        return None
    start = rth.index[0]
    end = start + pd.Timedelta(minutes=bar_minutes * max_bars)
    win = rth[(rth.index >= start) & (rth.index < end)]
    if len(win) < bar_minutes:
        return None

    # resample to wall-clock 30m buckets from session open
    buckets = []
    t0 = start
    for i in range(max_bars):
        a = t0 + pd.Timedelta(minutes=bar_minutes * i)
        b = t0 + pd.Timedelta(minutes=bar_minutes * (i + 1))
        sl = win[(win.index >= a) & (win.index < b)]
        if len(sl) < max(3, bar_minutes // 4):
            break
        buckets.append((float(sl["high"].max()), float(sl["low"].min())))
    if len(buckets) < 2:
        return 0

    streak = 0
    direction = None  # 'up' or 'down'
    for i in range(1, len(buckets)):
        h0, l0 = buckets[i - 1]
        h1, l1 = buckets[i]
        up = h1 > h0 and l1 > l0
        dn = h1 < h0 and l1 < l0
        if up:
            if direction in (None, "up"):
                direction = "up"
                streak += 1
            else:
                break
        elif dn:
            if direction in (None, "down"):
                direction = "down"
                streak += 1
            else:
                break
        else:
            break
    return streak


def is_inside_day(prior_high, prior_low, high, low) -> Optional[int]:
    if None in (prior_high, prior_low, high, low):
        return None
    return 1 if high <= prior_high and low >= prior_low else 0


def is_nr_n(ranges_ending_at_prior, n: int) -> Optional[int]:
    """Prior day is NR-n if its range is the narrowest of the last n sessions (including itself)."""
    if ranges_ending_at_prior is None or len(ranges_ending_at_prior) < n:
        return None
    window = ranges_ending_at_prior[-n:]
    return 1 if window[-1] == min(window) else 0
