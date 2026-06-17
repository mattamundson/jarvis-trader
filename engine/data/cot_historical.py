"""
COT Historical Data — Vectorized CFTC Data for Backtesting (T1-4)
==================================================================
Fetches and caches CFTC Commitment of Traders data for historical
backtesting. Resolves the COT/backtest coherence failure where COT
is used in live signals but absent from the backtest.

Data source: CFTC public data portal (data.gov Socrata API)
  ES futures: Chicago Mercantile Exchange, E-mini S&P 500
  NQ futures: Chicago Mercantile Exchange, E-mini NASDAQ-100
  Available: 1995 → present (weekly, Tuesday report)

This module produces a weekly pd.Series of COT multipliers [0.85, 1.05]
aligned to the strategy's rebalancing dates, suitable for direct
multiplication into the backtest scale series.

Usage:
  from engine.data.cot_historical import COTHistoricalData
  cot = COTHistoricalData()
  cot_series = cot.get_multiplier_series(weekly_dates)  # pd.Series

Fallback behavior:
  If CFTC API is unavailable or rate-limited, falls back to neutral (1.0).
  Never blocks backtest execution.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Cache location
CACHE_DIR = Path(__file__).parent.parent / "backtest" / "data" / "cot_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# CFTC Socrata API endpoint
# Disaggregated Commitments of Traders — Financial Futures
CFTC_URL = (
    "https://publicreporting.cftc.gov/resource/jun7-fc8e.json"
    "?$where=market_and_exchange_names like '%25{symbol}%25'"
    "&$limit=2000"
    "&$order=report_date_as_yyyy_mm_dd DESC"
)

# Magnitude thresholds for multiplier assignment (calibrated on ES 2015-2026)
COT_EXTREME_LONG_THRESHOLD  =  200_000
COT_MODERATE_LONG_THRESHOLD =   50_000
COT_MODERATE_SHORT_THRESHOLD = -75_000
COT_EXTREME_SHORT_THRESHOLD  = -150_000


def net_position_to_multiplier(net: Optional[float]) -> float:
    """
    Convert large-spec net position to a scale multiplier.
    Mirrors the live signal's magnitude-aware COT logic.
    """
    if net is None or np.isnan(net):
        return 1.0
    if net > COT_EXTREME_LONG_THRESHOLD:
        return 1.05     # Strong spec long → bullish
    if net > COT_MODERATE_LONG_THRESHOLD:
        return 1.025    # Moderate spec long
    if net > COT_MODERATE_SHORT_THRESHOLD:
        return 1.0      # Neutral band
    if net > COT_EXTREME_SHORT_THRESHOLD:
        return 0.90     # Moderate spec short → headwind
    return 0.85         # Extreme spec short → strong headwind


class COTHistoricalData:
    """
    Fetches and vectorizes CFTC COT data for historical backtesting.

    Parameters
    ----------
    es_symbol_filter : str
        Keyword to filter ES futures from CFTC data. Default 'E-MINI S&P'.
    nq_symbol_filter : str
        Keyword to filter NQ futures. Default 'E-MINI NASDAQ'.
    blend_es_nq : float
        Weight on NQ vs ES in combined multiplier. Default 0.5.
    use_cache : bool
        Cache downloaded data to disk. Default True.
    cache_max_age_days : int
        Reload cache if older than this. Default 7.
    """

    def __init__(
        self,
        es_symbol_filter: str = "E-MINI S&P",
        nq_symbol_filter: str = "E-MINI NASDAQ",
        blend_es_nq: float = 0.5,
        use_cache: bool = True,
        cache_max_age_days: int = 7,
    ):
        self.es_filter = es_symbol_filter
        self.nq_filter = nq_symbol_filter
        self.blend = blend_es_nq
        self.use_cache = use_cache
        self.cache_max_age_days = cache_max_age_days
        self._es_data: Optional[pd.DataFrame] = None
        self._nq_data: Optional[pd.DataFrame] = None

    def _load_from_cftc(self, symbol_filter: str) -> Optional[pd.DataFrame]:
        """Fetch COT data from CFTC Socrata API."""
        try:
            import requests
            url = CFTC_URL.format(symbol=symbol_filter.replace(" ", "%20"))
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if not data:
                return None
            df = pd.DataFrame(data)
            df["report_date"] = pd.to_datetime(df["report_date_as_yyyy_mm_dd"])
            for col in ["noncomm_positions_long_all", "noncomm_positions_short_all"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            df["large_spec_net"] = (
                df.get("noncomm_positions_long_all", 0)
                - df.get("noncomm_positions_short_all", 0)
            )
            df = df.set_index("report_date").sort_index()
            return df[["large_spec_net"]]
        except Exception as e:
            logger.warning("CFTC API fetch failed for '%s': %s", symbol_filter, e)
            return None

    def _get_data(self, symbol_filter: str, cache_key: str) -> Optional[pd.DataFrame]:
        """Load from cache or fetch."""
        cache_path = CACHE_DIR / f"{cache_key}.parquet"
        if self.use_cache and cache_path.exists():
            age_days = (pd.Timestamp.now() - pd.Timestamp(cache_path.stat().st_mtime, unit="s")).days
            if age_days < self.cache_max_age_days:
                try:
                    return pd.read_parquet(cache_path)
                except Exception:
                    pass

        df = self._load_from_cftc(symbol_filter)
        if df is not None and self.use_cache:
            try:
                df.to_parquet(cache_path)
            except Exception:
                pass
        return df

    def get_multiplier_series(
        self,
        weekly_dates: pd.DatetimeIndex,
        fallback: float = 1.0,
    ) -> pd.Series:
        """
        Build a weekly COT multiplier series aligned to rebalancing dates.

        CFTC reports Tuesday; we align to the next Friday (rebalancing date).
        For each Friday, uses the most recent available Tuesday report.

        Returns pd.Series[float] indexed by weekly_dates.
        """
        # Lazy load
        if self._es_data is None:
            self._es_data = self._get_data(self.es_filter, "cot_es")
        if self._nq_data is None:
            self._nq_data = self._get_data(self.nq_filter, "cot_nq")

        if self._es_data is None and self._nq_data is None:
            logger.warning("COT data unavailable — using neutral multiplier %.1f", fallback)
            return pd.Series(fallback, index=weekly_dates)

        # Build multiplier at each rebalancing date
        multipliers = []
        for date in weekly_dates:
            es_mult = fallback
            nq_mult = fallback

            if self._es_data is not None:
                past = self._es_data.loc[:date]
                if not past.empty:
                    net = float(past["large_spec_net"].iloc[-1])
                    es_mult = net_position_to_multiplier(net)

            if self._nq_data is not None:
                past = self._nq_data.loc[:date]
                if not past.empty:
                    net = float(past["large_spec_net"].iloc[-1])
                    nq_mult = net_position_to_multiplier(net)

            blended = self.blend * nq_mult + (1 - self.blend) * es_mult
            multipliers.append(blended)

        return pd.Series(multipliers, index=weekly_dates, name="cot_multiplier")
