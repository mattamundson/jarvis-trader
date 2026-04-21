"""
JARVIS TRADER — TPO Score
Python port of thinkorswim-scripts/AA_CoreyTscorev2STUDY.ts (Corey Surles).
Spec: thinkorswim-scripts/docs/corey_tscore_v2.md (not yet created — see source .ts).

Depends on output columns produced by engine/backtest/tpo_profile.py:
  vpoc     — Point of Control price level  (float)
  va_high  — Value Area High               (float)
  va_low   — Value Area Low                (float)

Input DataFrame must also contain:
  close    — bar close price               (float)

The ThinkScript ScoreTotal sums five ticsize-scaled sub-scores and adds close,
producing a value > close (positive) / == close (neutral) / < close (negative).
This port normalises that to a continuous -1 .. +1 value without tick-size
dependency, making it comparable across instruments.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

_REQUIRED = {"vpoc", "va_high", "va_low", "close"}

_SCORE_THRESHOLDS = (0.66, 0.33, -0.33, -0.66)
_SCORE_LABELS = (
    "BUYERS_CONTROL",
    "BUYERS_LEAN",
    "NEUTRAL",
    "SELLERS_LEAN",
    "SELLERS_CONTROL",
)

_ZONE_LABELS = (
    "ABOVE_VALUE",
    "AT_UPPER_VA",
    "IN_VALUE",
    "AT_LOWER_VA",
    "BELOW_VALUE",
)


def _tpo_score_row(close: float, vpoc: float, va_high: float, va_low: float) -> float:
    va_range = max(va_high - va_low, 1e-9)
    if close > va_high:
        raw = (close - va_high) / max(va_high - vpoc, 1e-9)
        return min(1.0, raw)
    if close < va_low:
        raw = (close - va_low) / max(vpoc - va_low, 1e-9)
        return max(-1.0, raw)
    return 0.5 * (close - vpoc) / va_range


def _score_label(score: float) -> str:
    hi1, hi2, lo2, lo1 = _SCORE_THRESHOLDS
    if score >= hi1:
        return _SCORE_LABELS[0]
    if score >= hi2:
        return _SCORE_LABELS[1]
    if score > lo2:
        return _SCORE_LABELS[2]
    if score > lo1:
        return _SCORE_LABELS[3]
    return _SCORE_LABELS[4]


def _zone_label(close: float, va_high: float, va_low: float) -> str:
    va_range = va_high - va_low
    band = max(va_range * 0.05, 1e-9)
    if close > va_high + band:
        return _ZONE_LABELS[0]
    if close >= va_high - band:
        return _ZONE_LABELS[1]
    if close > va_low + band:
        return _ZONE_LABELS[2]
    if close >= va_low - band:
        return _ZONE_LABELS[3]
    return _ZONE_LABELS[4]


def compute_tpo_score(df: pd.DataFrame) -> pd.DataFrame:
    """Add tpo_score, tpo_score_label, price_zone_label columns to df.

    Parameters
    ----------
    df:
        DataFrame with columns vpoc, va_high, va_low, close (float).
        Typically produced by engine.backtest.tpo_profile.compute_tpo_profile().

    Returns
    -------
    df with three new columns added in-place (copy returned).
    """
    missing = _REQUIRED - set(df.columns)
    if missing:
        raise ValueError(f"compute_tpo_score: missing columns {sorted(missing)}")

    out = df.copy()
    scores = np.vectorize(_tpo_score_row)(
        out["close"].to_numpy(),
        out["vpoc"].to_numpy(),
        out["va_high"].to_numpy(),
        out["va_low"].to_numpy(),
    )
    out["tpo_score"] = scores
    out["tpo_score_label"] = [_score_label(s) for s in scores]
    out["price_zone_label"] = [
        _zone_label(c, h, l)
        for c, h, l in zip(
            out["close"].to_numpy(),
            out["va_high"].to_numpy(),
            out["va_low"].to_numpy(),
        )
    ]
    return out
