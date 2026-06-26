"""Proves the harmonic detector can actually fire.

The live harmonic analyst has recorded 0 patterns across all trades, which is
consistent with BOTH "XABCD patterns are rare" and "detect_patterns is a silent
no-op." This test removes that ambiguity: it constructs a textbook bullish
Gartley (AB/XA=0.618, XD/XA=0.786) as synthetic bars and asserts the engine
detects it and the agent emits the expected non-zero signal end-to-end.
"""

from __future__ import annotations

import pandas as pd
import pytest

from agents.harmonic_agent import HarmonicAgent
from analysis.harmonics_engine import HarmonicEngine

# Bullish Gartley pivots (index, price): X low, A high, B low, C high, D low.
#   AB/XA = |107.64-120| / |120-100| = 12.36/20 = 0.618   (Gartley B)
#   XD/XA = |84.28-100|  / 20        = 15.72/20 = 0.786    (Gartley D)
# D sits at index 103 of a 110-bar frame -> within 10 bars of the end, so the
# agent's "active pattern" filter keeps it. >=100 bars clears the agent guard.
_ANCHORS = [
    (0, 106.0),
    (20, 100.0),  # X (low)
    (45, 120.0),  # A (high)
    (70, 107.64),  # B (low)
    (90, 115.0),  # C (high)
    (103, 84.28),  # D (low)
    (109, 90.0),
]


def _gartley_df() -> pd.DataFrame:
    prices = [None] * 110
    for (i0, p0), (i1, p1) in zip(_ANCHORS, _ANCHORS[1:], strict=False):
        for k in range(i0, i1):
            prices[k] = p0 + (p1 - p0) * (k - i0) / (i1 - i0)
    prices[109] = _ANCHORS[-1][1]
    # Flat OHLC bars: each pivot is a clean isolated swing high/low.
    return pd.DataFrame({"open": prices, "high": prices, "low": prices, "close": prices})


def test_engine_detects_known_gartley():
    patterns = HarmonicEngine().detect_patterns(_gartley_df())
    found = [(p.name, p.type) for p in patterns]
    assert ("Gartley", "bullish") in found, f"no Gartley detected; got {found}"


class _FakeDataManager:
    def __init__(self, df):
        self._df = df

    async def get_bars(self, symbol, lookback_days=10, timeframe="15m", is_futures=False):
        return self._df


@pytest.mark.asyncio
async def test_agent_emits_nonzero_signal_on_active_pattern():
    agent = HarmonicAgent(_FakeDataManager(_gartley_df()))
    report = await agent.analyze("MES", timeframe="1h", is_futures=True)
    # Bullish pattern at D -> +0.7 per harmonic_agent.analyze.
    assert report.signal == 0.7, f"expected +0.7, got {report.signal}: {report.summary}"
    assert report.patterns, "agent reported no active patterns"


@pytest.mark.asyncio
async def test_agent_zero_when_insufficient_bars():
    # < 100 bars -> guard returns empty report (the dormant daily-timeframe case).
    short = _gartley_df().iloc[:60].reset_index(drop=True)
    agent = HarmonicAgent(_FakeDataManager(short))
    report = await agent.analyze("MES", timeframe="1d")
    assert report.signal == 0
