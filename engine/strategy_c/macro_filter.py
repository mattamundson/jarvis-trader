"""
Macro Regime Filter — FRED + CoT Integration
=============================================
Uses macroeconomic data (yield curve, Fed funds rate) and CFTC Commitment
of Traders data to provide a secondary regime gate for Strategy C.

The filter outputs a multiplier [0.5, 1.0] that is applied AFTER:
  1. Dual Momentum asset selection
  2. Volatility targeting scale
  3. VIX composite multiplier

Design principles (from jarvis-trader engine/data/fred_data.py and cot_fetcher.py):
  - Never BLOCKS a trade outright (that's VIX composite's job)
  - Acts as a mild headwind/tailwind on position sizing
  - Graceful fallback: if FRED/CFTC unavailable → returns 1.0 (neutral)

Macro regime signals:
  1. Yield curve (10Y - 2Y):
       > +0.5% → strong tailwind (+0.10 multiplier boost)
       0 to +0.5% → neutral
       Inverted (<0) → mild headwind (-0.10)
       Deeply inverted (<-0.75%) → strong headwind (-0.20)

  2. CoT ES/NQ commercial positioning (weekly CFTC data):
       BULLISH (commercials adding longs) → +0.05
       BEARISH (commercials adding shorts) → -0.05
       NEUTRAL → 0

  3. Fed cycle phase:
       Cutting cycle (rates declining) → +0.05
       Hiking cycle (rates rising) → -0.05
       Paused → 0
"""
from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


