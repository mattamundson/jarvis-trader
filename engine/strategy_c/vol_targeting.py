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

Blended vol estimator (T1-2 upgrade, 2026-06-17):
  realized_vol = blend_fast_weight * vol_short + (1 - blend_fast_weight) * vol_long
  Default: 0.40 * vol_5d + 0.60 * vol_21d
  Rationale: pure 5-day is too reactive to single-spike days (Jun 5 QQQ -4.92%
  caused a 38.6% CRISIS reading). Pure 21-day is too sluggish. The 40/60 blend
  produces ~23% on the Jun 12 week vs raw 38.6% — still ELEVATED (correctly)
  but not CRISIS. Validated against Strategy C+ signal history 2026-04-24→2026-06-12.
  To recover legacy behavior: set blend_fast_weight=1.0, lookback_days=5.

Vol spike winsorization (T2-8 upgrade, 2026-06-17):
  Returns winsorized at winsorize_sigma × trailing 60-day avg return magnitude.
  Prevents a single outlier day from dominating the vol window.
  The winsorized return is capped, not dropped — still contributes to the sample.
  Set winsorize_sigma=None to disable (legacy behavior).
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
        Days of daily returns for the SHORT-window vol computation (default 10).
        In blended mode this is the fast window; the slow window is lookback_long_days.
    lookback_long_days : int
        Days for the SLOW-window vol component in blended mode (default 21).
        Ignored if blend_fast_weight == 1.0 (pure fast mode).
    blend_fast_weight : float
        Weight on the short-window vol estimate in the blend. [0.0, 1.0]
        Default 0.40 (40% 5-day + 60% 21-day).
        Set to 1.0 to recover legacy single-window behavior.
    vol_floor : float
        Minimum vol assumed (prevents scale > 1 in ultra-low-vol periods)
    max_scale : float
        Maximum scaling factor (1.0 = unlevered; never > 1.0 for this strategy)
    blend_es_nq : float
        Weight on NQ vol vs ES vol in composite (0.5 = equal blend)
    winsorize_sigma : float | None
        Winsorize daily returns at this multiple of the trailing 60-day avg
        absolute return before computing realized vol. Default 3.0.
        Set to None to disable winsorization.
    winsorize_lookback : int
        Lookback days for computing the reference avg absolute return for
        winsorization. Default 60.
    """

    def __init__(
        self,
        vol_target: float = 8.0,
        lookback_days: int = 10,
        lookback_long_days: int = 21,
        blend_fast_weight: float = 1.0,  # legacy single-window; engine_v2 passes 0.40 explicitly
        vol_floor: float = 6.0,
        max_scale: float = 1.0,
        blend_es_nq: float = 0.5,
        winsorize_sigma: Optional[float] = None,  # legacy off; engine_v2 passes 3.0 explicitly
        winsorize_lookback: int = 60,
    ):
        self.vol_target = vol_target
        self.lookback_days = lookback_days
        self.lookback_long_days = lookback_long_days
        self.blend_fast_weight = blend_fast_weight
        self.vol_floor = vol_floor
        self.max_scale = max_scale
        self.blend_es_nq = blend_es_nq
        self.winsorize_sigma = winsorize_sigma
        self.winsorize_lookback = winsorize_lookback

    # ──────────────────────────────────────────────────────────────────────────
    # Core vol computation
    # ──────────────────────────────────────────────────────────────────────────

    def _winsorize_returns(self, returns: pd.Series) -> pd.Series:
        """
        Winsorize returns at winsorize_sigma × trailing avg |return|.
        Uses the full available history before the current window for the
        reference, capped to winsorize_lookback days.
        """
        if self.winsorize_sigma is None or len(returns) < 5:
            return returns

        # Use the available series as the reference for avg |ret|
        ref = returns.tail(self.winsorize_lookback)
        avg_abs = float(ref.abs().mean())
        if avg_abs == 0:
            return returns

        cap = self.winsorize_sigma * avg_abs
        return returns.clip(-cap, cap)

    def _single_window_vol(
        self,
        returns: pd.Series,
        window: int,
    ) -> float:
        """Annualized vol from the last `window` returns."""
        sample = returns.tail(window)
        if len(sample) < 3:
            return 15.0  # conservative fallback
        ann = np.sqrt(252)
        v = float(sample.std() * ann * 100)
        return 15.0 if np.isnan(v) else v

    def compute_realized_vol(
        self,
        es_prices: pd.Series,
        nq_prices: pd.Series,
        as_of_date: Optional[pd.Timestamp] = None,
    ) -> float:
        """
        Compute blended ES/NQ realized annualized volatility as of a date.

        Returns annualized vol in percent (e.g., 12.5 = 12.5%).

        In blended mode (default):
          vol = blend_fast_weight * vol_short + (1 - blend_fast_weight) * vol_long

        In legacy mode (blend_fast_weight=1.0):
          vol = vol_short  (single window, original behavior)
        """
        # Slice to as_of_date — need enough history for long window + winsorize
        max_lookback = max(self.lookback_long_days, self.winsorize_lookback) + 5
        if as_of_date is not None:
            es = es_prices.loc[:as_of_date].tail(max_lookback + 1)
            nq = nq_prices.loc[:as_of_date].tail(max_lookback + 1)
        else:
            es = es_prices.tail(max_lookback + 1)
            nq = nq_prices.tail(max_lookback + 1)

        if len(es) < 3 or len(nq) < 3:
            return max(self.vol_floor, 15.0)

        es_ret = np.log(es / es.shift(1)).dropna()
        nq_ret = np.log(nq / nq.shift(1)).dropna()

        # Winsorize before computing vol
        es_ret_w = self._winsorize_returns(es_ret)
        nq_ret_w = self._winsorize_returns(nq_ret)

        # Short-window vol (fast component)
        es_vol_fast = self._single_window_vol(es_ret_w, self.lookback_days)
        nq_vol_fast = self._single_window_vol(nq_ret_w, self.lookback_days)
        composite_fast = (
            self.blend_es_nq * nq_vol_fast + (1 - self.blend_es_nq) * es_vol_fast
        )

        if self.blend_fast_weight >= 1.0 and self.winsorize_sigma is None:
            # Legacy mode — bit-for-bit the master formula that feeds the v1 live
            # signal (tests/test_strategy_c_lag_and_vol_legacy.py pins this).
            # A NaN on either leg → conservative fallback (2026-05-06 incident).
            es_l, nq_l = es.tail(self.lookback_days + 1), nq.tail(self.lookback_days + 1)
            es_r = np.log(es_l / es_l.shift(1)).dropna()
            nq_r = np.log(nq_l / nq_l.shift(1)).dropna()
            ann = np.sqrt(252)
            es_vol = float(es_r.tail(self.lookback_days).std() * ann * 100)
            nq_vol = float(nq_r.tail(self.lookback_days).std() * ann * 100)
            legacy = self.blend_es_nq * nq_vol + (1 - self.blend_es_nq) * es_vol
            if np.isnan(legacy) or legacy <= 0:
                return max(self.vol_floor, 15.0)
            return max(legacy, self.vol_floor)
        if self.blend_fast_weight >= 1.0:
            if np.isnan(composite_fast) or composite_fast <= 0:
                return max(self.vol_floor, 15.0)
            return max(composite_fast, self.vol_floor)

        # Long-window vol (slow component)
        es_vol_slow = self._single_window_vol(es_ret_w, self.lookback_long_days)
        nq_vol_slow = self._single_window_vol(nq_ret_w, self.lookback_long_days)
        composite_slow = (
            self.blend_es_nq * nq_vol_slow + (1 - self.blend_es_nq) * es_vol_slow
        )

        # Blended composite
        blended = (
            self.blend_fast_weight * composite_fast
            + (1 - self.blend_fast_weight) * composite_slow
        )
        # NaN guard (master, 2026-05-06 incident) — a NaN vol would default the
        # vol-target scale to 1.0 (full exposure). Fall back to a conservative vol.
        if np.isnan(blended) or blended <= 0:
            return max(self.vol_floor, 15.0)
        return max(blended, self.vol_floor)

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
            "blend_fast_weight": self.blend_fast_weight,
            "lookback_days": self.lookback_days,
            "lookback_long_days": self.lookback_long_days,
            "winsorize_sigma": self.winsorize_sigma,
        }
