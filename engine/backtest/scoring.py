"""
Jarvis-Trader Signal Scorer

Additive risk-adjusted scoring model:
  Score = S_structure + S_trend + S_momentum + S_volatility - P_risk

Component ranges:
  structure : 0-40  (IB + VA/VAL + BUYER/SELLER control)
  trend     : 0-30  (VWAP, EMA ribbon, ADX)
  momentum  : 0-20  (STC, ROC)
  volatility: 0-10  (ATR-consumed, VWAP z-score, regime)
  risk_pen  : 0-25  (news, low-vol, MTF miss, EXHAUSTED/COMPRESSION)

Tier mapping:
  >= 75  → A_PLUS
  >= 60  → A
  >= 40  → B
  < 40   → C
  blocked → BLOCKED
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class ScoreResult:
    total: float
    structure: float
    trend: float
    momentum: float
    volatility: float
    risk_penalty: float
    tier: str
    blocked_reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Scorer
# ---------------------------------------------------------------------------

class SignalScorer:
    """
    Score a single signal row produced by the backtest engine.

    The ``row`` object is expected to be a namedtuple produced by
    ``DataFrame.itertuples()`` and must expose the following attributes
    (all optional — missing attributes gracefully default to zero/neutral):

      structure_position : str  e.g. 'BUYER_CONTROL'
      broke_ib_high      : bool
      broke_ib_low       : bool
      c_period_confirmed : bool
      above_vwap         : bool
      below_vwap         : bool
      vwap_zscore        : float
      adx                : float
      ema_8_gt_21        : bool
      ema_21_gt_34       : bool
      stc_value          : float
      roc_10             : float
      atr_consumed_pct   : float  (0.0-1.0, fraction of daily ATR used)
      regime             : str
      entry_signal       : str
      news_blackout      : bool
      low_volume         : bool
      mtf_blocked        : bool
    """

    # Tier thresholds
    THRESH_A_PLUS = 75.0
    THRESH_A = 60.0
    THRESH_B = 40.0

    # Blocking signals — any of these → BLOCKED regardless of numeric score
    BLOCK_SIGNALS = frozenset({
        "LOW_VOLUME_BLOCK",
        "NEWS_BLACKOUT",
        "MTF_BLOCKED",
        "ROUTING_POLICY_BLOCK",
        "KILL_SWITCH_ACTIVE",
        "CONSECUTIVE_LOSS_BLOCK",
        "MAX_DAILY_LOSS_BLOCK",
    })

    def score_row(self, row) -> ScoreResult:
        """Score a single signal row.  Thread-safe (stateless)."""
        s_struct = self._score_structure(row)
        s_trend = self._score_trend(row)
        s_mom = self._score_momentum(row)
        s_vol = self._score_volatility(row)
        p_risk = self._risk_penalty(row)

        total = s_struct + s_trend + s_mom + s_vol - p_risk
        total = max(0.0, total)  # floor at zero

        signal = getattr(row, "entry_signal", "")
        hard_block = (
            p_risk >= 25.0
            or signal in self.BLOCK_SIGNALS
            or getattr(row, "news_blackout", False)
            or getattr(row, "low_volume", False)
            or getattr(row, "mtf_blocked", False)
        )

        tier = self._map_tier(total, hard_block)
        reason = signal if hard_block else None

        return ScoreResult(
            total=round(total, 2),
            structure=round(s_struct, 2),
            trend=round(s_trend, 2),
            momentum=round(s_mom, 2),
            volatility=round(s_vol, 2),
            risk_penalty=round(p_risk, 2),
            tier=tier,
            blocked_reason=reason,
        )

    # ------------------------------------------------------------------
    # Component scorers
    # ------------------------------------------------------------------

    def _score_structure(self, row) -> float:
        """0-40 points based on IB and market structure."""
        score = 0.0
        pos = getattr(row, "structure_position", "NEUTRAL_STRUCTURE")

        # Primary structure alignment
        if pos == "BUYER_CONTROL":
            score += 20.0
        elif pos == "SELLER_CONTROL":
            score += 20.0  # directionally aligned bear signal
        else:
            score += 5.0   # neutral/contested

        # IB breakout confirmation
        if getattr(row, "broke_ib_high", False) or getattr(row, "broke_ib_low", False):
            score += 12.0

        # C-period / acceptance
        if getattr(row, "c_period_confirmed", False):
            score += 8.0

        return min(score, 40.0)

    def _score_trend(self, row) -> float:
        """0-30 points based on VWAP, EMA ribbon, ADX."""
        score = 0.0

        # VWAP alignment
        side = getattr(row, "side", "")  # 'LONG' or 'SHORT'
        above = getattr(row, "above_vwap", False)
        below = getattr(row, "below_vwap", False)
        if (side == "LONG" and above) or (side == "SHORT" and below):
            score += 10.0

        # EMA ribbon alignment
        if getattr(row, "ema_8_gt_21", False):
            score += 5.0
        if getattr(row, "ema_21_gt_34", False):
            score += 5.0

        # ADX trend strength
        adx = getattr(row, "adx", 0.0) or 0.0
        if adx >= 30:
            score += 10.0
        elif adx >= 20:
            score += 5.0

        return min(score, 30.0)

    def _score_momentum(self, row) -> float:
        """0-20 points based on STC and ROC."""
        score = 0.0
        side = getattr(row, "side", "")
        stc = getattr(row, "stc_value", 50.0) or 50.0
        roc = getattr(row, "roc_10", 0.0) or 0.0

        # Schaff Trend Cycle
        if side == "LONG" and stc < 23:
            score += 12.0  # oversold — high-quality long setup
        elif side == "LONG" and stc < 40:
            score += 6.0
        elif side == "SHORT" and stc > 83:
            score += 12.0  # overbought — high-quality short setup
        elif side == "SHORT" and stc > 70:
            score += 6.0

        # Rate of Change
        if side == "LONG" and roc > 0:
            score += 8.0
        elif side == "SHORT" and roc < 0:
            score += 8.0

        return min(score, 20.0)

    def _score_volatility(self, row) -> float:
        """0-10 points based on ATR-consumed and regime."""
        score = 0.0
        atr_consumed = getattr(row, "atr_consumed_pct", 0.5) or 0.5
        regime = getattr(row, "regime", "RANGE_BOUND")

        # Prefer signals early in daily range (< 50% ATR consumed)
        if atr_consumed < 0.35:
            score += 6.0
        elif atr_consumed < 0.55:
            score += 3.0

        # Regime bonus
        if regime in ("TRENDING_BULL", "TRENDING_BEAR"):
            score += 4.0
        elif regime == "RANGE_BOUND":
            score += 2.0
        # EXHAUSTED / COMPRESSION → 0 bonus (and also add penalty below)

        return min(score, 10.0)

    def _risk_penalty(self, row) -> float:
        """0-25 penalty points for adverse conditions."""
        penalty = 0.0
        regime = getattr(row, "regime", "")

        if getattr(row, "news_blackout", False):
            penalty += 25.0
        if getattr(row, "low_volume", False):
            penalty += 15.0
        if getattr(row, "mtf_blocked", False):
            penalty += 10.0
        if regime in ("EXHAUSTED", "COMPRESSION"):
            penalty += 8.0

        # High VWAP z-score indicates extension, not a good entry
        zscore = abs(getattr(row, "vwap_zscore", 0.0) or 0.0)
        if zscore > 2.5:
            penalty += 5.0

        return min(penalty, 25.0)

    def _map_tier(self, score: float, blocked: bool) -> str:
        if blocked or score < self.THRESH_B:
            return "BLOCKED" if blocked else "C"
        if score >= self.THRESH_A_PLUS:
            return "A_PLUS"
        if score >= self.THRESH_A:
            return "A"
        return "B"