class MacroRegimeFilter:
    """
    Macro overlay filter for Strategy C.

    Parameters
    ----------
    use_cot : bool
        Whether to include CoT positioning data (default True, falls back gracefully)
    use_fred : bool
        Whether to include FRED yield curve data (default True, falls back gracefully)
    """

    def __init__(self, use_cot: bool = True, use_fred: bool = True):
        self.use_cot = use_cot
        self.use_fred = use_fred
        self._cot_fetcher = None
        self._fred_service = None

    def _init_services(self):
        """Lazy init to avoid import errors in standalone backtest mode."""
        if self.use_cot and self._cot_fetcher is None:
            try:
                # Prefer v2 (corrected CFTC endpoint) — fall back to v1
                try:
                    try:
                        from data.cot_fetcher_v2 import CoTFetcherV2
                    except ImportError:
                        from engine.data.cot_fetcher_v2 import CoTFetcherV2
                    self._cot_fetcher = CoTFetcherV2()
                    logger.info("CoTFetcherV2 initialised (Socrata endpoint)")
                except ImportError:
                    try:
                        from data.cot_fetcher import CoTFetcher
                    except ImportError:
                        from engine.data.cot_fetcher import CoTFetcher
                    self._cot_fetcher = CoTFetcher()
            except Exception as e:
                logger.debug("CoTFetcher unavailable: %s", e)

        if self.use_fred and self._fred_service is None:
            try:
                try:
                    from data.fred_data import get_fred_service
                except ImportError:
                    from engine.data.fred_data import get_fred_service
                self._fred_service = get_fred_service()
            except Exception as e:
                logger.debug("FREDDataService unavailable: %s", e)

    def get_live_multiplier(self) -> tuple[float, dict]:
        """
        Fetch live macro data and compute the position multiplier.

        Returns
        -------
        (multiplier: float, detail: dict)
            multiplier: 0.50–1.10 position multiplier
            detail: breakdown of each component
        """
        self._init_services()
        detail = {
            "yield_curve_adj": 0.0,
            "cot_adj": 0.0,
            "fed_cycle_adj": 0.0,
            "yield_curve": None,
            "cot_es": None,
            "cot_nq": None,
            "fed_funds": None,
            "source": "live",
        }

        # ── Component 1: Yield Curve ─────────────────────────────────────────
        if self._fred_service:
            try:
                ten_year = self._fred_service.get_latest("GS10")
                two_year = self._fred_service.get_latest("GS2")
                fed_funds = self._fred_service.get_latest("FEDFUNDS")

                if ten_year and two_year:
                    spread = ten_year - two_year
                    detail["yield_curve"] = round(spread, 3)
                    if spread > 0.50:
                        detail["yield_curve_adj"] = 0.10
                    elif spread > 0:
                        detail["yield_curve_adj"] = 0.0
                    elif spread > -0.75:
                        detail["yield_curve_adj"] = -0.10
                    else:
                        detail["yield_curve_adj"] = -0.20

                if fed_funds:
                    detail["fed_funds"] = round(fed_funds, 3)
                    # Fed cycle: compare to 3-month average to detect direction
                    ff_series = self._fred_service.get_series("FEDFUNDS", periods=6)
                    if ff_series is not None and len(ff_series) >= 3:
                        recent = float(ff_series.dropna().iloc[-1])
                        prev = float(ff_series.dropna().iloc[-3])
                        if recent < prev - 0.10:
                            detail["fed_cycle_adj"] = 0.05  # Cutting → bullish
                        elif recent > prev + 0.10:
                            detail["fed_cycle_adj"] = -0.05  # Hiking → headwind
            except Exception as e:
                logger.debug("FRED macro filter error: %s", e)

        # ── Component 1b: Live yfinance macro (supplement/replace FRED when no API key) ──
        if not detail["yield_curve"]:
            try:
                try:
                    from data.fred_data import get_live_macro_yfinance
                except ImportError:
                    from engine.data.fred_data import get_live_macro_yfinance
                snap = get_live_macro_yfinance()
                yc = snap.get("yield_curve_2_10", {}).get("value", None)
                if yc is not None:
                    detail["yield_curve"] = round(float(yc), 3)
                    if yc > 0.50:
                        detail["yield_curve_adj"] = 0.10
                    elif yc > 0:
                        detail["yield_curve_adj"] = 0.0
                    elif yc > -0.75:
                        detail["yield_curve_adj"] = -0.10
                    else:
                        detail["yield_curve_adj"] = -0.20
                vix_live = snap.get("vix", {}).get("value", None)
                if vix_live:
                    detail["vix_live"] = round(float(vix_live), 2)
                if not detail["fed_funds"]:
                    ff = snap.get("fed_funds_rate", {}).get("value", None)
                    if ff:
                        detail["fed_funds"] = round(float(ff), 3)
                logger.info("Live macro (yfinance): yield_curve=%.3f, VIX=%.1f",
                            detail["yield_curve"] or 0, vix_live or 0)
            except Exception as e:
                logger.debug("yfinance macro fallback error: %s", e)

        # ── Component 2: CoT Positioning ─────────────────────────────────────
        if self._cot_fetcher:
            try:
                # v2 fetcher uses get_positioning() + cot_signal
                if hasattr(self._cot_fetcher, 'get_cot_multiplier'):
                    # CoTFetcherV2 interface
                    es_result = self._cot_fetcher.get_positioning("MES")
                    nq_result = self._cot_fetcher.get_positioning("MNQ")
                    es_signal = es_result.get("cot_signal", "NEUTRAL") if es_result else "NEUTRAL"
                    nq_signal = nq_result.get("cot_signal", "NEUTRAL") if nq_result else "NEUTRAL"
                    signal_to_adj = {"BULLISH": 0.05, "NEUTRAL": 0.0, "BEARISH": -0.05}
                    es_adj = signal_to_adj.get(es_signal, 0.0)
                    nq_adj = signal_to_adj.get(nq_signal, 0.0)
                    combined_cot = (es_adj + nq_adj) / 2.0
                    detail["cot_adj"] = round(combined_cot, 4)
                    detail["cot_es"] = es_signal
                    detail["cot_nq"] = nq_signal
                    detail["cot_es_net"] = es_result.get("large_spec_net") if es_result else None
                    detail["cot_nq_net"] = nq_result.get("large_spec_net") if nq_result else None
                    logger.info("CoT: ES=%s(%+d) NQ=%s(%+d) adj=%.3f",
                                es_signal, detail.get("cot_es_net") or 0,
                                nq_signal, detail.get("cot_nq_net") or 0, combined_cot)
                else:
                    # Legacy CoTFetcher v1 interface
                    es_cot = self._cot_fetcher.get_bias_adjustment("ES")
                    nq_cot = self._cot_fetcher.get_bias_adjustment("NQ")
                    combined_cot = (es_cot + nq_cot) / 2.0
                    detail["cot_adj"] = round(combined_cot * 0.5, 4)
                    detail["cot_es"] = es_cot
                    detail["cot_nq"] = nq_cot
            except Exception as e:
                logger.debug("CoT filter error: %s", e)

        # ── Aggregate ────────────────────────────────────────────────────────
        total_adj = (
            detail["yield_curve_adj"]
            + detail["cot_adj"]
            + detail["fed_cycle_adj"]
        )
        # Base is 1.0; clamp to [0.50, 1.10]
        multiplier = max(0.50, min(1.10, 1.0 + total_adj))
        detail["multiplier"] = round(multiplier, 4)
        detail["total_adj"] = round(total_adj, 4)

        return multiplier, detail

    def get_historical_multiplier_series(
        self,
        weekly_index: pd.DatetimeIndex,
        yield_curve_series: Optional[pd.Series] = None,
    ) -> pd.Series:
        """
        Build a historical macro multiplier series for backtesting.

        For backtesting we only use yield curve (CoT is weekly point-in-time,
        not easily vectorized historically without an expensive data pull).

        Parameters
        ----------
        weekly_index : pd.DatetimeIndex
            Weekly rebalancing dates
        yield_curve_series : pd.Series, optional
            Pre-loaded 10Y-2Y spread series (from FRED or yfinance)

        Returns
        -------
        pd.Series of float multipliers indexed by weekly_index
        """
        if yield_curve_series is None:
            # Default: neutral throughout
            return pd.Series(1.0, index=weekly_index)

        spread_aligned = yield_curve_series.reindex(weekly_index, method="ffill")

        def spread_to_adj(spread: float) -> float:
            if pd.isna(spread):
                return 0.0
            if spread > 0.50:
                return 0.10
            elif spread > 0:
                return 0.0
            elif spread > -0.75:
                return -0.10
            else:
                return -0.20

        adjustments = spread_aligned.apply(spread_to_adj)
        multipliers = (1.0 + adjustments).clip(0.50, 1.10)
        return multipliers
