"""Market-wide macro trend regime — RISK_ON / RISK_OFF / NEUTRAL / UNKNOWN.

Derived from the two REAL trend edges of the 2026-07-02 X-bookmark scan applied to
SPY as an S&P proxy (MES ≈ ES ≈ SPX): the weekly Supertrend(ATR10, ×3) trend and the
monthly 12mo-SMA momentum state. Agreement bullish → RISK_ON; agreement bearish →
RISK_OFF; disagreement → NEUTRAL; stale/missing data → UNKNOWN (fail-safe).

Read-only, no side effects. Consumed by ``GET /macro/regime`` and, when the
``ENABLE_MACRO_TREND_BIAS`` feature flag is on, as an ADVISORY context feature in the
futures pipeline. It is NEVER a mechanical trade gate and never routes capital.
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# Weekly/monthly signals move slowly — a multi-hour cache is plenty and keeps the
# per-cycle pipeline read cheap (SPY bar load + resample is otherwise repeated work).
_CACHE_TTL_SEC = 6 * 3600
_cache: dict = {"ts": 0.0, "value": None}


def _bias_line(state: str) -> str:
    """Advisory bias sentence appended to the LLM context (empty for NEUTRAL/UNKNOWN)."""
    return {
        "RISK_ON": "MACRO TREND: RISK_ON (weekly SPX uptrend + monthly momentum) "
                   "— favor longs, normal size.",
        "RISK_OFF": "MACRO TREND: RISK_OFF (weekly downtrend + below 12mo SMA) "
                    "— de-emphasize new longs, reduce size.",
    }.get(state, "")


def _compute() -> dict:
    try:
        import spy_paper_track_lib as lib
        from generate_sma12_momentum_signals import generate_sma12_momentum_signals
        from generate_supertrend_signals import generate_supertrend_signals

        daily = lib._load_spy_daily()
        agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
        wk = daily.resample("W-FRI").agg(agg).dropna()
        mo = daily.resample("ME").agg(agg).dropna()

        st = generate_supertrend_signals(wk, atr_period=10, multiplier=3.0)
        mm = generate_sma12_momentum_signals(mo, sma_len=12)
        wk_up = bool(st["trend"].iloc[-1] == 1)
        mo_up = bool(mm["position"].iloc[-1] > 0)

        last_bar = pd.Timestamp(daily.index[-1])
        stale_days = (datetime.now(timezone.utc).replace(tzinfo=None) - last_bar.to_pydatetime()).days
        if stale_days > 10:
            state = "UNKNOWN"
        elif wk_up and mo_up:
            state = "RISK_ON"
        elif (not wk_up) and (not mo_up):
            state = "RISK_OFF"
        else:
            state = "NEUTRAL"

        return {
            "state": state,
            "weekly_trend": "UP" if wk_up else "DOWN",
            "monthly_momentum": "ABOVE" if mo_up else "BELOW",
            "asof": str(last_bar.date()),
            "spy_close": round(float(daily["close"].iloc[-1]), 2),
            "bias_line": _bias_line(state),
            "stale_days": int(stale_days),
            "components": {
                "weekly_supertrend_atr10x3": wk_up,
                "monthly_sma12_momentum": mo_up,
            },
        }
    except Exception as exc:  # fail-safe: never raise into the pipeline
        return {
            "state": "UNKNOWN", "weekly_trend": None, "monthly_momentum": None,
            "asof": None, "spy_close": None, "bias_line": "", "error": str(exc),
            "components": {},
        }


def compute_macro_regime(force: bool = False) -> dict:
    """Return the current macro trend regime (cached ``_CACHE_TTL_SEC``)."""
    now = time.time()
    if not force and _cache["value"] is not None and (now - _cache["ts"]) < _CACHE_TTL_SEC:
        return _cache["value"]
    result = _compute()
    _cache["ts"] = now
    _cache["value"] = result
    return result
