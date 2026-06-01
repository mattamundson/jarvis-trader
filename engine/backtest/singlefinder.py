"""
JARVIS TRADER — Corey Singlefinder v2 (Python port)

Source  : thinkorswim-scripts/AA_CoreySFv2STUDY.ts  (Corey Surles @coreysurles)
Spec    : thinkorswim-scripts/docs/corey_singlefinder_v2.md

Price-action approximation of TOS's TPO letter-counting logic.
The original ThinkScript operates on any aggregation and marks a "single"
wherever a true price gap exists between consecutive bars:

  bearish single : high[-1] < low[1]   (gap down, orange)
  bullish single : high[1]  < low[-1]  (gap up,   pink)

This port extends that concept to multi-session data by:
1. Splitting the DataFrame into daily sessions.
2. Within each session, building a coarse TPO histogram (tick bins).
3. Tagging price gaps (single-print bins touched by only one bar).
4. Grouping adjacent single-print bins into zones; filtering by
   min_single_ticks.
5. Classifying zones as bullish (below POC) or bearish (above POC).
6. Detecting fail bars: price entered a zone then closed back out of it.

Column outputs (all forward-filled from the session that produced them):
  sf_bullish_single_top     float  — top boundary of most recent bullish zone
  sf_bullish_single_bottom  float  — bottom boundary of most recent bullish zone
  sf_bearish_single_top     float  — top boundary of most recent bearish zone
  sf_bearish_single_bottom  float  — bottom boundary of most recent bearish zone
  sf_in_bullish_single      bool   — close is inside a bullish zone this bar
  sf_in_bearish_single      bool   — close is inside a bearish zone this bar
  sf_bullish_fail           bool   — bar opened above bullish zone, closed below it
  sf_bearish_fail           bool   — bar opened below bearish zone, closed above it
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _tick_size(prices: pd.Series) -> float:
    """Infer a reasonable tick size from the price series."""
    diffs = prices.diff().abs().dropna()
    nonzero = diffs[diffs > 0]
    if nonzero.empty:
        return 0.25
    return float(np.percentile(nonzero, 5))


def _build_tpo_histogram(df_session: pd.DataFrame, tick: float) -> dict[float, int]:
    """Count how many bars touched each tick-rounded price level."""
    counts: dict[float, int] = {}
    for _, row in df_session.iterrows():
        lo_bin = round(row["low"] / tick) * tick
        hi_bin = round(row["high"] / tick) * tick
        level = lo_bin
        while level <= hi_bin + tick * 0.5:
            counts[level] = counts.get(level, 0) + 1
            level = round(level + tick, 10)
    return counts


def _find_zones(
    counts: dict[float, int], tick: float, min_ticks: int
) -> list[tuple[float, float]]:
    """Return list of (bottom, top) zones made up of single-print levels."""
    singles = sorted(k for k, v in counts.items() if v == 1)
    if not singles:
        return []
    zones: list[tuple[float, float]] = []
    run = [singles[0]]
    for lvl in singles[1:]:
        if abs(lvl - run[-1] - tick) < tick * 0.01:
            run.append(lvl)
        else:
            if len(run) >= min_ticks:
                zones.append((run[0], run[-1] + tick))
            run = [lvl]
    if len(run) >= min_ticks:
        zones.append((run[0], run[-1] + tick))
    return zones


def _poc(counts: dict[float, int]) -> float:
    """Point of Control — most frequently touched price level."""
    return max(counts, key=lambda k: counts[k])


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def compute_single_prints(
    df: pd.DataFrame,
    session_start_hour: int = 9,
    session_start_minute: int = 30,
    tz: str = "America/Chicago",
    min_single_ticks: int = 2,
) -> pd.DataFrame:
    """
    Compute Corey Singlefinder v2 columns for an OHLC DataFrame.

    Parameters
    ----------
    df : DataFrame with columns [open, high, low, close] and a DatetimeIndex.
         Index may be tz-naive (treated as UTC) or tz-aware.
    session_start_hour, session_start_minute : session boundary in *tz*.
    tz : timezone string for session grouping.
    min_single_ticks : minimum contiguous single-print bins to form a zone.

    Returns
    -------
    df copy with 8 new columns (see module docstring).
    """
    if df.empty:
        out = df.copy()
        for col in (
            "sf_bullish_single_top", "sf_bullish_single_bottom",
            "sf_bearish_single_top", "sf_bearish_single_bottom",
            "sf_in_bullish_single", "sf_in_bearish_single",
            "sf_bullish_fail", "sf_bearish_fail",
        ):
            out[col] = np.nan if "top" in col or "bottom" in col else False
        return out

    out = df.copy()

    # normalise index to target tz
    idx = out.index
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    idx = idx.tz_convert(tz)

    tick = _tick_size(out["close"])

    # session label: the date on which this session *started*
    adjusted = idx - pd.Timedelta(
        hours=session_start_hour, minutes=session_start_minute
    )
    session_labels = adjusted.normalize()

    out["_session"] = session_labels.values

    # output columns initialised
    out["sf_bullish_single_top"] = np.nan
    out["sf_bullish_single_bottom"] = np.nan
    out["sf_bearish_single_top"] = np.nan
    out["sf_bearish_single_bottom"] = np.nan
    out["sf_in_bullish_single"] = False
    out["sf_in_bearish_single"] = False
    out["sf_bullish_fail"] = False
    out["sf_bearish_fail"] = False

    bull_top = bull_bot = bear_top = bear_bot = np.nan

    for _sess_date, grp in out.groupby("_session", sort=True):
        counts = _build_tpo_histogram(grp, tick)
        if not counts:
            continue
        poc = _poc(counts)
        zones = _find_zones(counts, tick, min_single_ticks)

        bull_zones = [(b, t) for b, t in zones if t <= poc]
        bear_zones = [(b, t) for b, t in zones if b >= poc]

        # take the zone closest to current price (highest bull, lowest bear)
        if bull_zones:
            bull_bot, bull_top = max(bull_zones, key=lambda z: z[0])
        if bear_zones:
            bear_bot, bear_top = min(bear_zones, key=lambda z: z[0])

        idx_locs = grp.index
        out.loc[idx_locs, "sf_bullish_single_top"] = bull_top if bull_zones else np.nan
        out.loc[idx_locs, "sf_bullish_single_bottom"] = bull_bot if bull_zones else np.nan
        out.loc[idx_locs, "sf_bearish_single_top"] = bear_top if bear_zones else np.nan
        out.loc[idx_locs, "sf_bearish_single_bottom"] = bear_bot if bear_zones else np.nan

        closes = grp["close"]
        opens = grp["open"]

        if bull_zones:
            in_bull = (closes >= bull_bot) & (closes <= bull_top)
            out.loc[idx_locs, "sf_in_bullish_single"] = in_bull.values
            # fail: opened above zone, low dipped into zone, closed below zone
            bull_fail = (opens > bull_top) & (grp["low"] <= bull_top) & (closes < bull_bot)
            out.loc[idx_locs, "sf_bullish_fail"] = bull_fail.values

        if bear_zones:
            in_bear = (closes >= bear_bot) & (closes <= bear_top)
            out.loc[idx_locs, "sf_in_bearish_single"] = in_bear.values
            # fail: opened below zone, high penetrated into zone, closed above zone
            bear_fail = (opens < bear_bot) & (grp["high"] >= bear_bot) & (closes > bear_top)
            out.loc[idx_locs, "sf_bearish_fail"] = bear_fail.values

    out.drop(columns=["_session"], inplace=True)
    return out
