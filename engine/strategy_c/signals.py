"""
Strategy C+ Signal Layer — Enhanced Dual Momentum with Factor Tilts
====================================================================
Expands the baseline Dual Momentum universe and adds a factor-blend
ranking layer to improve asset selection within the risk-on universe.

Universe:
  Risk-On Core:    QQQ, SPY, EFA
  Risk-On Factors: USMV (low-vol), MTUM (momentum), XLK (tech), XLV (healthcare)
  Risk-Off:        IEF (intermediate bonds), SHY (short-term bonds)

Signal Logic (enhanced from Antonacci Dual Momentum):
  Step 1: Absolute momentum gate — if SPY 12-month return < 0, go risk-off
  Step 2: Factor-blend ranking of risk-on assets:
            rank_score = 0.70 * mom_52w + 0.20 * mom_13w + 0.10 * mom_4w
            (multi-horizon momentum — validated in Fama-French / AQR research)
  Step 3: Risk-off tiering:
            IEF 12-month return > 0 → IEF
            else → SHY
  Step 4: Top-1 selection (classic DM) OR top-2 equal-weight (enhanced DM)
            Default: top-2 equal-weight improves diversification without hurting Sharpe

Walk-forward validated momentum lookbacks (from jarvis-trader WF harness):
  Primary: 52 weeks (Antonacci canonical)
  Secondary: 13 weeks (quarterly)
  Tertiary: 4 weeks (monthly — momentum confirmation)
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

# Default universe — can be overridden in StrategyCConfig
RISK_ON_CORE = ["QQQ", "SPY", "EFA"]
RISK_ON_FACTORS = ["USMV", "MTUM", "XLK", "XLV"]
RISK_OFF = ["IEF", "SHY"]

# Factor-blend momentum weights (multi-horizon)
MOM_WEIGHTS = {52: 0.70, 13: 0.20, 4: 0.10}


class StrategyCSignals:
    """
    Enhanced Dual Momentum signal generator with factor tilts.

    Parameters
    ----------
    risk_on : list
        Risk-on asset pool (default: core + factor ETFs)
    risk_off : list
        Risk-off fallback assets (default: IEF, SHY)
    mom_lookback_primary : int
        Primary momentum lookback in weeks (default 52)
    top_n : int
        Number of top-ranked risk-on assets to hold (1 or 2, default 2)
    use_factor_tilt : bool
        Whether to use multi-horizon factor ranking (default True)
    absolute_mom_threshold : float
        Minimum 12-month SPY return to stay risk-on (default 0.0)
    """

    def __init__(
        self,
        risk_on: Optional[list] = None,
        risk_off: Optional[list] = None,
        mom_lookback_primary: int = 52,
        top_n: int = 2,
        use_factor_tilt: bool = True,
        absolute_mom_threshold: float = 0.0,
    ):
        self.risk_on = risk_on or (RISK_ON_CORE + RISK_ON_FACTORS)
        self.risk_off = risk_off or RISK_OFF
        self.mom_lookback_primary = mom_lookback_primary
        self.top_n = top_n
        self.use_factor_tilt = use_factor_tilt
        self.absolute_mom_threshold = absolute_mom_threshold

    def available_assets(self, weekly_prices: pd.DataFrame) -> tuple[list, list]:
        """Return available risk-on and risk-off assets given price data."""
        avail_on = [a for a in self.risk_on if a in weekly_prices.columns]
        avail_off = [a for a in self.risk_off if a in weekly_prices.columns]
        return avail_on, avail_off

    def compute_momentum_score(
        self,
        weekly_prices: pd.DataFrame,
        assets: list,
        as_of_idx: int,
    ) -> pd.Series:
        """
        Compute multi-horizon momentum ranking score for each asset.

        For each asset at a given bar index:
          score = Σ weight_k * (price[t] / price[t - k_weeks] - 1)

        Returns pd.Series of scores indexed by asset ticker.
        """
        if as_of_idx < max(MOM_WEIGHTS.keys()):
            return pd.Series(dict.fromkeys(assets, np.nan))

        scores = {}
        for asset in assets:
            if asset not in weekly_prices.columns:
                continue
            price_series = weekly_prices[asset].iloc[:as_of_idx + 1]
            score = 0.0
            valid = True
            for lookback, weight in MOM_WEIGHTS.items():
                if len(price_series) < lookback + 1:
                    valid = False
                    break
                past_price = price_series.iloc[-lookback - 1]
                if past_price <= 0:
                    valid = False
                    break
                ret = (price_series.iloc[-1] / past_price) - 1.0
                score += weight * ret
            if valid:
                scores[asset] = score

        return pd.Series(scores)

    def generate_signals(
        self,
        weekly_prices: pd.DataFrame,
        t1_lag: bool = True,
    ) -> pd.DataFrame:
        """
        Generate weekly asset allocation signals for the full backtest period.

        Parameters
        ----------
        weekly_prices : pd.DataFrame
            Weekly Friday close prices for all universe assets
        t1_lag : bool
            Apply T+1 execution lag (signal generated Friday, executed next open)
            This is critical for realistic backtest — avoids look-ahead bias.

        Returns
        -------
        DataFrame with columns: signal (asset name), weight (0 or 1/n for top-n),
        raw_score, absolute_mom_pass, risk_regime
        """
        avail_on, avail_off = self.available_assets(weekly_prices)
        if not avail_off:
            raise ValueError("No risk-off assets available in weekly_prices")

        spy_col = "SPY" if "SPY" in weekly_prices.columns else (avail_on[0] if avail_on else None)

        records = []
        dates = weekly_prices.index

        for i, date in enumerate(dates):
            # Need enough history for primary lookback
            if i < self.mom_lookback_primary + 1:
                records.append({
                    "date": date,
                    "holdings": {avail_off[-1]: 1.0},
                    "risk_regime": "WARMUP",
                    "absolute_mom_pass": False,
                })
                continue

            # ── Step 1: Absolute Momentum Gate ────────────────────────────────
            absolute_mom_pass = False
            if spy_col:
                spy_52w = weekly_prices[spy_col].iloc[i - self.mom_lookback_primary]
                spy_now = weekly_prices[spy_col].iloc[i]
                spy_ret = (spy_now / spy_52w) - 1.0 if spy_52w > 0 else -1.0
                absolute_mom_pass = spy_ret > self.absolute_mom_threshold

            if not absolute_mom_pass:
                # Risk-off: IEF vs SHY momentum check
                holdings = self._risk_off_selection(weekly_prices, avail_off, i)
                records.append({
                    "date": date,
                    "holdings": holdings,
                    "risk_regime": "RISK_OFF",
                    "absolute_mom_pass": False,
                })
                continue

            # ── Step 2: Rank risk-on assets ────────────────────────────────────
            if self.use_factor_tilt:
                scores = self.compute_momentum_score(weekly_prices, avail_on, i)
            else:
                # Fallback: single lookback
                scores = {}
                for asset in avail_on:
                    if asset in weekly_prices.columns:
                        past = weekly_prices[asset].iloc[i - self.mom_lookback_primary]
                        now = weekly_prices[asset].iloc[i]
                        scores[asset] = (now / past) - 1.0 if past > 0 else np.nan
                scores = pd.Series(scores)

            scores = scores.dropna()
            if scores.empty:
                records.append({
                    "date": date,
                    "holdings": {avail_off[-1]: 1.0},
                    "risk_regime": "NO_SIGNAL",
                    "absolute_mom_pass": True,
                })
                continue

            # ── Step 3: Select top-N assets ────────────────────────────────────
            top_assets = scores.nlargest(min(self.top_n, len(scores))).index.tolist()
            weight = 1.0 / len(top_assets)
            holdings = dict.fromkeys(top_assets, weight)

            records.append({
                "date": date,
                "holdings": holdings,
                "risk_regime": "RISK_ON",
                "absolute_mom_pass": True,
                "top_score": float(scores[top_assets[0]]),
                "top_asset": top_assets[0],
            })

        df = pd.DataFrame(records).set_index("date")

        # T+1 lag: signal generated on Friday, applied next week
        if t1_lag:
            df["holdings"] = df["holdings"].shift(1)
            df["holdings"] = df["holdings"].ffill()

        return df

    def _risk_off_selection(
        self,
        weekly_prices: pd.DataFrame,
        avail_off: list,
        i: int,
    ) -> dict:
        """
        Select risk-off asset: IEF if 12-month return > 0, else SHY.
        """
        for asset in avail_off:
            lookback = min(self.mom_lookback_primary, i)
            if asset in weekly_prices.columns and lookback > 0:
                past = weekly_prices[asset].iloc[i - lookback]
                now = weekly_prices[asset].iloc[i]
                ret = (now / past) - 1.0 if past > 0 else -1.0
                if ret > 0:
                    return {asset: 1.0}
        # Fallback: SHY (cash-like)
        fallback = avail_off[-1] if avail_off else "SHY"
        return {fallback: 1.0}

    def get_current_signal(
        self,
        weekly_prices: pd.DataFrame,
    ) -> dict:
        """
        Generate the CURRENT WEEK's signal for live use.

        Returns dict with holdings, risk_regime, and scores.
        """
        df = self.generate_signals(weekly_prices, t1_lag=True)
        last = df.iloc[-1]
        return {
            "date": str(df.index[-1].date()),
            "holdings": last["holdings"] if isinstance(last["holdings"], dict) else {},
            "risk_regime": last.get("risk_regime", "UNKNOWN"),
            "absolute_mom_pass": bool(last.get("absolute_mom_pass", False)),
        }
