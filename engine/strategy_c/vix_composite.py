"""
VIX Composite Signal — 4-Component Regime Filter
=================================================
Extends the jarvis-trader VIX overlay (analytics/vix_overlay.py)
for weekly strategic regime rotation.

Components:
  1. VIX Level        — raw level vs thresholds (CALM/NORMAL/CAUTION/ELEVATED/EXTREME)
  2. VIX Momentum     — 4-week rate-of-change (rising VIX = de-risk)
  3. VIX vs VIX MA    — VIX relative to 26-week moving average (structural regime)
  4. VIX/Realized Spread — implied vs realized vol gap (fear premium signal)

The composite score ranges 0.0–1.0:
  >= 0.60 → RISK_ON   (full position per vol target)
  0.35–0.60 → NEUTRAL (75% of vol-target scale)
  < 0.35  → RISK_OFF  (50% of vol-target scale, or cash if below 0.20)

Aligned with jarvis-trader thresholds:
  CALM    (VIX<12):  score contribution 1.0
  NORMAL  (12-20):   score contribution 0.75
  CAUTION (20-30):   score contribution 0.40
  ELEVATED(30-40):   score contribution 0.15
  EXTREME (40+):     score contribution 0.0
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

# Match jarvis-trader vix_overlay.py thresholds exactly
VIX_LEVEL_SCORES = {
    "CALM":     (0,  12,  1.00),
    "NORMAL":   (12, 20,  0.75),
    "CAUTION":  (20, 30,  0.40),
    "ELEVATED": (30, 40,  0.15),
    "EXTREME":  (40, 999, 0.00),
}

VIX_SCALE_MAP = {
    "CALM":     1.00,
    "NORMAL":   1.00,
    "CAUTION":  0.75,
    "ELEVATED": 0.50,
    "EXTREME":  0.00,
}


def classify_vix_level(vix: float) -> tuple[str, float]:
    """Return (regime_name, score) for a given VIX value."""
    for name, (lo, hi, score) in VIX_LEVEL_SCORES.items():
        if lo <= vix < hi:
            return name, score
    return "EXTREME", 0.0


class VIXComposite:
    """
    4-component VIX composite signal for weekly regime filtering.

    Parameters
    ----------
    vix_ma_period : int
        Weeks for VIX structural moving average (default 26)
    mom_period : int
        Weeks for VIX momentum lookback (default 4)
    component_weights : tuple
        Weights for (level, momentum, ma_ratio, fear_premium) — must sum to 1.0
    """

    def __init__(
        self,
        vix_ma_period: int = 26,
        mom_period: int = 4,
        component_weights: tuple = (0.40, 0.25, 0.20, 0.15),
    ):
        self.vix_ma_period = vix_ma_period
        self.mom_period = mom_period
        self.w_level, self.w_mom, self.w_ma, self.w_fear = component_weights

    def compute(
        self,
        weekly_vix: pd.Series,
        weekly_realized_vol: Optional[pd.Series] = None,
    ) -> pd.DataFrame:
        """
        Compute the 4-component VIX composite for each week.

        Parameters
        ----------
        weekly_vix : pd.Series
            Weekly VIX closing levels, indexed by date
        weekly_realized_vol : pd.Series, optional
            Weekly realized vol (%) for fear premium component.
            If None, this component defaults to neutral (0.5).

        Returns
        -------
        DataFrame with columns:
            vix, level_score, mom_score, ma_score, fear_score,
            composite_score, vix_regime, position_multiplier
        """
        vix = weekly_vix.copy()
        result = pd.DataFrame(index=vix.index)
        result["vix"] = vix

        # ── Component 1: VIX Level ──────────────────────────────────────────
        level_info = vix.apply(lambda v: classify_vix_level(v))
        result["vix_regime"] = level_info.apply(lambda x: x[0])
        result["level_score"] = level_info.apply(lambda x: x[1])

        # ── Component 2: VIX Momentum (4-week ROC, inverted) ────────────────
        # Rising VIX = danger → lower score
        vix_roc = vix.pct_change(self.mom_period)
        # Map: -50% or lower change → 1.0; +100% or higher → 0.0
        mom_raw = 1.0 - (vix_roc.clip(-0.5, 1.0) + 0.5) / 1.5
        result["mom_score"] = mom_raw.clip(0.0, 1.0).fillna(0.5)

        # ── Component 3: VIX vs Structural MA ────────────────────────────────
        # VIX below long-run MA = benign structural regime
        vix_ma = vix.rolling(self.vix_ma_period, min_periods=13).mean()
        # VIX/MA ratio: 0.6→ score 1.0, 1.0 → 0.75, 1.5 → 0.30, 2.0 → 0.0
        ma_ratio = vix / vix_ma
        ma_score = (2.0 - ma_ratio).clip(0.0, 1.0) / 1.0  # linear: 1.0 at ratio=1, 0.0 at ratio=2
        ma_score = ma_score.clip(0.0, 1.0)
        result["ma_score"] = ma_score.fillna(0.5)

        # ── Component 4: Fear Premium (VIX - Realized Vol) ───────────────────
        # Large positive spread = fear > realized = mean-reverting opportunity (bullish)
        # Large negative spread = complacency (bearish)
        if weekly_realized_vol is not None:
            rv_aligned = weekly_realized_vol.reindex(vix.index).ffill()
            fear_spread = vix - rv_aligned
            # Normalize: spread > +5 → 1.0, spread < -5 → 0.0, 0 spread → 0.5
            fear_score = (fear_spread / 10.0 + 0.5).clip(0.0, 1.0)
        else:
            fear_score = pd.Series(0.5, index=vix.index)
        result["fear_score"] = fear_score.fillna(0.5)

        # ── Composite Weighted Score ─────────────────────────────────────────
        result["composite_score"] = (
            self.w_level * result["level_score"]
            + self.w_mom * result["mom_score"]
            + self.w_ma * result["ma_score"]
            + self.w_fear * result["fear_score"]
        )

        # ── Position Multiplier ───────────────────────────────────────────────
        # Aligned with jarvis-trader VIX overlay position sizing
        def score_to_multiplier(row) -> float:
            # Hard override: EXTREME VIX level = zero
            if row["vix_regime"] == "EXTREME":
                return 0.0
            score = row["composite_score"]
            if score >= 0.60:
                return 1.00   # Full risk-on
            elif score >= 0.45:
                return 0.85   # Mild caution
            elif score >= 0.35:
                return 0.65   # Moderate caution
            elif score >= 0.20:
                return 0.40   # Significant caution
            else:
                return 0.0    # Risk-off: cash

        result["position_multiplier"] = result.apply(score_to_multiplier, axis=1)

        # ── Composite Regime Label ─────────────────────────────────────────────
        # Derived from the composite score (all 4 components), NOT the raw VIX level.
        # This is what drives the actual position multiplier decision.
        # Distinct from vix_regime which is purely the VIX level band.
        def score_to_composite_regime(score: float) -> str:
            if score >= 0.60:
                return "RISK_ON"
            elif score >= 0.45:
                return "MILD_CAUTION"
            elif score >= 0.35:
                return "MODERATE_CAUTION"
            elif score >= 0.20:
                return "SIGNIFICANT_CAUTION"
            else:
                return "RISK_OFF"

        result["composite_regime"] = result["composite_score"].apply(score_to_composite_regime)
        # Mirror the position_multiplier hard override: EXTREME VIX is fully risk-off.
        result.loc[result["vix_regime"] == "EXTREME", "composite_regime"] = "RISK_OFF"

        return result

    def get_current_signal(
        self,
        weekly_vix: pd.Series,
        weekly_realized_vol: Optional[pd.Series] = None,
    ) -> dict:
        """
        Get the latest composite signal for live use.

        Returns dict with current VIX regime, score, and position multiplier.
        """
        df = self.compute(weekly_vix, weekly_realized_vol)
        last = df.iloc[-1]
        vix_val = round(float(last["vix"]), 2)
        rv = weekly_realized_vol.reindex(df.index).ffill().iloc[-1] if weekly_realized_vol is not None else None
        fear_spread = round(vix_val - float(rv), 2) if rv is not None else None
        fear_context = (
            "implied > realized (fear premium, mean-reverting bullish)" if (fear_spread or 0) > 0
            else "realized > implied (complacency, bearish lean)"
        ) if fear_spread is not None else "no realized vol data"
        return {
            "vix": vix_val,
            # vix_regime = raw VIX level band (CALM/NORMAL/CAUTION/ELEVATED/EXTREME)
            "vix_regime": last["vix_regime"],
            # composite_regime = position decision from all 4 components
            "composite_regime": last["composite_regime"],
            "composite_score": round(float(last["composite_score"]), 4),
            "position_multiplier": round(float(last["position_multiplier"]), 4),
            "level_score": round(float(last["level_score"]), 4),
            "mom_score": round(float(last["mom_score"]), 4),
            "ma_score": round(float(last["ma_score"]), 4),
            "fear_score": round(float(last["fear_score"]), 4),
            "fear_spread": fear_spread,
            "fear_context": fear_context,
            "date": str(df.index[-1].date()),
        }
