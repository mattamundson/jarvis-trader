"""
regime_detector.py — daily market regime conditions that warrant halting strategies.

Two conditions trigger a REGIME_ALERT:
  1. MES daily RSI(14) < 30.0 for N consecutive days (default 5)
     → sustained oversold condition; mean-reversion edge may invert
  2. VIX daily close > 25.0 for N consecutive days (default 5)
     → elevated volatility; ATR-based stops may be structurally too tight

Both conditions are evaluated using pure pandas with no external TA library
dependency — importable without the engine venv fully loaded.

Typical usage (from CLI wrapper or engine endpoint):

    from risk.regime_detector import evaluate_regime, RegimeStatus

    status = evaluate_regime(mes_daily_df=mes_df, vix_daily_df=vix_df)
    if status.alert:
        print(status.message)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

# ---------------------------------------------------------------------------
# Config constants
# ---------------------------------------------------------------------------

RSI_PERIOD: int = 14
MES_RSI_ALERT_THRESHOLD: float = 30.0  # fire if RSI < this for N days
VIX_ALERT_THRESHOLD: float = 25.0  # fire if VIX > this for N days
CONSECUTIVE_DAYS: int = 5  # how many consecutive days must satisfy condition


# ---------------------------------------------------------------------------
# Core computation helpers
# ---------------------------------------------------------------------------


def compute_rsi(closes: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    """Compute RSI using Wilder smoothing (alpha = 1/period).

    Returns a Series aligned with the input index; first (period) values are NaN.
    """
    delta = closes.diff()
    gains = delta.clip(lower=0.0)
    losses = (-delta).clip(lower=0.0)
    avg_gain = gains.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = losses.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    # Use epsilon instead of NaN for zero losses so RSI approaches 100 on pure uptrends
    rs = avg_gain / avg_loss.where(avg_loss > 0, other=1e-10)
    return 100.0 - (100.0 / (1.0 + rs))


def mes_rsi_alert_triggered(
    df: pd.DataFrame,
    rsi_threshold: float = MES_RSI_ALERT_THRESHOLD,
    consecutive: int = CONSECUTIVE_DAYS,
    rsi_period: int = RSI_PERIOD,
) -> tuple[bool, float | None]:
    """Return (triggered, latest_rsi).

    `triggered` is True when the last `consecutive` RSI values are all below
    `rsi_threshold`.  Requires at least (rsi_period + consecutive) rows.
    """
    if df is None or df.empty or len(df) < rsi_period + consecutive:
        return False, None
    if "close" not in df.columns:
        return False, None

    rsi = compute_rsi(df["close"], period=rsi_period)
    rsi_clean = rsi.dropna()
    if len(rsi_clean) < consecutive:
        return False, None

    latest_rsi = float(rsi_clean.iloc[-1])
    window = rsi_clean.iloc[-consecutive:]
    triggered = bool((window < rsi_threshold).all())
    return triggered, latest_rsi


def vix_alert_triggered(
    df: pd.DataFrame,
    vix_threshold: float = VIX_ALERT_THRESHOLD,
    consecutive: int = CONSECUTIVE_DAYS,
) -> tuple[bool, float | None]:
    """Return (triggered, latest_vix).

    `triggered` is True when the last `consecutive` VIX closes are all above
    `vix_threshold`.  Requires at least `consecutive` rows.
    """
    if df is None or df.empty or len(df) < consecutive:
        return False, None
    if "close" not in df.columns:
        return False, None

    latest_vix = float(df["close"].iloc[-1])
    window = df["close"].iloc[-consecutive:]
    triggered = bool((window > vix_threshold).all())
    return triggered, latest_vix


# ---------------------------------------------------------------------------
# Public result type and top-level evaluation
# ---------------------------------------------------------------------------


@dataclass
class RegimeStatus:
    alert: bool
    message: str
    mes_rsi: Optional[float] = None
    vix_level: Optional[float] = None
    triggers: list[str] = field(default_factory=list)


def evaluate_regime(
    mes_daily_df: Optional[pd.DataFrame] = None,
    vix_daily_df: Optional[pd.DataFrame] = None,
    rsi_threshold: float = MES_RSI_ALERT_THRESHOLD,
    vix_threshold: float = VIX_ALERT_THRESHOLD,
    consecutive: int = CONSECUTIVE_DAYS,
    rsi_period: int = RSI_PERIOD,
) -> RegimeStatus:
    """Evaluate both regime conditions and return a single RegimeStatus.

    Either DataFrame may be None or empty — that condition is simply skipped.
    An alert fires if ANY condition is met.
    """
    triggers: list[str] = []
    mes_rsi: Optional[float] = None
    vix_level: Optional[float] = None

    # MES RSI check
    rsi_triggered, mes_rsi = mes_rsi_alert_triggered(
        mes_daily_df, rsi_threshold=rsi_threshold, consecutive=consecutive, rsi_period=rsi_period
    )
    if rsi_triggered:
        triggers.append(
            f"MES RSI(14)={mes_rsi:.1f} < {rsi_threshold} for " f"{consecutive} consecutive days"
        )

    # VIX check
    vix_triggered, vix_level = vix_alert_triggered(
        vix_daily_df, vix_threshold=vix_threshold, consecutive=consecutive
    )
    if vix_triggered:
        triggers.append(
            f"VIX={vix_level:.1f} > {vix_threshold} for " f"{consecutive} consecutive days"
        )

    alert = len(triggers) > 0
    if alert:
        cond_str = " AND ".join(triggers) if len(triggers) > 1 else triggers[0]
        message = (
            f"REGIME ALERT: Conditions met for strategy pause.\n"
            f"Condition(s): {cond_str}\n"
            f"Action: Review strategies. Consider pausing trend-following on MES/MGC."
        )
    else:
        parts = []
        if mes_rsi is not None:
            parts.append(f"MES RSI={mes_rsi:.1f}")
        if vix_level is not None:
            parts.append(f"VIX={vix_level:.1f}")
        summary = ", ".join(parts) if parts else "no data"
        message = f"Regime OK ({summary}) — no alert triggered."

    return RegimeStatus(
        alert=alert,
        message=message,
        mes_rsi=mes_rsi,
        vix_level=vix_level,
        triggers=triggers,
    )
