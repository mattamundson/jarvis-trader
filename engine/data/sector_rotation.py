"""
Sector rotation monitor for macro context.

Fetches hourly 1h bars for key sector ETFs and computes relative momentum.
Used by FundamentalAnalystAgent to provide sector context.

Instruments mapped to sectors:
  MNQ/NQ  ← Technology (QQQ), vs Broad Market (SPY)
  MES/ES  ← Broad Market (SPY)
  MCL/CL  ← Energy (XLE)
"""

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

# Sector ETF mapping
INSTRUMENT_SECTORS = {
    "MNQ": {"primary": "QQQ", "benchmark": "SPY", "sector": "technology"},
    "NQ":  {"primary": "QQQ", "benchmark": "SPY", "sector": "technology"},
    "MES": {"primary": "SPY", "benchmark": "SPY", "sector": "broad_market"},
    "ES":  {"primary": "SPY", "benchmark": "SPY", "sector": "broad_market"},
    "MCL": {"primary": "XLE", "benchmark": "SPY", "sector": "energy"},
    "CL":  {"primary": "XLE", "benchmark": "SPY", "sector": "energy"},
}


class SectorRotationMonitor:
    """Sector rotation context for pipeline analysis."""

    def __init__(self, market_data_manager):
        """
        Args:
            market_data_manager: The engine's MarketDataManager instance
        """
        self.mdm = market_data_manager

    def get_sector_context(self, instrument: str) -> Dict[str, Any]:
        """
        Get sector rotation context for a futures instrument.

        Returns dict with:
        - sector_momentum: "OUTPERFORMING" / "NEUTRAL" / "UNDERPERFORMING"
        - primary_etf_change_pct: 5-day change of primary sector ETF
        - relative_strength: primary vs benchmark (positive = outperforming)
        - bias_adjustment: float -0.2 to +0.2 for analyst signal scaling
        - description: human-readable summary string
        """
        instrument = instrument.upper()
        mapping = INSTRUMENT_SECTORS.get(instrument)

        if not mapping:
            return self._neutral_context("No sector mapping for instrument")

        primary_etf = mapping["primary"]
        benchmark_etf = mapping["benchmark"]
        sector = mapping["sector"]

        try:
            # Fetch 5-day daily bars for sector ETF and benchmark
            primary_bars = self._get_recent_bars(primary_etf, limit=5)
            benchmark_bars = self._get_recent_bars(benchmark_etf, limit=5)

            if primary_bars is None or len(primary_bars) < 2:
                return self._neutral_context(f"Insufficient {primary_etf} data")

            # Compute 5-day price change %
            primary_change = self._compute_change_pct(primary_bars)

            if primary_etf == benchmark_etf:
                relative_strength = 0.0
                benchmark_change = primary_change
            elif benchmark_bars is not None and len(benchmark_bars) >= 2:
                benchmark_change = self._compute_change_pct(benchmark_bars)
                relative_strength = primary_change - benchmark_change
            else:
                relative_strength = 0.0
                benchmark_change = 0.0

            # Classify momentum
            if relative_strength > 0.5:
                momentum = "OUTPERFORMING"
                bias = 0.15   # Boost directional signals
            elif relative_strength < -0.5:
                momentum = "UNDERPERFORMING"
                bias = -0.20  # Derate signals (stronger penalty for underperform)
            else:
                momentum = "NEUTRAL"
                bias = 0.0

            description = (
                f"{primary_etf} {primary_change:+.1f}% vs {benchmark_etf} {benchmark_change:+.1f}% "
                f"(5-day) | Sector: {momentum}"
            )

            return {
                "instrument": instrument,
                "sector": sector,
                "primary_etf": primary_etf,
                "primary_change_pct": round(primary_change, 2),
                "benchmark_change_pct": round(benchmark_change, 2),
                "relative_strength": round(relative_strength, 2),
                "sector_momentum": momentum,
                "bias_adjustment": bias,
                "description": description,
                "source": "sector_rotation",
            }

        except Exception as e:
            logger.debug("Sector rotation error for %s: %s", instrument, e)
            return self._neutral_context(f"Error: {e}")

    def _get_recent_bars(self, symbol: str, limit: int = 5):
        """Fetch recent daily bars for an ETF symbol."""
        try:
            # Try to get bars from market data manager
            # The exact method may vary — try common patterns
            if hasattr(self.mdm, 'get_bars'):
                return self.mdm.get_bars(symbol, interval="1d", limit=limit)
            elif hasattr(self.mdm, 'fetch_bars'):
                return self.mdm.fetch_bars(symbol, interval="1d", limit=limit)
            elif hasattr(self.mdm, 'get_historical_data'):
                return self.mdm.get_historical_data(symbol, interval="1d", limit=limit)
            return None
        except Exception:
            return None

    def _compute_change_pct(self, bars) -> float:
        """Compute percentage change from first to last bar."""
        try:
            if hasattr(bars, 'iloc'):  # DataFrame
                first_close = bars.iloc[0]['close'] if 'close' in bars.columns else bars.iloc[0][4]
                last_close = bars.iloc[-1]['close'] if 'close' in bars.columns else bars.iloc[-1][4]
            else:  # List of dicts
                first_close = bars[0].get('close', bars[0].get('c', 0))
                last_close = bars[-1].get('close', bars[-1].get('c', 0))

            if first_close == 0:
                return 0.0
            return (last_close - first_close) / first_close * 100
        except (IndexError, KeyError, TypeError):
            return 0.0

    def _neutral_context(self, reason: str) -> Dict[str, Any]:
        return {
            "sector_momentum": "NEUTRAL",
            "bias_adjustment": 0.0,
            "description": f"Sector data unavailable: {reason}",
            "source": "sector_rotation",
        }
