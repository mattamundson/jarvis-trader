"""
JARVIS TRADER — TPO Profile
Python port of thinkorswim-scripts/AA_CoreyTPOProfilev1STUDY.ts (Corey Surles).
Spec: thinkorswim-scripts/docs/corey_tpo_profile_v1.md

Computes per-session (RTH day) Time-Price-Opportunity levels:
  vpoc          — price level with highest bar count in the session
  va_high       — upper boundary of 70% value area (VAH)
  va_low        — lower boundary of 70% value area (VAL)
  profile_high  — session price extreme high
  profile_low   — session price extreme low
  price_vs_va   — 'ABOVE_VAH' | 'IN_VA' | 'BELOW_VAL'
  buyer_control_signal  — bool: close > va_high
  seller_control_signal — bool: close < va_low

Value area algorithm mirrors the TOS TimeProfile logic:
  1. Bin prices to nearest tick_size.
  2. Count bars per bin (TPO count).
  3. VPOC = bin with max count.
  4. Expand outward from VPOC, adding the higher-count adjacent bin first,
     until the cumulative count >= value_area_pct of session total.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _detect_tick_size(close: pd.Series) -> float:
    diffs = close.diff().abs().dropna()
    diffs = diffs[diffs > 0]
    if diffs.empty:
        return 0.25
    return float(round(diffs.min(), 8))


def _session_tpo(
    group: pd.DataFrame,
    tick_size: float,
    value_area_pct: float,
) -> pd.Series:
    close = group["close"]
    bins = (close / tick_size).round() * tick_size
    counts = bins.value_counts().sort_index()

    if counts.empty:
        nan = float("nan")
        return pd.Series(
            {
                "vpoc": nan,
                "va_high": nan,
                "va_low": nan,
                "profile_high": nan,
                "profile_low": nan,
            }
        )

    profile_high = float(counts.index.max())
    profile_low = float(counts.index.min())
    vpoc_price = float(counts.idxmax())
    total = counts.sum()
    target = int(np.ceil(total * value_area_pct))

    # Expand value area outward from VPOC
    sorted_prices = counts.index.tolist()
    vpoc_idx = sorted_prices.index(vpoc_price)
    lo_ptr = vpoc_idx
    hi_ptr = vpoc_idx
    accumulated = int(counts.iloc[vpoc_idx])

    while accumulated < target:
        lo_candidate = counts.iloc[lo_ptr - 1] if lo_ptr > 0 else 0
        hi_candidate = counts.iloc[hi_ptr + 1] if hi_ptr < len(sorted_prices) - 1 else 0
        if lo_candidate == 0 and hi_candidate == 0:
            break
        if hi_candidate >= lo_candidate:
            hi_ptr += 1
            accumulated += int(hi_candidate)
        else:
            lo_ptr -= 1
            accumulated += int(lo_candidate)

    va_high = float(sorted_prices[hi_ptr])
    va_low = float(sorted_prices[lo_ptr])

    return pd.Series(
        {
            "vpoc": vpoc_price,
            "va_high": va_high,
            "va_low": va_low,
            "profile_high": profile_high,
            "profile_low": profile_low,
        }
    )


def compute_tpo_profile(
    df: pd.DataFrame,
    value_area_pct: float = 0.70,
    session_start_hour: int = 9,
    session_start_minute: int = 30,
    tz: str = "America/Chicago",
    tick_size: float | None = None,
) -> pd.DataFrame:
    """
    Compute TPO profile levels for each RTH session and join back onto df.

    Parameters
    ----------
    df : DataFrame
        Must have a DatetimeIndex (timezone-aware or naive) and a 'close' column.
    value_area_pct : float
        Fraction of TPO bars included in the value area (default 0.70).
    session_start_hour : int
        RTH open hour in local tz (default 9 for 9:30 CT).
    session_start_minute : int
        RTH open minute (default 30).
    tz : str
        Timezone for session detection.
    tick_size : float | None
        Price bin size. Auto-detected from df['close'] diffs when None.

    Returns
    -------
    DataFrame
        Original df plus columns: vpoc, va_high, va_low, profile_high,
        profile_low, price_vs_va, buyer_control_signal, seller_control_signal.
        All level columns carry the *prior* session's values (forward-filled,
        no look-ahead within the current session).
    """
    out = df.copy()

    if tick_size is None:
        tick_size = _detect_tick_size(out["close"])
    tick_size = max(tick_size, 1e-8)

    idx = out.index
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    idx_local = idx.tz_convert(tz)

    # Assign each bar to the RTH session date it belongs to.
    # Bars before the session open belong to the previous calendar date's session.
    session_open = idx_local.hour * 60 + idx_local.minute
    open_cutoff = session_start_hour * 60 + session_start_minute
    session_date = idx_local.normalize()
    pre_open_mask = session_open < open_cutoff
    session_date = session_date - pd.to_timedelta(pre_open_mask.astype(int), unit="D")

    out["_session_date"] = session_date.values

    tpo = (
        out.groupby("_session_date")
        .apply(_session_tpo, tick_size=tick_size, value_area_pct=value_area_pct)
        .reset_index()
    )
    tpo = tpo.rename(columns={"_session_date": "session_date"})

    # Merge using prior session values (shift by 1 session to avoid look-ahead)
    tpo_sorted = tpo.sort_values("session_date").copy()
    for col in ("vpoc", "va_high", "va_low", "profile_high", "profile_low"):
        tpo_sorted[col] = tpo_sorted[col].shift(1)
    tpo_sorted = tpo_sorted.set_index("session_date")

    for col in ("vpoc", "va_high", "va_low", "profile_high", "profile_low"):
        out[col] = out["_session_date"].map(tpo_sorted[col])

    out = out.drop(columns=["_session_date"])

    # Derived classification
    def _classify(row: pd.Series) -> str:
        if pd.isna(row["va_high"]) or pd.isna(row["va_low"]):
            return "IN_VA"
        if row["close"] > row["va_high"]:
            return "ABOVE_VAH"
        if row["close"] < row["va_low"]:
            return "BELOW_VAL"
        return "IN_VA"

    out["price_vs_va"] = out.apply(_classify, axis=1)
    out["buyer_control_signal"] = out["close"] > out["va_high"]
    out["seller_control_signal"] = out["close"] < out["va_low"]

    # NaN va_high/va_low → False signals
    out["buyer_control_signal"] = out["buyer_control_signal"].fillna(False)
    out["seller_control_signal"] = out["seller_control_signal"].fillna(False)

    # Measured-move targets (Corey TPOext1 / TPOrej2). These are the
    # "This profile targets X / fail targets Y" levels on the chart. bal is the
    # value-area balance midpoint; an imbalanced profile (bal vs vpoc) projects a
    # 1.0x measured move from the VPOC. All inputs are prior-session (shifted) =>
    # point-in-time safe.
    bal = (out["va_high"] + out["va_low"]) / 2
    poc = out["vpoc"]
    up_move = (poc - out["profile_low"]) + poc       # 1.0x projection upward
    down_move = poc - (out["profile_high"] - poc)    # 1.0x projection downward
    bear = bal > poc
    out["tpo_bal"] = bal
    out["tpo_imbalance"] = np.where(bear, "BEAR_IMBAL", "BULL_IMBAL")
    # Primary target: bear imbalance -> down, bull -> up. Fail target: opposite.
    out["tpo_target"] = np.where(bear, down_move, up_move)
    out["tpo_fail_target"] = np.where(bear, up_move, down_move)
    # Null targets where the profile is undefined.
    undefined = poc.isna() | out["profile_high"].isna() | out["profile_low"].isna()
    out.loc[undefined, ["tpo_bal", "tpo_target", "tpo_fail_target"]] = np.nan

    return out
