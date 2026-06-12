"""Shared helpers for the study signal generators.

Centralizes the RTH session mask, intraday ATR, per-session anchor attachment,
and the Backtester-contract column finalizer so each study module stays small
and consistent. No look-ahead helpers live here so the discipline is uniform.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.indicators import wilder_atr

RTH_TZ = "America/New_York"
_OPEN_T = pd.Timestamp("09:30").time()
_CLOSE_T = pd.Timestamp("16:00").time()

# Backtester-contract columns every study must emit.
CONTRACT_COLS = (
    "entry_signal", "bias", "stop_level",
    "target_1", "target_2", "target_3", "atr", "regime", "exit_signal",
)


def to_et(idx: pd.DatetimeIndex, tz: str = RTH_TZ) -> pd.DatetimeIndex:
    """Return the index converted to Eastern (localizing UTC if tz-naive)."""
    if idx.tz is not None:
        return idx.tz_convert(tz)
    return idx.tz_localize("UTC").tz_convert(tz)


def rth_mask(idx: pd.DatetimeIndex, tz: str = RTH_TZ) -> np.ndarray:
    """Boolean mask for RTH bars: ET 09:30 <= t < 16:00, Mon-Fri."""
    et = to_et(idx, tz)
    t = et.time
    in_session = np.array([(_OPEN_T <= x < _CLOSE_T) for x in t])
    weekday = np.asarray(et.dayofweek < 5)
    return in_session & weekday


def restrict_rth(df: pd.DataFrame, tz: str = RTH_TZ) -> pd.DataFrame:
    """Return RTH-only rows with a stable DatetimeIndex."""
    out = df.copy()
    if not isinstance(out.index, pd.DatetimeIndex):
        out.index = pd.to_datetime(out.index)
    return out[rth_mask(out.index, tz)].copy()


def atr_5m(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Intraday Wilder ATR on the working (5m) bars — the Backtester's unit."""
    return wilder_atr(df["high"], df["low"], df["close"], period=period)


def session_dates(idx: pd.DatetimeIndex, tz: str = RTH_TZ) -> pd.Index:
    """Per-bar ET session date (the calendar day the RTH bar belongs to)."""
    return pd.Index(to_et(idx, tz).date, name="session_date")


def attach_session_anchors(
    rth: pd.DataFrame, tz: str = RTH_TZ, atr_period: int = 14
) -> pd.DataFrame:
    """Attach per-bar ``anchor`` (prior-session close) and ``day_atr`` (prior
    session's Wilder ATR(14) on session OHLC). Both shifted one session so they
    are fully known at the open of the session they label — no look-ahead."""
    sd = session_dates(rth.index, tz)
    grp = rth.groupby(sd)
    sess = pd.DataFrame({
        "high": grp["high"].max(),
        "low": grp["low"].min(),
        "close": grp["close"].last(),
    }).sort_index()
    sess["day_atr"] = wilder_atr(sess["high"], sess["low"], sess["close"], period=atr_period)
    sess["anchor"] = sess["close"].shift(1)
    sess["day_atr_prior"] = sess["day_atr"].shift(1)

    anchor_map = sess["anchor"].to_dict()
    atr_map = sess["day_atr_prior"].to_dict()
    out = rth.copy()
    out["anchor"] = [anchor_map.get(d, np.nan) for d in sd]
    out["day_atr"] = [atr_map.get(d, np.nan) for d in sd]
    out["__session"] = sd.values
    return out


def empty_contract(rth: pd.DataFrame) -> pd.DataFrame:
    """Finalize a frame that produced no entries (all NO_TRADE)."""
    out = rth.copy()
    out["entry_signal"] = "NO_TRADE"
    out["bias"] = "NEUTRAL"
    for c in ("stop_level", "target_1", "target_2", "target_3"):
        out[c] = np.nan
    if "atr" not in out.columns:
        out["atr"] = atr_5m(out) if not out.empty else []
    out["regime"] = ""
    out["exit_signal"] = "NO_EXIT"
    return out
