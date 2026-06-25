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


def compute_tpo_score_tos(df: pd.DataFrame) -> pd.DataFrame:
    """Faithful port of the TOS AA_CoreyTscorev2 ScoreTotal (the chart panel).

    Unlike ``compute_tpo_score`` (a normalized distance reinterpretation), this
    reproduces the ThinkScript exactly: five ticsize-scaled sub-scores whose sign
    drives the chart's "TPO Score is Positive/Negative" label. The ticsize factor
    cancels for the sign, so this sums the five unit components and normalizes by
    5 for cross-instrument comparability.

        s_vah   = +1 close>VAH / -1 close<VAL / 0      (scorevah)
        s_val   = +1 close>VAH / -1 close<VAL / 0      (scoreval; identical to s_vah)
        s_poc   = +1 close>VPOC / -1 close<VPOC / 0
        s_vabal = +1 close>VAbal / -1 close<VAbal / 0  (VAbal=(VAH+VAL)/2)
        s_imbal = +1 VAbal>VPOC / -1 VAbal<VPOC / 0    (profile skew; close-independent)

    Adds columns: tpo_score_tos (-1..1), tpo_score_tos_sign
    ("POSITIVE"/"NEUTRAL"/"NEGATIVE"). Requires vpoc/va_high/va_low/close
    (prior-session via compute_tpo_profile -> point-in-time safe).
    """
    missing = _REQUIRED - set(df.columns)
    if missing:
        raise ValueError(f"compute_tpo_score_tos: missing columns {sorted(missing)}")
    out = df.copy()
    close = out["close"]
    poc = out["vpoc"]
    vah = out["va_high"]
    val = out["va_low"]
    vabal = (vah + val) / 2

    def _sign_above_below(x: pd.Series, lo: pd.Series, hi: pd.Series) -> pd.Series:
        return np.where(x > hi, 1.0, np.where(x < lo, -1.0, 0.0))

    s_vah = _sign_above_below(close, val, vah)  # +1 above VAH, -1 below VAL
    s_val = s_vah  # the ThinkScript scoreval is identical to scorevah
    s_poc = np.sign((close - poc).to_numpy())
    s_vabal = np.sign((close - vabal).to_numpy())
    s_imbal = np.sign((vabal - poc).to_numpy())

    total = s_vah + s_val + s_poc + s_vabal + s_imbal  # range -5..+5
    out["tpo_score_tos"] = total / 5.0
    out["tpo_score_tos_sign"] = np.where(
        total > 0, "POSITIVE", np.where(total < 0, "NEGATIVE", "NEUTRAL")
    )
    # NaN profile -> neutral / NaN score
    undefined = poc.isna() | vah.isna() | val.isna()
    out.loc[undefined, "tpo_score_tos"] = np.nan
    out.loc[undefined.to_numpy(), "tpo_score_tos_sign"] = "NEUTRAL"
    return out


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
    with np.errstate(invalid="ignore", divide="ignore"):
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
        for c, h, l in zip(  # noqa: E741  # OHLC convention
            out["close"].to_numpy(),
            out["va_high"].to_numpy(),
            out["va_low"].to_numpy(), strict=False,
        )
    ]
    return out
