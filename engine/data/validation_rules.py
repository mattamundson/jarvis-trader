"""
JARVIS TRADER — Data Validation Rules
Enforces data quality standards on incoming OHLCV bars.
Prevents pipeline execution on corrupted or 'garbage' data.
"""

from __future__ import annotations

import logging
from typing import Tuple

import pandas as pd

logger = logging.getLogger("jarvis_trader.data_validation")

class DataValidator:
    """
    Validates a DataFrame of OHLCV bars.
    Returns a score (0.0 to 1.0) and a list of identified issues.
    """

    def __init__(self, spike_threshold: float = 10.0):
        self._spike_threshold = spike_threshold  # Multiplier for ATR spike detection

    def validate(self, df: pd.DataFrame, interval: str = "1h") -> Tuple[float, list[str]]:
        """
        Runs a battery of quality checks.
        """
        issues = []
        scores = []

        if df is None or df.empty:
            return 0.0, ["Dataframe is empty or None."]

        # 1. Basic Price Integrity
        if (df[["open", "high", "low", "close"]] <= 0).any().any():
            scores.append(0.0)
            issues.append("Detected zero or negative prices.")
        else:
            scores.append(1.0)

        # 2. Logic Check (L <= O, L <= C, H >= O, H >= C)
        logic_fail = (
            (df["low"] > df["open"]) |
            (df["low"] > df["close"]) |
            (df["high"] < df["open"]) |
            (df["high"] < df["close"])
        ).any()
        if logic_fail:
            scores.append(0.0)
            issues.append("Detected OHLC logic violations (e.g. High < Low).")
        else:
            scores.append(1.0)

        # 3. Gap Detection (Timestamp continuity)
        # Expected delta based on interval
        delta_map = {
            "1m": pd.Timedelta(minutes=1),
            "5m": pd.Timedelta(minutes=5),
            "15m": pd.Timedelta(minutes=15),
            "1h": pd.Timedelta(hours=1),
            "1d": pd.Timedelta(days=1),
        }
        expected_delta = delta_map.get(interval)
        if expected_delta and len(df) > 1:
            diffs = df.index.to_series().diff().dropna()
            # Filter for RTH (crude: ignore diffs > 16 hours which are usually overnight)
            gaps = diffs[diffs > expected_delta * 1.1]
            large_gaps = gaps[gaps < pd.Timedelta(hours=16)]
            if not large_gaps.empty:
                scores.append(max(0, 1.0 - (len(large_gaps) / len(df)) * 10))
                issues.append(f"Detected {len(large_gaps)} missing bars (gaps) within expected session.")
            else:
                scores.append(1.0)
        else:
            scores.append(1.0)

        # 4. Spike Detection (Extreme moves)
        if len(df) > 20:
            returns = df["close"].pct_change().abs()
            mean_ret = returns.rolling(20).mean()
            std_ret = returns.rolling(20).std()
            spikes = returns[returns > mean_ret + (self._spike_threshold * std_ret)]
            if not spikes.empty:
                scores.append(0.5)
                issues.append(f"Detected {len(spikes)} extreme price spikes (> {self._spike_threshold}x variance).")
            else:
                scores.append(1.0)
        else:
            scores.append(1.0)

        final_score = sum(scores) / len(scores) if scores else 1.0

        if final_score < 0.95:
            logger.warning("[DataValidator] Quality Score: %.2f | Issues: %s", final_score, issues)
        else:
            logger.info("[DataValidator] Data quality check passed (Score: %.2f)", final_score)

        return round(final_score, 2), issues
