"""
JARVIS TRADER — TPO Profile
Python port of thinkorswim-scripts/AA_CoreyTPOProfilev1STUDY.ts (Corey Surles).
Spec: thinkorswim-scripts/docs/corey_tpo_profile_v1.md

Computes per-session (RTH day) Time-Price-Opportunity levels:
  vpoc          — price level with the most volume in the RTH session
  va_high       — upper boundary of 70% value area (VAH)
  va_low        — lower boundary of 70% value area (VAL)
  profile_high  — session price extreme high
  profile_low   — session price extreme low
  price_vs_va   — 'ABOVE_VAH' | 'IN_VA' | 'BELOW_VAL'
  buyer_control_signal  — bool: close > va_high
  seller_control_signal — bool: close < va_low

Value area algorithm mirrors the TOS TimeProfile logic:
  1. Spread each bar's volume evenly across the tick bins from its low to
     its high (one unit per bin when there is no volume column).
  2. VPOC = bin with the most volume.
  3. Expand outward from VPOC, adding the larger adjacent bin first,
     until the cumulative volume >= value_area_pct of session total.

Sessions are RTH only on weekdays, 08:30-15:00 CT. A bar carries the most
recent session completed at or before that bar; later sessions cannot change
earlier values.
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
    tick_size: float | None,
    value_area_pct: float,
) -> pd.Series:
    if tick_size is None:
        # Inferring from the whole input frame uses future close differences.
        # A session is selected only once it has completed, so this group is
        # the earliest causally available window for its price bins.
        tick_size = _detect_tick_size(group["close"])
    tick_size = max(tick_size, 1e-8)
    close = group["close"].to_numpy(dtype=float)
    high = group["high"].to_numpy(dtype=float) if "high" in group else close
    low = group["low"].to_numpy(dtype=float) if "low" in group else close
    vol = group["volume"].to_numpy(dtype=float) if "volume" in group else np.ones(len(close))
    lo_t = np.round(np.minimum(low, high) / tick_size).astype(np.int64)
    hi_t = np.round(np.maximum(low, high) / tick_size).astype(np.int64)
    acc: dict[int, float] = {}
    for lo_i, hi_i, v in zip(lo_t, hi_t, vol, strict=True):
        if not np.isfinite(v) or v <= 0:
            continue
        n = hi_i - lo_i + 1
        for t in range(lo_i, hi_i + 1):
            acc[t] = acc.get(t, 0.0) + v / n
    counts = pd.Series(
        {round(t * tick_size, 8): v for t, v in acc.items()}, dtype=float
    ).sort_index()

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
    target = total * value_area_pct

    # Expand value area outward from VPOC
    sorted_prices = counts.index.tolist()
    vpoc_idx = sorted_prices.index(vpoc_price)
    lo_ptr = vpoc_idx
    hi_ptr = vpoc_idx
    accumulated = float(counts.iloc[vpoc_idx])

    while accumulated < target:
        lo_candidate = counts.iloc[lo_ptr - 1] if lo_ptr > 0 else 0
        hi_candidate = counts.iloc[hi_ptr + 1] if hi_ptr < len(sorted_prices) - 1 else 0
        if lo_candidate == 0 and hi_candidate == 0:
            break
        if hi_candidate >= lo_candidate:
            hi_ptr += 1
            accumulated += float(hi_candidate)
        else:
            lo_ptr -= 1
            accumulated += float(lo_candidate)

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
    session_start_hour: int = 8,
    session_start_minute: int = 30,
    session_end_hour: int = 15,
    session_end_minute: int = 0,
    tz: str = "America/Chicago",
    tick_size: float | None = None,
) -> pd.DataFrame:
    """
    Compute TPO profile levels for each RTH session and join back onto df.

    Parameters
    ----------
    df : DataFrame
        Must have a DatetimeIndex (timezone-aware or naive) and a 'close' column.
        'high', 'low' and 'volume' are used when present.
    value_area_pct : float
        Fraction of TPO bars included in the value area (default 0.70).
    session_start_hour : int
        RTH open hour in local tz (default 8 for 08:30 CT).
    session_start_minute : int
        RTH open minute (default 30).
    session_end_hour, session_end_minute : int
        RTH close in local tz (default 15:00 CT).
    tz : str
        Timezone for session detection.
    tick_size : float | None
        Price bin size. Auto-detected within each completed RTH session when None.

    Returns
    -------
    DataFrame
        Original df plus columns: vpoc, va_high, va_low, profile_high,
        profile_low, price_vs_va, buyer_control_signal, seller_control_signal.
        All level columns carry the latest completed RTH session's values,
        never a profile requiring bars after the current timestamp.
    """
    out = df.copy()

    idx = out.index
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    idx_local = idx.tz_convert(tz)

    # A session becomes available only at its actual RTH close. Mapping via
    # the next business date can select a *future* weekend/holiday profile
    # when a synthetic or malformed input includes those dates.
    minute = idx_local.hour * 60 + idx_local.minute
    rth_open = session_start_hour * 60 + session_start_minute
    rth_close = session_end_hour * 60 + session_end_minute
    day = idx_local.normalize().tz_localize(None)
    in_rth = (minute >= rth_open) & (minute < rth_close) & (idx_local.weekday < 5)

    rth = out[np.asarray(in_rth)].copy()
    rth["_session_date"] = day[np.asarray(in_rth)]
    level_cols = ("vpoc", "va_high", "va_low", "profile_high", "profile_low")
    if rth.empty:
        tpo = pd.DataFrame(columns=list(level_cols), index=pd.DatetimeIndex([]))
    else:
        tpo = (
            rth.groupby("_session_date")
            .apply(_session_tpo, tick_size=tick_size, value_area_pct=value_area_pct)
            .sort_index()
        )

    sessions = pd.DatetimeIndex(tpo.index)
    completed_at = sessions.tz_localize(tz) + pd.Timedelta(minutes=rth_close)
    pos = completed_at.searchsorted(idx_local, side="right") - 1
    for col in level_cols:
        vals = tpo[col].to_numpy(dtype=float) if len(tpo) else np.array([])
        out[col] = np.where(pos >= 0, vals[np.clip(pos, 0, None)] if len(vals) else np.nan, np.nan)

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
    bull = bal < poc
    out["tpo_bal"] = bal
    # bal == poc (genuinely balanced) or either NaN -> no imbalance either way;
    # left as NaN (object Series), unlike a two-way np.where(bear, ..., ...)
    # which silently mislabeled that case BULL_IMBAL. Built via boolean masking
    # rather than np.select/np.where -- numpy can't unify a str choicelist with
    # a float default/fill in one call without forcing an explicit object dtype.
    imbalance = pd.Series(np.nan, index=out.index, dtype=object)
    imbalance[bear] = "BEAR_IMBAL"
    imbalance[bull] = "BULL_IMBAL"
    out["tpo_imbalance"] = imbalance
    # Primary target: bear imbalance -> down, bull -> up, no imbalance -> NaN.
    out["tpo_target"] = np.where(bear, down_move, np.where(bull, up_move, np.nan))
    out["tpo_fail_target"] = np.where(bear, up_move, np.where(bull, down_move, np.nan))
    # Null targets where the profile is undefined (e.g. first session, no prior).
    undefined = poc.isna() | out["profile_high"].isna() | out["profile_low"].isna()
    out.loc[undefined, ["tpo_bal", "tpo_imbalance", "tpo_target", "tpo_fail_target"]] = np.nan

    return out
