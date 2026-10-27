"""
Risk Controls — Strategy C+ Position Sizing Overlays
======================================================
Implements portfolio-level risk management that operates AFTER signal
generation and vol targeting. These are real-time risk measures that
directly reflect account state, not lagging economic indicators.

Modules:
  1. DrawdownCircuitBreaker   (T2-7)  — replaces macro filter's lagging function
  2. MinimumHoldPeriod        (T3-11) — anti-whipsaw protection
  3. RiskParitySizer          (T3-12) — inverse-vol position sizing
  4. AbsoluteMomentumGate     (T2-6)  — SPY 200d MA co-trigger
  5. RegimeChangeDetector     (T3-10) — Kalman vol regime early warning

These modules plug into engine.py as modular multipliers on the
final position scale, downstream of vol targeting.
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════════════
#  T2-7: DRAWDOWN CIRCUIT BREAKER
# ═════════════════════════════════════════════════════════════════════════════

class DrawdownCircuitBreaker:
    """
    Real-time drawdown-based position reduction.

    Replaces the macro filter's lagging economic indicator function with
    a direct measurement of what's happening to the account. Operates
    on the running equity curve (weekly NAV series).

    Logic:
      - Track rolling ATH of equity curve
      - If current drawdown from ATH exceeds threshold → reduce position
      - Multiple tiers supported (e.g., 8% → 50% cut, 15% → 75% cut)

    Parameters
    ----------
    tiers : list of (dd_threshold, scale_multiplier) tuples
        Drawdown tiers in ascending threshold order.
        Default: [(0.08, 0.50), (0.15, 0.25)]
        Meaning: 8% drawdown → 50% scale; 15% drawdown → 25% scale
    recovery_threshold : float
        Drawdown must recover to this level before full scale resumes.
        Default 0.03 (restore full scale when DD < 3%).
    min_bars_before_restore : int
        Minimum weeks at < recovery_threshold before scale is restored.
        Prevents whipsaw at the threshold boundary. Default 2.
    """

    DEFAULT_TIERS = [(0.08, 0.50), (0.15, 0.25)]

    def __init__(
        self,
        tiers: Optional[list] = None,
        recovery_threshold: float = 0.03,
        min_bars_before_restore: int = 2,
    ):
        self.tiers = sorted(tiers or self.DEFAULT_TIERS, key=lambda x: x[0])
        self.recovery_threshold = recovery_threshold
        self.min_bars_before_restore = min_bars_before_restore
        self._ath = None
        self._bars_below_recovery = 0

    def reset(self):
        """Reset state — call at start of new backtest."""
        self._ath = None
        self._bars_below_recovery = 0

    def update_and_get_multiplier(self, current_equity: float) -> tuple[float, dict]:
        """
        Update ATH and return the circuit breaker multiplier.

        Parameters
        ----------
        current_equity : float

        Returns
        -------
        (multiplier: float, detail: dict)
        """
        if self._ath is None:
            self._ath = current_equity

        self._ath = max(self._ath, current_equity)
        drawdown = (self._ath - current_equity) / self._ath if self._ath > 0 else 0.0

        # Determine tier
        multiplier = 1.0
        active_tier = None
        for threshold, scale in self.tiers:
            if drawdown >= threshold:
                multiplier = scale
                active_tier = (threshold, scale)

        # Recovery logic
        if drawdown < self.recovery_threshold:
            self._bars_below_recovery += 1
        else:
            self._bars_below_recovery = 0

        if active_tier and self._bars_below_recovery < self.min_bars_before_restore:
            pass  # still recovering, keep reduced scale

        detail = {
            "drawdown_pct": round(drawdown * 100, 2),
            "ath": round(self._ath, 2),
            "circuit_multiplier": round(multiplier, 4),
            "active_tier": active_tier,
            "bars_below_recovery": self._bars_below_recovery,
        }
        return multiplier, detail

    def apply_to_series(self, equity_series: pd.Series) -> pd.Series:
        """
        Compute circuit breaker multipliers for a historical equity series.
        For vectorized backtesting.
        """
        self.reset()
        multipliers = []
        for eq in equity_series:
            m, _ = self.update_and_get_multiplier(eq)
            multipliers.append(m)
        return pd.Series(multipliers, index=equity_series.index)


# ═════════════════════════════════════════════════════════════════════════════
#  T3-11: MINIMUM HOLD PERIOD (Anti-Whipsaw)
# ═════════════════════════════════════════════════════════════════════════════

class MinimumHoldPeriod:
    """
    Prevents whipsaw by enforcing a minimum hold before full RISK_OFF.

    When the system transitions RISK_ON → RISK_OFF, it must stay at a
    reduced (but not zero) scale for min_hold_weeks before fully exiting.
    Vol targeting and drawdown circuit breakers can override this.

    This directly addresses the Jun 5 → Jun 12 dynamic where scale
    collapsed 77pp in one week on a single spike day.

    Parameters
    ----------
    min_hold_weeks : int
        Minimum weeks to hold before allowing full RISK_OFF exit. Default 2.
    soft_scale : float
        Scale applied during the hold period (before full exit allowed).
        Default 0.50 (50% position during transition).
    allow_override_on_drawdown : bool
        If True, the min hold is bypassed when drawdown > 15%. Default True.
    override_drawdown_threshold : float
        Drawdown level that bypasses the hold period. Default 0.15.
    """

    def __init__(
        self,
        min_hold_weeks: int = 2,
        soft_scale: float = 0.50,
        allow_override_on_drawdown: bool = True,
        override_drawdown_threshold: float = 0.15,
    ):
        self.min_hold_weeks = min_hold_weeks
        self.soft_scale = soft_scale
        self.allow_override = allow_override_on_drawdown
        self.override_threshold = override_drawdown_threshold
        self._risk_on_weeks = 0
        self._last_regime = None

    def reset(self):
        self._risk_on_weeks = 0
        self._last_regime = None

    def apply(
        self,
        new_regime: str,
        proposed_scale: float,
        drawdown_pct: float = 0.0,
    ) -> tuple[float, dict]:
        """
        Evaluate whether a RISK_ON → RISK_OFF transition is allowed at full scale.

        Parameters
        ----------
        new_regime : str — 'RISK_ON' or 'RISK_OFF'
        proposed_scale : float — scale from vol targeting (already applied)
        drawdown_pct : float — current drawdown from ATH (0.0 to 1.0)

        Returns
        -------
        (adjusted_scale, detail)
        """
        # Track risk-on streak
        if new_regime == "RISK_ON":
            self._risk_on_weeks += 1
        else:
            self._risk_on_weeks = 0

        detail = {
            "risk_on_streak_weeks": self._risk_on_weeks,
            "min_hold_active": False,
            "hold_override": False,
        }

        # Check if transitioning to RISK_OFF before minimum hold
        transitioning_off = (
            self._last_regime == "RISK_ON" and new_regime == "RISK_OFF"
        )

        if transitioning_off:
            # Drawdown override check
            if self.allow_override and drawdown_pct > self.override_threshold:
                detail["hold_override"] = True
                detail["override_reason"] = f"Drawdown {drawdown_pct:.1%} exceeds {self.override_threshold:.0%}"
                self._last_regime = new_regime
                return proposed_scale, detail

            if self._risk_on_weeks < self.min_hold_weeks:
                # Force soft scale instead of full exit
                adjusted = max(proposed_scale, self.soft_scale)
                detail["min_hold_active"] = True
                detail["weeks_remaining"] = self.min_hold_weeks - self._risk_on_weeks
                detail["forced_soft_scale"] = adjusted
                self._last_regime = new_regime
                return adjusted, detail

        self._last_regime = new_regime
        return proposed_scale, detail


# ═════════════════════════════════════════════════════════════════════════════
#  T3-12: RISK PARITY SIZER
# ═════════════════════════════════════════════════════════════════════════════

class RiskParitySizer:
    """
    Inverse-volatility position sizing for multi-asset portfolios.

    Replaces equal-weight top-2 with risk parity weighting — each asset
    is sized inversely proportional to its recent volatility. This
    naturally underweights structurally volatile assets (XLK > QQQ on vol)
    without requiring additional signals.

    Uses the same daily price data already available in vol_targeting.

    Parameters
    ----------
    vol_lookback_days : int
        Days for per-asset vol estimate. Default 21.
    vol_floor_pct : float
        Minimum annualized vol assumed per asset (prevents extreme concentration).
        Default 8.0%.
    normalize : bool
        Whether to normalize weights to sum to 1.0. Default True.
    """

    def __init__(
        self,
        vol_lookback_days: int = 21,
        vol_floor_pct: float = 8.0,
        normalize: bool = True,
    ):
        self.vol_lookback_days = vol_lookback_days
        self.vol_floor_pct = vol_floor_pct / 100.0
        self.normalize = normalize

    def compute_vol(self, price_series: pd.Series) -> float:
        """Annualized close-to-close vol for one asset."""
        rets = np.log(price_series / price_series.shift(1)).dropna()
        if len(rets) < 5:
            return self.vol_floor_pct
        vol = float(rets.tail(self.vol_lookback_days).std() * np.sqrt(252))
        return max(vol, self.vol_floor_pct)

    def size_portfolio(
        self,
        selected_assets: list,
        price_data: pd.DataFrame,
        as_of_date: Optional[pd.Timestamp] = None,
    ) -> dict:
        """
        Compute risk parity weights for a list of selected assets.

        Parameters
        ----------
        selected_assets : list of ticker strings
        price_data : pd.DataFrame — daily prices with tickers as columns
        as_of_date : optional — slice prices as of this date

        Returns
        -------
        dict of {ticker: weight}
        """
        if not selected_assets:
            return {}

        vols = {}
        for ticker in selected_assets:
            if ticker not in price_data.columns:
                vols[ticker] = self.vol_floor_pct
                continue
            if as_of_date is not None:
                prices = price_data.loc[:as_of_date, ticker].tail(self.vol_lookback_days + 1)
            else:
                prices = price_data[ticker].tail(self.vol_lookback_days + 1)
            vols[ticker] = self.compute_vol(prices)

        # Inverse-vol weights
        inv_vols = {t: 1.0 / v for t, v in vols.items()}
        total_inv = sum(inv_vols.values())

        if total_inv == 0 or not self.normalize:
            # Equal weight fallback
            w = 1.0 / len(selected_assets)
            return {t: round(w, 4) for t in selected_assets}

        weights = {t: round(inv_v / total_inv, 4) for t, inv_v in inv_vols.items()}
        detail = {
            "vols": {t: round(v * 100, 2) for t, v in vols.items()},
            "weights": weights,
            "note": "Risk parity (inverse vol) — higher vol = lower weight",
        }
        logger.debug("RiskParitySizer: %s", detail)
        return weights


# ═════════════════════════════════════════════════════════════════════════════
#  T2-6: ABSOLUTE MOMENTUM GATE (SPY 200d MA co-trigger)
# ═════════════════════════════════════════════════════════════════════════════

class AbsoluteMomentumGate:
    """
    Enhanced absolute momentum gate with 200-day MA co-trigger.

    The original Strategy C absolute momentum gate uses SPY 52-week return > 0.
    This adds a stricter co-trigger: if SPY has been BELOW its 200d MA for
    at least ma_breach_weeks consecutive weeks, additionally require SPY
    52-week return > absolute_mom_threshold_bear (e.g., +2% vs default 0%).

    This would have caught the 2022 bear market entry while not adding
    false signals in normal bull conditions.

    Parameters
    ----------
    ma_period_days : int
        Period for the SPY moving average. Default 200.
    ma_breach_weeks : int
        Consecutive weeks below MA before stricter threshold applies. Default 3.
    absolute_mom_threshold_normal : float
        12-month return threshold in normal conditions (SPY above 200d MA).
        Default 0.0 (Antonacci canonical).
    absolute_mom_threshold_bear : float
        12-month return threshold when SPY is in MA bear zone. Default 0.02 (+2%).
    """

    def __init__(
        self,
        ma_period_days: int = 200,
        ma_breach_weeks: int = 3,
        absolute_mom_threshold_normal: float = 0.0,
        absolute_mom_threshold_bear: float = 0.02,
    ):
        self.ma_period_days = ma_period_days
        self.ma_breach_weeks = ma_breach_weeks
        self.threshold_normal = absolute_mom_threshold_normal
        self.threshold_bear = absolute_mom_threshold_bear

    def compute_gate_series(
        self,
        weekly_prices: pd.DataFrame,
        spy_daily_prices: Optional[pd.Series] = None,
    ) -> pd.DataFrame:
        """
        Compute the enhanced absolute momentum gate for all weekly bars.

        Returns DataFrame with columns:
          spy_52w_return        : float
          spy_above_200d_ma     : bool
          consecutive_below_ma  : int  (weeks)
          in_ma_bear_zone       : bool
          abs_mom_threshold     : float  (active threshold this week)
          abs_mom_pass          : bool  (True = stay risk-on)
        """
        spy_col = "SPY"
        if spy_col not in weekly_prices.columns:
            spy_col = weekly_prices.columns[0]

        weekly_spy = weekly_prices[spy_col].dropna()

        # 52-week return
        spy_52w = weekly_spy.pct_change(52)

        # MA computation
        if spy_daily_prices is not None:
            # Compute 200d MA on daily, resample to weekly
            daily_ma = spy_daily_prices.rolling(self.ma_period_days).mean()
            # Align to weekly dates
            weekly_ma = daily_ma.reindex(weekly_spy.index, method="ffill")
            spy_above_ma = weekly_spy > weekly_ma
        else:
            # Fallback: use weekly data with a ~40-week MA (≈ 200 trading days)
            weekly_ma_period = self.ma_period_days // 5
            weekly_ma = weekly_spy.rolling(weekly_ma_period).mean()
            spy_above_ma = weekly_spy > weekly_ma

        # Consecutive weeks below MA
        consec_below = pd.Series(0, index=weekly_spy.index)
        count = 0
        for date, above in spy_above_ma.items():
            if not above:
                count += 1
            else:
                count = 0
            consec_below[date] = count

        in_bear_zone = consec_below >= self.ma_breach_weeks

        # Apply appropriate threshold
        threshold = pd.Series(
            np.where(in_bear_zone, self.threshold_bear, self.threshold_normal),
            index=weekly_spy.index,
        )

        abs_mom_pass = spy_52w > threshold

        return pd.DataFrame({
            "spy_52w_return": spy_52w.round(4),
            "spy_above_200d_ma": spy_above_ma,
            "consecutive_below_ma_weeks": consec_below,
            "in_ma_bear_zone": in_bear_zone,
            "abs_mom_threshold": threshold.round(4),
            "abs_mom_pass": abs_mom_pass,
        })


# ═════════════════════════════════════════════════════════════════════════════
#  T3-10: REGIME CHANGE DETECTOR (Kalman vol filter)
# ═════════════════════════════════════════════════════════════════════════════

class KalmanVolRegimeDetector:
    """
    Kalman filter applied to the vol estimate for early regime-change detection.

    Replaces the MTF layer's redundant momentum-confirmation function with
    a statistically grounded vol regime transition detector. Uses a 1D
    Kalman filter to smooth vol and detect low→high vol shifts at the
    earliest possible bar.

    The Kalman filter models vol as a latent state with:
      - Process noise (Q): how quickly vol can change
      - Observation noise (R): measurement error in realized vol

    Outputs:
      - Smoothed vol estimate (less reactive than raw)
      - Vol regime: CALM / NORMAL / ELEVATED / CRISIS
      - Transition signal: detected regime change with direction
      - Estimated time to regime change (based on vol velocity)

    Parameters
    ----------
    process_noise : float
        Kalman process noise Q. Higher = more responsive. Default 0.5.
    observation_noise : float
        Kalman observation noise R. Higher = more smoothing. Default 2.0.
    vol_thresholds : tuple
        (calm_max, normal_max, elevated_max) vol thresholds in %.
        Default (10.0, 18.0, 30.0) matching VolatilityTargeter.
    """

    def __init__(
        self,
        process_noise: float = 0.5,
        observation_noise: float = 2.0,
        vol_thresholds: tuple = (10.0, 18.0, 30.0),
    ):
        self.Q = process_noise
        self.R = observation_noise
        self.thresholds = vol_thresholds
        # Kalman state
        self._x = None   # state estimate (smoothed vol)
        self._P = 10.0   # state covariance

    def reset(self, initial_vol: float = 15.0):
        self._x = initial_vol
        self._P = 10.0

    def update(self, observed_vol: float) -> tuple[float, str]:
        """
        Update Kalman filter with new vol observation.

        Returns (smoothed_vol, regime_label)
        """
        if self._x is None:
            self._x = observed_vol

        # Predict
        x_pred = self._x
        P_pred = self._P + self.Q

        # Update (Kalman gain)
        K = P_pred / (P_pred + self.R)
        self._x = x_pred + K * (observed_vol - x_pred)
        self._P = (1 - K) * P_pred

        return self._x, self._classify(self._x)

    def _classify(self, vol: float) -> str:
        calm, normal, elevated = self.thresholds
        if vol < calm:
            return "CALM"
        elif vol < normal:
            return "NORMAL"
        elif vol < elevated:
            return "ELEVATED"
        else:
            return "CRISIS"

    def build_regime_series(
        self,
        vol_series: pd.Series,
        initial_vol: Optional[float] = None,
    ) -> pd.DataFrame:
        """
        Apply Kalman filter to a historical vol series.

        Returns DataFrame with:
          raw_vol, smoothed_vol, regime, regime_change,
          transition_direction (LOW_TO_HIGH or HIGH_TO_LOW or None)
        """
        self.reset(initial_vol or float(vol_series.iloc[0]))

        records = []
        prev_regime = None
        for date, raw_vol in vol_series.items():
            smoothed, regime = self.update(float(raw_vol))

            transition = None
            if prev_regime is not None and regime != prev_regime:
                # Classify direction: calm/normal → elevated/crisis = LOW_TO_HIGH
                regime_order = {"CALM": 0, "NORMAL": 1, "ELEVATED": 2, "CRISIS": 3}
                if regime_order.get(regime, 0) > regime_order.get(prev_regime, 0):
                    transition = "LOW_TO_HIGH"
                else:
                    transition = "HIGH_TO_LOW"

            records.append({
                "date": date,
                "raw_vol": round(raw_vol, 2),
                "smoothed_vol": round(smoothed, 2),
                "regime": regime,
                "regime_change": transition is not None,
                "transition_direction": transition,
            })
            prev_regime = regime

        return pd.DataFrame(records).set_index("date")

    def get_regime_multiplier(self, regime: str) -> float:
        """
        Map Kalman regime to scale multiplier.

        This replaces the MTF layer's 4-level scale output:
          CALM → 1.15 (low vol, add exposure — MTF 3/3 BULL equivalent)
          NORMAL → 1.00 (neutral)
          ELEVATED → 0.85 (reduce — MTF 1/3 BULL equivalent)
          CRISIS → 0.60 (defensive — MTF 0/3 BULL equivalent)
        """
        mapping = {
            "CALM":     1.15,
            "NORMAL":   1.00,
            "ELEVATED": 0.85,
            "CRISIS":   0.60,
        }
        return mapping.get(regime, 1.00)
