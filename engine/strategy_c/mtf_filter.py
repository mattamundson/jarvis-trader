"""
Multi-Timeframe (MTF) Momentum Confirmation Layer for Strategy C+

Confirms the weekly momentum signal using:
  1. Weekly momentum  — 12-week price ROC on XLK, QQQ, SPY
  2. Monthly momentum — 3-month price ROC on XLK, QQQ, SPY
  3. Daily confirmation — 20-day vs 50-day EMA crossover
  4. Breadth filter — % of S&P 500 above 200-day MA (use SPY as proxy)

Scale output:
  - 3/3 timeframes agree BULL → scale multiplier 1.15 (boost)
  - 2/3 agree → 1.00 (neutral)
  - 1/3 agree → 0.85 (reduce)
  - 0/3 agree → 0.60 (defensive)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Timeframe parameters
WEEKLY_ROC_WEEKS = 12          # 12-week price rate-of-change
MONTHLY_ROC_MONTHS = 3         # 3-month price rate-of-change (~63 trading days)
DAILY_EMA_FAST = 20            # Fast EMA for daily confirmation
DAILY_EMA_SLOW = 50            # Slow EMA for daily confirmation
BREADTH_MA = 200               # MA period for breadth filter (SPY proxy)
LOOKBACK_DAYS = 300            # Days of history to fetch


class MTFFilter:
    """
    Multi-Timeframe Momentum Confirmation Layer.

    Fetches recent price data via yfinance and computes three momentum
    timeframe votes plus a breadth filter. Aggregates into a single
    scale multiplier for use in the Strategy C+ signal stack.

    Usage:
        mtf = MTFFilter()
        result = mtf.get_mtf_signal(["XLK", "QQQ", "SPY"])
    """

    def __init__(self) -> None:
        self._cache: Optional[pd.DataFrame] = None
        self._cache_ts: Optional[datetime] = None
        self._cache_ttl_seconds = 300  # 5-minute cache

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    def get_mtf_signal(self, symbols: list = None) -> dict:
        """
        Compute MTF momentum confirmation signal.

        Args:
            symbols: List of tickers to use (default: ["XLK", "QQQ", "SPY"]).

        Returns:
            dict with mtf_scale, weekly_momentum, monthly_momentum,
            daily_confirmation, breadth, votes_bull, votes_bear,
            confidence, and details sub-dict.
        """
        if symbols is None:
            symbols = ["XLK", "QQQ", "SPY"]

        neutral_result = self._neutral_result()

        try:
            prices = self._fetch_prices(symbols)
            if prices is None or prices.empty or len(prices) < DAILY_EMA_SLOW + 5:
                logger.warning("[MTFFilter] Insufficient price data; returning neutral.")
                return neutral_result

            # ── Layer 1: Weekly momentum (12-week ROC) ──────────────────────
            weekly_signal, weekly_details = self._compute_weekly_momentum(prices, symbols)

            # ── Layer 2: Monthly momentum (3-month ROC, ~63 trading days) ───
            monthly_signal, monthly_details = self._compute_monthly_momentum(prices, symbols)

            # ── Layer 3: Daily EMA confirmation (20 vs 50) ──────────────────
            daily_signal, daily_details = self._compute_daily_confirmation(prices)

            # ── Layer 4: Breadth (SPY 200-day MA proxy) ─────────────────────
            breadth_label = self._compute_breadth(prices)

            # ── Vote aggregation ─────────────────────────────────────────────
            votes_bull = sum([
                weekly_signal == "BULL",
                monthly_signal == "BULL",
                daily_signal == "BULL",
            ])
            votes_bear = sum([
                weekly_signal == "BEAR",
                monthly_signal == "BEAR",
                daily_signal == "BEAR",
            ])

            # Scale mapping
            mtf_scale = self._votes_to_scale(votes_bull)

            # Confidence
            confidence = self._compute_confidence(votes_bull, votes_bear, breadth_label)

            return {
                "mtf_scale": mtf_scale,
                "weekly_momentum": weekly_signal,
                "monthly_momentum": monthly_signal,
                "daily_confirmation": daily_signal,
                "breadth": breadth_label,
                "votes_bull": votes_bull,
                "votes_bear": votes_bear,
                "confidence": confidence,
                "details": {
                    **weekly_details,
                    **monthly_details,
                    **daily_details,
                },
            }

        except Exception as exc:
            logger.error("[MTFFilter] Error computing MTF signal: %s", exc, exc_info=True)
            return neutral_result

    # ─────────────────────────────────────────────────────────────────────────
    # Data Fetching
    # ─────────────────────────────────────────────────────────────────────────

    def _fetch_prices(self, symbols: list) -> Optional[pd.DataFrame]:
        """Fetch daily closing prices via yfinance with a short-lived cache."""
        now = datetime.utcnow()
        if (
            self._cache is not None
            and self._cache_ts is not None
            and (now - self._cache_ts).total_seconds() < self._cache_ttl_seconds
        ):
            # Return cached subset
            available = [s for s in symbols if s in self._cache.columns]
            if len(available) == len(symbols):
                return self._cache[symbols]

        try:
            import yfinance as yf

            end_date = datetime.today().strftime("%Y-%m-%d")
            start_date = (datetime.today() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")

            raw = yf.download(
                symbols,
                start=start_date,
                end=end_date,
                auto_adjust=True,
                progress=False,
            )

            if raw is None or raw.empty:
                return None

            if isinstance(raw.columns, pd.MultiIndex):
                prices = raw["Close"]
            else:
                # Single ticker returns flat DataFrame
                prices = raw[["Close"]] if "Close" in raw.columns else raw

            prices.index = pd.to_datetime(prices.index)
            prices = prices.ffill().dropna(how="all")

            # If single symbol, yfinance may return a flat DataFrame
            if len(symbols) == 1 and isinstance(prices, pd.Series):
                prices = prices.to_frame(name=symbols[0])

            # Ensure all requested symbols are present
            for sym in symbols:
                if sym not in prices.columns:
                    logger.warning("[MTFFilter] Symbol %s not found in downloaded data.", sym)

            self._cache = prices
            self._cache_ts = now
            return prices

        except Exception as exc:
            logger.error("[MTFFilter] yfinance fetch failed: %s", exc)
            return None

    # ─────────────────────────────────────────────────────────────────────────
    # Signal Computations
    # ─────────────────────────────────────────────────────────────────────────

    def _compute_weekly_momentum(
        self, prices: pd.DataFrame, symbols: list
    ) -> tuple[str, dict]:
        """
        12-week price ROC on each symbol.
        BULL if median ROC > 0, BEAR if < 0, else NEUTRAL.
        """
        # Resample to weekly (Friday close)
        weekly = prices.resample("W-FRI").last()

        roc_values = {}
        period = WEEKLY_ROC_WEEKS

        for sym in symbols:
            if sym not in weekly.columns:
                continue
            series = weekly[sym].dropna()
            if len(series) < period + 1:
                continue
            roc = float(series.iloc[-1] / series.iloc[-(period + 1)] - 1.0)
            roc_values[sym] = round(roc, 6)

        details = {}
        for sym, roc in roc_values.items():
            key = f"{sym}_weekly_roc"
            details[key] = roc

        if not roc_values:
            return "NEUTRAL", details

        median_roc = float(np.median(list(roc_values.values())))

        # Small deadband to avoid noise near zero
        if median_roc > 0.003:
            signal = "BULL"
        elif median_roc < -0.003:
            signal = "BEAR"
        else:
            signal = "NEUTRAL"

        details["weekly_median_roc"] = round(median_roc, 6)
        return signal, details

    def _compute_monthly_momentum(
        self, prices: pd.DataFrame, symbols: list
    ) -> tuple[str, dict]:
        """
        3-month price ROC (~63 trading days) on each symbol.
        BULL if median ROC > 0, BEAR if < 0, else NEUTRAL.
        """
        period_days = MONTHLY_ROC_MONTHS * 21  # ~63 trading days

        roc_values = {}
        for sym in symbols:
            if sym not in prices.columns:
                continue
            series = prices[sym].dropna()
            if len(series) < period_days + 1:
                continue
            roc = float(series.iloc[-1] / series.iloc[-(period_days + 1)] - 1.0)
            roc_values[sym] = round(roc, 6)

        details = {}
        for sym, roc in roc_values.items():
            key = f"{sym}_monthly_roc"
            details[key] = roc

        if not roc_values:
            return "NEUTRAL", details

        median_roc = float(np.median(list(roc_values.values())))

        if median_roc > 0.005:
            signal = "BULL"
        elif median_roc < -0.005:
            signal = "BEAR"
        else:
            signal = "NEUTRAL"

        details["monthly_median_roc"] = round(median_roc, 6)
        return signal, details

    def _compute_daily_confirmation(self, prices: pd.DataFrame) -> tuple[str, dict]:
        """
        20-day EMA vs 50-day EMA crossover on SPY (or first available symbol).
        BULL if EMA20 > EMA50, BEAR otherwise.
        """
        # Prefer SPY; fall back to first available column
        spy_col = "SPY" if "SPY" in prices.columns else prices.columns[0]
        series = prices[spy_col].dropna()

        details: dict = {"daily_ema_symbol": spy_col}

        if len(series) < DAILY_EMA_SLOW + 5:
            details["ema20_above_ema50"] = None
            return "NEUTRAL", details

        ema20 = float(series.ewm(span=DAILY_EMA_FAST, adjust=False).mean().iloc[-1])
        ema50 = float(series.ewm(span=DAILY_EMA_SLOW, adjust=False).mean().iloc[-1])

        above = ema20 > ema50
        details["ema20_above_ema50"] = above
        details["ema20"] = round(ema20, 4)
        details["ema50"] = round(ema50, 4)
        details["ema_gap_pct"] = round((ema20 / ema50 - 1.0) * 100, 4)

        return "BULL" if above else "BEAR", details

    def _compute_breadth(self, prices: pd.DataFrame) -> str:
        """
        Breadth filter: SPY price vs its 200-day MA as a proxy for broad
        market participation.
        EXPANDING  — SPY > SMA200 and trending up
        CONTRACTING — SPY < SMA200 or trending down
        NEUTRAL    — SPY within ±0.5% of SMA200
        """
        spy_col = "SPY" if "SPY" in prices.columns else prices.columns[0]
        series = prices[spy_col].dropna()

        if len(series) < BREADTH_MA + 5:
            return "NEUTRAL"

        sma200 = float(series.rolling(BREADTH_MA).mean().iloc[-1])
        current = float(series.iloc[-1])
        gap_pct = (current / sma200 - 1.0) * 100

        if gap_pct > 0.5:
            return "EXPANDING"
        elif gap_pct < -0.5:
            return "CONTRACTING"
        else:
            return "NEUTRAL"

    # ─────────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _votes_to_scale(votes_bull: int) -> float:
        """Map bull vote count to scale multiplier."""
        mapping = {3: 1.15, 2: 1.00, 1: 0.85, 0: 0.60}
        return mapping.get(votes_bull, 1.00)

    @staticmethod
    def _compute_confidence(
        votes_bull: int, votes_bear: int, breadth: str
    ) -> str:
        """
        Derive confidence label from vote unanimity and breadth alignment.
          HIGH   — 3 votes in one direction AND breadth confirms
          MEDIUM — 2 votes in one direction OR breadth neutral
          LOW    — split votes or breadth contradicts
        """
        unanimous = votes_bull == 3 or votes_bear == 3
        majority = votes_bull >= 2 or votes_bear >= 2

        breadth_confirms_bull = breadth == "EXPANDING" and votes_bull >= 2
        breadth_confirms_bear = breadth == "CONTRACTING" and votes_bear >= 2

        if unanimous and (breadth_confirms_bull or breadth_confirms_bear or breadth == "NEUTRAL"):
            return "HIGH"
        elif unanimous or (majority and (breadth_confirms_bull or breadth_confirms_bear)):
            return "HIGH" if unanimous else "MEDIUM"
        elif majority:
            return "MEDIUM"
        else:
            return "LOW"

    @staticmethod
    def _neutral_result() -> dict:
        """Return a safe neutral result when data is unavailable."""
        return {
            "mtf_scale": 1.0,
            "weekly_momentum": "NEUTRAL",
            "monthly_momentum": "NEUTRAL",
            "daily_confirmation": "NEUTRAL",
            "breadth": "NEUTRAL",
            "votes_bull": 0,
            "votes_bear": 0,
            "confidence": "LOW",
            "details": {
                "error": "Data unavailable — defaulting to neutral",
                "ema20_above_ema50": None,
            },
        }
