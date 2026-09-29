"""
System 1 — Macro Filter v2 (Real Inputs)
=========================================
Rebuilds the macro regime classifier with three primary real-world inputs:

  1. Yield curve (10Y–2Y spread)   — via yfinance ^TNX / ^IRX or FRED T10Y2Y
  2. Credit spreads (HYG/LQD ratio) — via yfinance, proxy for HY vs IG spread
  3. Copper/Gold ratio (CPER/GLD)   — via yfinance, cyclical demand signal

Design:
  - Each input scores -2 to +2 based on level + direction of change
  - Composite = weighted sum → [−6, +6] → mapped to [0.60, 1.15] multiplier
  - Graceful fallback: any input failure → neutral score for that input
  - No FRED API key required (yfinance covers all three)
  - Results cached 1h to avoid re-fetching on every weekly bar

Signal logic per input
──────────────────────
Yield curve (10Y–2Y, %) — higher = more bullish (steepening = growth expected)
  >  1.0 : +2 (steep, expansion)
   0.25–1.0: +1
  -0.25–0.25: 0 (flat)
  -1.0– -0.25: -1
  < -1.0 : -2 (deeply inverted, recession signal)

Credit spread (HYG/LQD price ratio, change from 20-week MA)
  Ratio rising (credit improving):  +2/+1
  Ratio flat:                         0
  Ratio falling (credit stress):     -1/-2

Copper/Gold ratio (CPER/GLD price ratio, normalized momentum)
  Ratio in top quartile of 52-week range: +2
  Ratio in top half:                      +1
  Ratio in bottom half:                   -1
  Ratio in bottom quartile:               -2

Weights: yield_curve=0.40, credit_spread=0.35, copper_gold=0.25

Multiplier mapping (composite −6..+6 → 0.60..1.15):
  composite >=  3:  1.15 (strong macro tailwind — add exposure)
  composite >=  1:  1.05
  composite >= -1:  1.00 (neutral)
  composite >= -3:  0.85
  composite <  -3:  0.65 (macro headwind — reduce)
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Cache TTL in seconds
_CACHE_TTL = 3600  # 1 hour


class MacroFilterV2:
    """
    Real-input macro regime classifier for Strategy C+ v2.

    Uses yield curve, credit spreads, and copper/gold ratio as primary
    signals — no lagging economic indicators, no FRED API key required.

    Parameters
    ----------
    weights : tuple (yield_curve, credit_spread, copper_gold)
        Relative weights for each component. Default: (0.40, 0.35, 0.25)
    use_direction : bool
        If True, also considers 4-week direction of change for each signal.
        Default True — adds dynamic element beyond just level.
    """

    MULTIPLIER_MAP = [
        (3.0, 1.15),
        (1.0, 1.05),
        (-1.0, 1.00),
        (-3.0, 0.85),
        (float("-inf"), 0.65),
    ]

    def __init__(
        self,
        weights: tuple = (0.40, 0.35, 0.25),
        use_direction: bool = True,
    ):
        self.weights = weights
        self.use_direction = use_direction
        self._cache: Optional[tuple[float, dict]] = None
        self._cache_ts: float = 0.0

    # ── Public API ────────────────────────────────────────────────────────────
    def get_live_multiplier(self) -> tuple[float, dict]:
        """
        Fetch live macro data and return (multiplier, detail).
        Results cached for 1 hour.
        """
        now = time.time()
        if self._cache and (now - self._cache_ts) < _CACHE_TTL:
            return self._cache

        detail = self._compute_live_detail()
        multiplier = self._composite_to_multiplier(detail["composite"])
        detail["multiplier"] = round(multiplier, 4)

        self._cache = (multiplier, detail)
        self._cache_ts = now
        logger.info(
            "[MacroFilterV2] composite=%.2f → multiplier=%.3f | "
            "YC=%.3f(s=%.1f) CR=%.3f(s=%.1f) CG=%.3f(s=%.1f)",
            detail["composite"],
            multiplier,
            detail.get("yield_curve_val", 0),
            detail.get("yield_curve_score", 0),
            detail.get("credit_spread_val", 0),
            detail.get("credit_spread_score", 0),
            detail.get("copper_gold_val", 0),
            detail.get("copper_gold_score", 0),
        )
        return multiplier, detail

    def get_historical_multiplier_series(
        self,
        weekly_index: pd.DatetimeIndex,
    ) -> pd.Series:
        """
        Build a historical multiplier series for backtest use.
        Downloads full history for all three inputs and applies the
        same scoring logic week-by-week.
        """
        try:
            yc_series = self._fetch_yield_curve_history()
            credit_series = self._fetch_credit_history()
            copper_series = self._fetch_copper_gold_history()
        except Exception as e:
            logger.warning("[MacroFilterV2] History fetch failed: %s — neutral series", e)
            return pd.Series(1.0, index=weekly_index)

        mults = []
        for date in weekly_index:
            try:
                yc_score = self._score_yield_curve_at(yc_series, date)
                cr_score = self._score_credit_at(credit_series, date)
                cg_score = self._score_copper_gold_at(copper_series, date)
                composite = (
                    self.weights[0] * yc_score * 6
                    + self.weights[1] * cr_score * 6
                    + self.weights[2] * cg_score * 6
                )
                mults.append(self._composite_to_multiplier(composite))
            except Exception:
                mults.append(1.0)

        return pd.Series(mults, index=weekly_index).fillna(1.0)

    # ── Live computation ──────────────────────────────────────────────────────
    def _compute_live_detail(self) -> dict:
        detail = {
            "source": "yfinance_live",
            "generated_at": datetime.now().isoformat(),
            "yield_curve_val": None,
            "yield_curve_score": 0.0,
            "credit_spread_val": None,
            "credit_spread_score": 0.0,
            "copper_gold_val": None,
            "copper_gold_score": 0.0,
            "composite": 0.0,
        }

        # 1. Yield curve
        try:
            yc_val, yc_score = self._live_yield_curve()
            detail["yield_curve_val"] = round(yc_val, 3)
            detail["yield_curve_score"] = round(yc_score, 2)
        except Exception as e:
            logger.debug("[MacroFilterV2] Yield curve error: %s", e)

        # 2. Credit spread
        try:
            cr_val, cr_score = self._live_credit_spread()
            detail["credit_spread_val"] = round(cr_val, 4)
            detail["credit_spread_score"] = round(cr_score, 2)
        except Exception as e:
            logger.debug("[MacroFilterV2] Credit spread error: %s", e)

        # 3. Copper/Gold
        try:
            cg_val, cg_score = self._live_copper_gold()
            detail["copper_gold_val"] = round(cg_val, 4)
            detail["copper_gold_score"] = round(cg_score, 2)
        except Exception as e:
            logger.debug("[MacroFilterV2] Copper/gold error: %s", e)

        # Composite (each score is in [-2, +2], weight-sum in [-6, +6] range)
        composite = (
            self.weights[0] * detail["yield_curve_score"] * 3
            + self.weights[1] * detail["credit_spread_score"] * 3
            + self.weights[2] * detail["copper_gold_score"] * 3
        )
        detail["composite"] = round(composite, 3)
        return detail

    # ── Input: Yield Curve ────────────────────────────────────────────────────
    def _live_yield_curve(self) -> tuple[float, float]:
        """
        Fetch 10Y and 2Y yields via yfinance.
        Returns (spread_pct, score).
        Primary: ^TNX (10Y) and ^IRX (13-week, ≈ 2Y proxy)
        Better:  ^TYX minus ^FVX or direct T10Y2Y via FRED
        """
        import yfinance as yf

        # Try direct T10Y2Y from yfinance (available as ^TNX minus manual)
        # yfinance doesn't have T10Y2Y directly, so compute from components
        data = yf.download(
            ["^TNX", "^IRX"],  # 10Y, 13-week (short-end proxy)
            period="3mo",
            interval="1wk",
            progress=False,
            auto_adjust=True,
        )
        if data.empty:
            raise ValueError("yfinance ^TNX/^IRX returned empty")

        close = data["Close"] if "Close" in data.columns else data
        if hasattr(close.columns, "get_level_values"):
            close.columns = close.columns.get_level_values(0)

        tnx = close["^TNX"].dropna()
        irx = close["^IRX"].dropna()

        if len(tnx) < 2 or len(irx) < 2:
            raise ValueError("Insufficient yield data")

        # IRX is quoted as annualized discount rate * 100 — divide by 100
        ten_y = float(tnx.iloc[-1])
        two_y = float(irx.iloc[-1]) / 100.0 * 100  # already in % terms
        spread = ten_y - two_y

        score = self._score_yield_curve(spread)

        # Direction adjustment (4-week change)
        if self.use_direction and len(tnx) >= 5:
            prev_spread = float(tnx.iloc[-5]) - float(irx.iloc[-5])
            if spread > prev_spread + 0.15:
                score = min(2.0, score + 0.5)  # steepening
            elif spread < prev_spread - 0.15:
                score = max(-2.0, score - 0.5)  # flattening

        return spread, score

    @staticmethod
    def _score_yield_curve(spread: float) -> float:
        if spread > 1.0:
            return 2.0
        if spread > 0.25:
            return 1.0
        if spread > -0.25:
            return 0.0
        if spread > -1.0:
            return -1.0
        return -2.0

    # ── Input: Credit Spread ──────────────────────────────────────────────────
    def _live_credit_spread(self) -> tuple[float, float]:
        """
        HYG/LQD price ratio as a proxy for HY credit spread.
        Rising ratio = tightening spreads = risk-on.
        """
        import yfinance as yf

        data = yf.download(
            ["HYG", "LQD"],
            period="1y",
            interval="1wk",
            progress=False,
            auto_adjust=True,
        )
        if data.empty:
            raise ValueError("HYG/LQD empty")

        close = data["Close"] if "Close" in data.columns else data
        if hasattr(close.columns, "get_level_values"):
            close.columns = close.columns.get_level_values(0)

        ratio = (close["HYG"] / close["LQD"]).dropna()
        if len(ratio) < 20:
            raise ValueError("Insufficient HYG/LQD history")

        current_ratio = float(ratio.iloc[-1])
        ma20 = float(ratio.rolling(20).mean().iloc[-1])
        pct_above_ma = (current_ratio - ma20) / ma20

        score = self._score_credit_ratio(pct_above_ma)

        if self.use_direction and len(ratio) >= 5:
            prev_ratio = float(ratio.iloc[-5])
            prev_ma20 = float(ratio.rolling(20).mean().iloc[-5])
            prev_pct = (prev_ratio - prev_ma20) / prev_ma20
            trend = pct_above_ma - prev_pct
            if trend > 0.005:
                score = min(2.0, score + 0.5)
            elif trend < -0.005:
                score = max(-2.0, score - 0.5)

        return current_ratio, score

    @staticmethod
    def _score_credit_ratio(pct_above_ma: float) -> float:
        if pct_above_ma > 0.015:
            return 2.0
        if pct_above_ma > 0.003:
            return 1.0
        if pct_above_ma > -0.003:
            return 0.0
        if pct_above_ma > -0.015:
            return -1.0
        return -2.0

    # ── Input: Copper/Gold Ratio ──────────────────────────────────────────────
    def _live_copper_gold(self) -> tuple[float, float]:
        """
        CPER (copper ETF) / GLD (gold ETF) ratio.
        High ratio = cyclical demand strong = risk-on.
        Scored as percentile within 52-week range.
        """
        import yfinance as yf

        data = yf.download(
            ["CPER", "GLD"],
            period="2y",
            interval="1wk",
            progress=False,
            auto_adjust=True,
        )
        if data.empty:
            raise ValueError("CPER/GLD empty")

        close = data["Close"] if "Close" in data.columns else data
        if hasattr(close.columns, "get_level_values"):
            close.columns = close.columns.get_level_values(0)

        ratio = (close["CPER"] / close["GLD"]).dropna()
        if len(ratio) < 52:
            raise ValueError("Insufficient CPER/GLD history")

        current_ratio = float(ratio.iloc[-1])
        recent_52w = ratio.tail(52)
        r_min, r_max = float(recent_52w.min()), float(recent_52w.max())
        if r_max == r_min:
            return current_ratio, 0.0

        percentile = (current_ratio - r_min) / (r_max - r_min)  # 0–1
        score = self._score_percentile(percentile)

        return current_ratio, score

    @staticmethod
    def _score_percentile(p: float) -> float:
        if p >= 0.75:
            return 2.0
        if p >= 0.50:
            return 1.0
        if p >= 0.25:
            return -1.0
        return -2.0

    # ── Multiplier mapping ────────────────────────────────────────────────────
    def _composite_to_multiplier(self, composite: float) -> float:
        for threshold, mult in self.MULTIPLIER_MAP:
            if composite >= threshold:
                return mult
        return 0.65

    # ── Historical helpers ────────────────────────────────────────────────────
    def _fetch_yield_curve_history(self) -> pd.Series:
        import yfinance as yf

        data = yf.download(
            ["^TNX", "^IRX"], period="max", interval="1wk", progress=False, auto_adjust=True
        )
        close = data["Close"]
        if hasattr(close.columns, "get_level_values"):
            close.columns = close.columns.get_level_values(0)
        return (close["^TNX"] - close["^IRX"]).dropna()

    def _fetch_credit_history(self) -> pd.Series:
        import yfinance as yf

        data = yf.download(
            ["HYG", "LQD"], period="max", interval="1wk", progress=False, auto_adjust=True
        )
        close = data["Close"]
        if hasattr(close.columns, "get_level_values"):
            close.columns = close.columns.get_level_values(0)
        return (close["HYG"] / close["LQD"]).dropna()

    def _fetch_copper_gold_history(self) -> pd.Series:
        import yfinance as yf

        data = yf.download(
            ["CPER", "GLD"], period="max", interval="1wk", progress=False, auto_adjust=True
        )
        close = data["Close"]
        if hasattr(close.columns, "get_level_values"):
            close.columns = close.columns.get_level_values(0)
        return (close["CPER"] / close["GLD"]).dropna()

    def _score_yield_curve_at(self, series: pd.Series, date: pd.Timestamp) -> float:
        try:
            val = float(series.asof(date))
            return self._score_yield_curve(val) / 2.0  # normalize to [-1, +1]
        except Exception:
            return 0.0

    def _score_credit_at(self, series: pd.Series, date: pd.Timestamp) -> float:
        try:
            idx = series.index.asof(date)
            pos = series.index.get_loc(idx)
            if pos < 20:
                return 0.0
            window = series.iloc[max(0, pos - 20) : pos + 1]
            ma20 = float(window.mean())
            val = float(series.iloc[pos])
            pct = (val - ma20) / ma20
            return self._score_credit_ratio(pct) / 2.0
        except Exception:
            return 0.0

    def _score_copper_gold_at(self, series: pd.Series, date: pd.Timestamp) -> float:
        try:
            idx = series.index.asof(date)
            pos = series.index.get_loc(idx)
            if pos < 52:
                return 0.0
            window = series.iloc[max(0, pos - 52) : pos + 1]
            val = float(series.iloc[pos])
            r_min, r_max = float(window.min()), float(window.max())
            if r_max == r_min:
                return 0.0
            p = (val - r_min) / (r_max - r_min)
            return self._score_percentile(p) / 2.0
        except Exception:
            return 0.0
