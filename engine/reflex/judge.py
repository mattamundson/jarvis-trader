"""
JARVIS TRADER -- Reflex judges
==============================
A judge maps a :class:`~reflex.state.MarketSnapshot` to a
:class:`~reflex.schema.ReflexDecision`. Two pieces live here:

* :class:`RuleBasedJudge` -- a deterministic baseline built only from the
  snapshot. It exists so the reflex loop runs and can be evaluated end to end
  with no model in the path, and so any model-backed judge has a benchmark it
  must beat on out-of-sample Brier and net P&L before it is trusted. Its
  thresholds are placeholders, not fitted values; its confidences are
  UNCALIBRATED by construction.
* :func:`build_judge_prompt` -- the system/user text for a model-backed judge,
  with the decision JSON schema embedded. Any reply must go back through
  :func:`reflex.schema.parse_decision`, which fails closed.
"""

from __future__ import annotations

import json
import math
from typing import Optional, Protocol

from reflex.schema import MAX_SETUP_QUALITY, Direction, ReflexDecision, Regime, RiskState
from reflex.state import DEFAULT_MOMENTUM_WINDOW, MarketSnapshot

__all__ = ["ReflexJudge", "RuleBasedJudge", "build_judge_prompt"]


class ReflexJudge(Protocol):
    async def judge(self, snap: MarketSnapshot) -> Optional[ReflexDecision]: ...


def _momentum_z(snap: MarketSnapshot, window: int) -> float:
    """Momentum over the window in units of the window's expected random-walk
    move (rv * sqrt(n)). ~0 = noise, |z| >= 2 = unusual drift."""
    denom = snap.rv_bps * math.sqrt(max(1, window))
    return snap.momentum_bps / denom if denom > 0 else 0.0


def _sign(x: float) -> Direction:
    return Direction.LONG if x > 0 else Direction.SHORT if x < 0 else Direction.NEUTRAL


class RuleBasedJudge:
    """Deterministic baseline. Defaults are [placeholder] values for a liquid
    index micro on 5-minute bars and must be re-fit per instrument/timeframe."""

    def __init__(
        self,
        high_vol_rv_bps: float = 25.0,
        crisis_rv_bps: float = 60.0,
        trend_z: float = 1.5,
        fade_z: float = 2.5,
        toxic_spread_bps: float = 5.0,
        toxic_imbalance: float = 0.8,
        momentum_window: int = DEFAULT_MOMENTUM_WINDOW,
    ) -> None:
        self.high_vol_rv_bps = high_vol_rv_bps
        self.crisis_rv_bps = crisis_rv_bps
        self.trend_z = trend_z
        self.fade_z = fade_z
        self.toxic_spread_bps = toxic_spread_bps
        self.toxic_imbalance = toxic_imbalance
        self.momentum_window = momentum_window

    def _regime(self, snap: MarketSnapshot, z: float) -> Regime:
        if snap.rv_bps >= self.crisis_rv_bps:
            return Regime.CRISIS
        if snap.rv_bps >= self.high_vol_rv_bps:
            return Regime.HIGH_VOL
        return Regime.TRENDING if abs(z) >= self.trend_z else Regime.MEAN_REVERTING

    def _direction(self, regime: Regime, z: float) -> Direction:
        if regime == Regime.TRENDING:
            return _sign(z)
        if regime == Regime.MEAN_REVERTING and abs(z) >= self.fade_z:
            return _sign(-z)
        return Direction.NEUTRAL

    def _toxic(self, snap: MarketSnapshot, direction: Direction) -> bool:
        if snap.spread_bps is not None and snap.spread_bps > self.toxic_spread_bps:
            return True
        if snap.imbalance is None or direction == Direction.NEUTRAL:
            return False
        against = -snap.imbalance if direction == Direction.LONG else snap.imbalance
        return against >= self.toxic_imbalance

    def _quality(self, snap: MarketSnapshot, direction: Direction, z: float) -> int:
        if direction == Direction.NEUTRAL:
            return 0
        score = 1 if abs(z) >= self.trend_z else 0
        if snap.imbalance is not None:
            with_dir = snap.imbalance if direction == Direction.LONG else -snap.imbalance
            score += 1 if with_dir > 0.2 else 0
        if snap.spread_bps is not None and snap.spread_bps <= self.toxic_spread_bps / 2:
            score += 1
        return min(score, MAX_SETUP_QUALITY)

    async def judge(self, snap: MarketSnapshot) -> Optional[ReflexDecision]:
        z = _momentum_z(snap, self.momentum_window)
        regime = self._regime(snap, z)
        direction = self._direction(regime, z)
        # Logistic in |z|, bounded to [0.5, 0.95]. A heuristic, not a probability.
        conf = 0.5 if direction == Direction.NEUTRAL else min(0.95, 1.0 / (1.0 + math.exp(-abs(z))))
        return ReflexDecision(
            regime=regime,
            direction=direction,
            direction_confidence=round(conf, 4),
            toxic_flow=self._toxic(snap, direction),
            setup_quality=self._quality(snap, direction, z),
            risk_state=RiskState.SAFE,  # the policy computes the real risk state from the account
            rationale=f"rule_based z={z:.2f} rv_bps={snap.rv_bps:.1f}",
        )


_SYSTEM_PROMPT = (
    "You are a per-bar market judge. You see one numeric state snapshot and "
    "return ONE JSON object matching the schema. You do not size, price, or "
    "place orders; code does that. direction_confidence is your probability "
    "that the direction is right over the next bar horizon -- it is scored with "
    "a Brier score, so overconfidence is penalized. If unsure, return neutral "
    "with low confidence. Output JSON only, no prose.\n\nSchema:\n"
)


def build_judge_prompt(snap: MarketSnapshot) -> tuple[str, str]:
    """Return ``(system, user)`` text for a model-backed judge."""
    schema = json.dumps(ReflexDecision.model_json_schema(), separators=(",", ":"))
    return _SYSTEM_PROMPT + schema, snap.to_prompt_json()
