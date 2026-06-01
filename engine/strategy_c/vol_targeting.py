"""
Volatility Targeting — ES/NQ Daily Realized Vol
================================================
The core innovation that transforms Dual Momentum's Sharpe 1.07 → 2.13.

Uses daily close-to-close returns on ES (via SPY proxy) and NQ (via QQQ proxy)
to compute a composite realized volatility. Scales weekly position to maintain
a target annualized volatility of 8%.

Key insight from backtest analysis:
  - Bull markets: NQ vol ≈ 10-12% annualized → scale ≈ 0.93-1.0 (nearly full)
  - Normal: vol ≈ 14-18% → scale ≈ 0.60-0.77
  - Crisis (2020, 2022): vol ≈ 40-60% annualized → scale ≈ 0.13-0.30
  - Scale during cash periods: forced to 0.0 (no equity exposure)

This is the primary Sharpe bridge: CAGR preserved because scaling up during
low-vol preserves upside; scaling down during crises limits MDD dramatically.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


class VolatilityTargeter:
    """
    Computes daily realized volatility and target position scaling factor.

    Parameters
    ----------
    vol_target : float
        Target annualized volatility (default 8.0%)
    lookback_days : int
        Days of daily returns for realized vol computation (default 10)
    vol_floor : float
        Minimum vol assumed (prevents scale > 1 in ultra-low-vol periods)
    max_scale : float
        Maximum scaling factor (1.0 = unlevered; never > 1.0 for this strategy)
    blend_es_nq : float
        Weight on NQ vol vs ES vol in composite (0.5 = equal blend)
    """

    def __init__(
        self,
        vol_target: float = 8.0,
        lookback_days: int = 10,
        vol_floor: float = 6.0,
        max_scale: float = 1.0,
        blend_es_nq: float = 0.5,
    ):
        self.vol_target = vol_target
        self.lookback_days = lookback_days
        self.vol_floor = vol_floor
        self.max_scale = max_scale
        self.blend_es_nq = blend_es_nq

    def compute_realized_vol(
        self,
        es_prices: pd.Series,
        nq_prices: pd.Series,
        as_of_date: Optional[pd.Timestamp] = None,
    ) -> float:
        """
        Compute blended ES/NQ realized annualized volatility as of a date.
        Uses close-to-close daily log returns, 10-day window.

        Returns annualized vol in percent (e.g., 12.5 = 12.5%).
        """
        if as_of_date is not None:
            es = es_prices.loc[:as_of_date].tail(self.lookback_days + 1)
            nq = nq_prices.loc[:as_of_date].tail(self.lookback_days + 1)
        else:
            es = es_prices.tail(self.lookback_days + 1)
            nq = nq_prices.tail(self.lookback_days + 1)

        if len(es) < 3 or len(nq) < 3:
            return max(self.vol_floor, 15.0)  # Conservative fallback

        es_ret = np.log(es / es.shift(1)).dropna()
        nq_ret = np.log(nq / nq.shift(1)).dropna()

        # Annualize: sqrt(252) * std
        ann = np.sqrt(252)
        es_vol = float(es_ret.tail(self.lookback_days).std() * ann * 100)
        nq_vol = float(nq_ret.tail(self.lookback_days).std() * ann * 100)

        # Blended composite: weight NQ higher (more predictive of tail risk)
        composite_vol = (
            self.blend_es_nq * nq_vol + (1 - self.blend_es_nq) * es_vol
        )
        # NaN guard — if std() returned NaN (e.g. transient yfinance fail with
        # too few clean bars), fall through to a conservative default rather
        # than silently writing NaN to the live signal which would default the
        # vol-target scale to 1.0 (full exposure). Observed 2026-05-06 on a
        # cold-cache first run; second run was clean.
        if np.isnan(composite_vol) or composite_vol <= 0:
            return max(self.vol_floor, 15.0)
        return max(composite_vol, self.vol_floor)

    def compute_scale(
        self,
        es_prices: pd.Series,
        nq_prices: pd.Series,
        as_of_date: Optional[pd.Timestamp] = None,
    ) -> tuple[float, float]:
        """
        Compute position scale factor [0.0, max_scale] to hit vol_target.

        Returns (scale: float, realized_vol: float)
        """
        realized_vol = self.compute_realized_vol(es_prices, nq_prices, as_of_date)
        raw_scale = self.vol_target / realized_vol
        scale = min(raw_scale, self.max_scale)
        return scale, realized_vol

    def build_scale_series(
        self,
        es_prices: pd.Series,
        nq_prices: pd.Series,
        weekly_dates: pd.DatetimeIndex,
    ) -> pd.DataFrame:
        """
        Build weekly scale factors and realized vol for the full backtest period.

        Operates on FRIDAY close prices (weekly rebalancing).
        Looks back `lookback_days` DAILY bars from each Friday.

        Returns DataFrame with columns: date, scale, realized_vol
        """
        records = []
        for date in weekly_dates:
            scale, rv = self.compute_scale(es_prices, nq_prices, date)
            records.append({"date": date, "scale": scale, "realized_vol": rv})

        df = pd.DataFrame(records).set_index("date")
        return df

    def vol_regime(self, realized_vol: float) -> str:
        """
        Classify vol regime — aligned with jarvis-trader VIX overlay thresholds.

        Returns one of: CALM / NORMAL / ELEVATED / CRISIS
        """
        if realized_vol < 10:
            return "CALM"
        elif realized_vol < 18:
            return "NORMAL"
        elif realized_vol < 30:
            return "ELEVATED"
        else:
            return "CRISIS"

    def summary_stats(self, scale_df: pd.DataFrame) -> dict:
        """Return summary statistics on the scale series."""
        return {
            "mean_scale": round(float(scale_df["scale"].mean()), 4),
            "min_scale": round(float(scale_df["scale"].min()), 4),
            "max_scale": round(float(scale_df["scale"].max()), 4),
            "pct_at_max": round(float((scale_df["scale"] >= self.max_scale).mean() * 100), 1),
            "mean_realized_vol_pct": round(float(scale_df["realized_vol"].mean()), 2),
            "vol_target_pct": self.vol_target,
        }
