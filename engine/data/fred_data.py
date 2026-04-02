"""
FRED Economic Data
==================
Federal Reserve Economic Data — free, no API key needed via fredapi.
Provides macro context for trading decisions.

When FRED is unreachable (rate-limited, no API key, network issues), all
public methods fall back to FRED_SNAPSHOT_DEFAULTS so callers always receive
numeric values rather than None. Defaults reflect Q1 2026 levels and should
be updated quarterly.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Hardcoded fallback values used when FRED cannot be reached.
# Series: DGS10 (ten_year_yield) is the most commonly requested — keep accurate.
FRED_SNAPSHOT_DEFAULTS: dict[str, float] = {
    "FEDFUNDS": 4.33,  # Federal Funds Rate
    "GS10": 4.30,  # 10-Year Treasury Yield (GS10, monthly)
    "GS2": 4.05,  # 2-Year Treasury Yield
    "VIXCLS": 20.0,  # CBOE VIX (daily close)
    "UNRATE": 4.1,  # Unemployment Rate
}

# Key FRED series for trading context
FRED_SERIES = {
    "fed_funds_rate": "FEDFUNDS",  # Federal Funds Rate
    "ten_year_yield": "GS10",  # 10-Year Treasury Yield
    "two_year_yield": "GS2",  # 2-Year Treasury Yield
    "vix": "VIXCLS",  # CBOE Volatility Index
    "unemployment": "UNRATE",  # Unemployment Rate
    "cpi_yoy": "CPIAUCSL",  # Consumer Price Index (YoY inflation)
    "pce_inflation": "PCEPI",  # PCE Price Index (Fed's preferred)
    "gdp_growth": "A191RL1Q225SBEA",  # Real GDP Growth Rate (quarterly)
    "yield_curve_2_10": None,  # Computed: 10Y - 2Y spread
    "ism_manufacturing": "MANEMP",  # Manufacturing Employment proxy
    "retail_sales": "RSXFS",  # Retail Sales ex-Food Services
}


class FREDDataService:
    """
    Fetches and caches FRED economic data.
    Data is public — no API key required (uses fredapi which scrapes FRED).
    """

    def __init__(self, api_key: Optional[str] = None):
        self._cache: dict = {}
        self._cache_time: dict = {}
        self._cache_ttl = 3600  # 1 hour cache (FRED data is monthly/weekly)
        self._api_key = api_key

    def _get_client(self):
        try:
            from fredapi import Fred

            if self._api_key:
                return Fred(api_key=self._api_key)
            # fredapi works without a key for most series (rate-limited)
            return Fred()
        except ImportError:
            logger.warning("fredapi not installed")
            return None

    def get_series(self, series_id: str, periods: int = 12) -> Optional[pd.Series]:
        """Get a FRED series, cached for 1 hour."""
        cache_key = f"{series_id}_{periods}"
        now = datetime.now()

        if cache_key in self._cache:
            age = (now - self._cache_time[cache_key]).total_seconds()
            if age < self._cache_ttl:
                return self._cache[cache_key]

        fred = self._get_client()
        if not fred:
            return None

        try:
            end_date = now
            start_date = now - timedelta(days=periods * 35)  # ~periods months back
            data = fred.get_series(series_id, start=start_date, end=end_date)
            if data is not None and len(data) > 0:
                self._cache[cache_key] = data
                self._cache_time[cache_key] = now
            return data
        except Exception as e:
            logger.warning(f"FRED series {series_id} failed: {e}")
            return None

    def get_latest(self, series_id: str) -> Optional[float]:
        """
        Get the most recent value for a series.
        Returns the live FRED value when available; falls back to
        FRED_SNAPSHOT_DEFAULTS and logs a WARNING when the series cannot
        be fetched (API key missing, rate-limited, network error, etc.).
        """
        data = self.get_series(series_id, periods=3)
        if data is not None and len(data) > 0:
            return float(data.dropna().iloc[-1])

        default_val = FRED_SNAPSHOT_DEFAULTS.get(series_id)
        if default_val is not None:
            logger.warning(
                f"FRED series {series_id} unavailable — using hardcoded default "
                f"{default_val} (update FRED_SNAPSHOT_DEFAULTS quarterly)"
            )
            return default_val

        logger.warning(
            f"FRED series {series_id} unavailable and no default defined — returning None"
        )
        return None

    def get_macro_snapshot(self) -> dict:
        """
        Returns a macro snapshot for trading context.
        All values are the most recent available from FRED.
        """
        snapshot = {
            "timestamp": datetime.now().isoformat(),
            "source": "FRED (Federal Reserve Economic Data)",
        }

        # Fetch each series
        fed_funds = self.get_latest("FEDFUNDS")
        ten_year = self.get_latest("GS10")
        two_year = self.get_latest("GS2")
        vix = self.get_latest("VIXCLS")
        unemployment = self.get_latest("UNRATE")

        snapshot["fed_funds_rate"] = {
            "value": fed_funds,
            "unit": "%",
            "description": "Federal Funds Rate",
        }
        snapshot["ten_year_yield"] = {
            "value": ten_year,
            "unit": "%",
            "description": "10-Year Treasury Yield",
        }
        snapshot["two_year_yield"] = {
            "value": two_year,
            "unit": "%",
            "description": "2-Year Treasury Yield",
        }
        snapshot["vix"] = {"value": vix, "unit": "index", "description": "CBOE Volatility Index"}
        snapshot["unemployment"] = {
            "value": unemployment,
            "unit": "%",
            "description": "Unemployment Rate",
        }

        # Derived
        if ten_year and two_year:
            spread = round(ten_year - two_year, 3)
            snapshot["yield_curve_2_10"] = {
                "value": spread,
                "unit": "%",
                "description": "Yield Curve (10Y - 2Y)",
                "inverted": spread < 0,
            }

        # Regime assessment
        regime = self._assess_regime(fed_funds, ten_year, vix, unemployment)
        snapshot["macro_regime"] = regime

        return snapshot

    def _assess_regime(self, fed_funds, ten_year, vix, unemployment) -> dict:
        """Simple rule-based macro regime assessment."""
        signals = []
        risk_score = 0.5  # Neutral

        if vix is not None:
            if vix > 30:
                signals.append("HIGH VOLATILITY (VIX>30)")
                risk_score -= 0.2
            elif vix > 20:
                signals.append("Elevated volatility (VIX>20)")
                risk_score -= 0.1
            else:
                signals.append("Low volatility (VIX<20)")
                risk_score += 0.1

        if ten_year is not None and fed_funds is not None:
            if ten_year < fed_funds:
                signals.append("Inverted yield curve (bearish)")
                risk_score -= 0.15
            else:
                signals.append("Normal yield curve")
                risk_score += 0.05

        if unemployment is not None:
            if unemployment > 5:
                signals.append(f"High unemployment ({unemployment:.1f}%)")
                risk_score -= 0.1
            elif unemployment < 4:
                signals.append(f"Low unemployment ({unemployment:.1f}%)")
                risk_score += 0.05

        risk_score = max(0.0, min(1.0, risk_score))

        if risk_score >= 0.55:
            regime_label = "risk_on"
        elif risk_score <= 0.35:
            regime_label = "risk_off"
        else:
            regime_label = "neutral"

        return {
            "label": regime_label,
            "risk_score": round(risk_score, 2),
            "signals": signals,
        }

    def get_series_history(self, series_id: str, periods: int = 24) -> list:
        """Get historical series as list of {date, value} dicts."""
        data = self.get_series(series_id, periods)
        if data is None:
            return []
        return [
            {"date": str(idx.date()), "value": float(val)} for idx, val in data.dropna().items()
        ]


# Singleton
_fred_service: Optional[FREDDataService] = None


def get_fred_service() -> FREDDataService:
    global _fred_service
    if _fred_service is None:
        _fred_service = FREDDataService()
    return _fred_service
