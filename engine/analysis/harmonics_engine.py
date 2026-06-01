"""
JARVIS ANALYSIS — Harmonic Pattern Engine
=========================================
Identifies XABCD harmonic patterns (Gartley, Bat, Butterfly, etc.)
using swing highs/lows and Fibonacci ratios.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import pandas as pd


@dataclass
class SwingPoint:
    index: int
    price: float
    type: str  # "high" or "low"

@dataclass
class HarmonicPattern:
    name: str
    type: str  # "bullish" or "bearish"
    points: List[Tuple[int, float]]  # List of (index, price) for X, A, B, C, D
    confidence: float
    ratios: Dict[str, float]

class HarmonicEngine:
    """
    Detects Fibonacci-based harmonic patterns from OHLC data.
    """

    def __init__(self, deviation: float = 0.05):
        self.deviation = deviation  # Allowance for ratio mismatch (5%)

    def get_swing_points(self, df: pd.DataFrame, window: int = 5) -> List[SwingPoint]:
        """
        Identify local swing highs and lows using a lookback window.
        """
        swings = []
        for i in range(window, len(df) - window):
            # Check for high
            is_high = True
            for j in range(i - window, i + window + 1):
                if df["high"].iloc[j] > df["high"].iloc[i]:
                    is_high = False
                    break
            if is_high:
                swings.append(SwingPoint(i, df["high"].iloc[i], "high"))
                continue

            # Check for low
            is_low = True
            for j in range(i - window, i + window + 1):
                if df["low"].iloc[j] < df["low"].iloc[i]:
                    is_low = False
                    break
            if is_low:
                swings.append(SwingPoint(i, df["low"].iloc[i], "low"))

        # Consolidate: if multiple highs/lows in a row, take the most extreme
        if not swings:
            return []

        consolidated = [swings[0]]
        for s in swings[1:]:
            last = consolidated[-1]
            if last.type == s.type:
                if (last.type == "high" and s.price > last.price) or \
                   (last.type == "low" and s.price < last.price):
                    consolidated[-1] = s
            else:
                consolidated.append(s)

        return consolidated

    def detect_patterns(self, df: pd.DataFrame) -> List[HarmonicPattern]:
        """
        Scan for XABCD patterns in recent swing points.
        """
        swings = self.get_swing_points(df)
        if len(swings) < 5:
            return []

        patterns = []
        # Look at every contiguous set of 5 swing points (X, A, B, C, D)
        for i in range(len(swings) - 4):
            pts = swings[i : i+5]
            pattern = self._check_points(pts)
            if pattern:
                patterns.append(pattern)

        return patterns

    def _check_points(self, pts: List[SwingPoint]) -> Optional[HarmonicPattern]:
        """
        Check ratios for a set of 5 points.
        X=0, A=1, B=2, C=3, D=4
        """
        x, a, b, c, d = pts[0].price, pts[1].price, pts[2].price, pts[3].price, pts[4].price

        # Calculate legs
        xa = abs(a - x)
        ab = abs(b - a)
        bc = abs(c - b)
        cd = abs(d - c)

        if xa == 0 or ab == 0 or bc == 0 or cd == 0:
            return None

        # Ratios (only ab_xa and xd_xa are used by pattern matchers below;
        # bc_ab/cd_bc/ad_xa retained as comments for future patterns)
        ab_xa = ab / xa
        xd_xa = abs(d - x) / xa

        side = "bullish" if pts[0].type == "low" and pts[1].type == "high" else "bearish"
        # Mirror for bearish: X(high), A(low), B(high), C(low), D(high)

        # Gartley
        if self._is_near(ab_xa, 0.618) and self._is_near(xd_xa, 0.786):
            return HarmonicPattern("Gartley", side, [(p.index, p.price) for p in pts], 0.9, {"AB/XA": ab_xa, "XD/XA": xd_xa})

        # Bat
        if self._is_near(ab_xa, 0.382, 0.50) and self._is_near(xd_xa, 0.886):
            return HarmonicPattern("Bat", side, [(p.index, p.price) for p in pts], 0.9, {"AB/XA": ab_xa, "XD/XA": xd_xa})

        # Butterfly
        if self._is_near(ab_xa, 0.786) and self._is_near(xd_xa, 1.27, 1.618):
            return HarmonicPattern("Butterfly", side, [(p.index, p.price) for p in pts], 0.9, {"AB/XA": ab_xa, "XD/XA": xd_xa})

        # Crab
        if self._is_near(ab_xa, 0.382, 0.618) and self._is_near(xd_xa, 1.618):
            return HarmonicPattern("Crab", side, [(p.index, p.price) for p in pts], 0.9, {"AB/XA": ab_xa, "XD/XA": xd_xa})

        return None

    def _is_near(self, val: float, target: float, target2: Optional[float] = None) -> bool:
        if target2 is not None:
            # Check if within range [target, target2] or [target2, target]
            lo = min(target, target2) * (1 - self.deviation)
            hi = max(target, target2) * (1 + self.deviation)
            return lo <= val <= hi
        else:
            return target * (1 - self.deviation) <= val <= target * (1 + self.deviation)
