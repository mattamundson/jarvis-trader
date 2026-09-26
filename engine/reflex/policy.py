"""
JARVIS TRADER -- Reflex policy (deterministic gates + sizing)
=============================================================
Reads a :class:`~reflex.schema.ReflexDecision` plus the code-computed
:class:`~reflex.state.MarketSnapshot` and returns a :class:`PolicyOutcome`.

This is pure, synchronous Python with no I/O and no LLM path. The judge can
only make the outcome *more* conservative:

* ``risk_state`` is computed here from the snapshot; the judge's value is
  combined with :func:`~reflex.schema.more_conservative`, so a judge saying
  "safe" while the account is near a limit changes nothing.
* Size comes from fractional Kelly on the *calibrated* probability and a
  reward/risk ratio supplied by code (stop/target geometry), never by the
  judge. Without a calibrator the size is capped at one contract -- Kelly on
  a raw LLM confidence is sizing on an unmeasured number.

The outcome is an INTENT, not an order. It is not wired into order routing;
anything that eventually consumes it must still pass ``risk/safety_layer.py``
(kill switch, daily-loss halt, drawdown halt, contract caps), which remains
the sole authority on whether an order may exist.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

from reflex.schema import Direction, ReflexDecision, Regime, RiskState, more_conservative
from reflex.state import MarketSnapshot
from risk.position_sizer import drawdown_scale_factor

__all__ = ["Action", "ReflexLimits", "PolicyConfig", "PolicyOutcome", "code_risk_state", "evaluate"]

Calibrator = Callable[[float], float]
MAX_KELLY_MULTIPLIER = 0.25  # quarter Kelly is the ceiling, not the default target
UNCALIBRATED_MAX_CONTRACTS = 1


class Action(str, Enum):
    FIRE = "fire"  # open a new position (intent only)
    HOLD = "hold"
    REDUCE = "reduce"  # cut existing exposure
    ESCALATE = "escalate"  # hand to the slow path (debate pipeline / advisor); no new risk now


@dataclass(frozen=True)
class ReflexLimits:
    """Account-level limits the policy reads. Fractions, not percents
    (``0.20`` = 20%), matching ``config.TradingConfig``."""

    max_contracts: int
    max_daily_loss_pct: float
    max_drawdown_pct: float
    max_trade_loss_usd: float

    @classmethod
    def from_settings(cls) -> "ReflexLimits":
        from config import settings  # lazy: keeps this module importable without .env

        return cls(
            max_contracts=int(settings.MAX_CONTRACTS_PER_INSTRUMENT),
            max_daily_loss_pct=float(settings.MAX_DAILY_LOSS_PCT),
            max_drawdown_pct=float(settings.MAX_DRAWDOWN_PCT),
            max_trade_loss_usd=float(settings.MAX_TRADE_LOSS_USD),
        )


@dataclass(frozen=True)
class PolicyConfig:
    min_setup_quality: int = 2
    min_confidence: float = 0.80  # strict: must be ABOVE this
    escalate_below: float = 0.60
    kelly_multiplier: float = MAX_KELLY_MULTIPLIER
    near_limit_ratio: float = 0.50  # share of any account limit consumed -> near_limit
    reduce_ratio: float = 0.75  # share consumed -> reduce
    max_quote_age_s: float = 5.0

    def __post_init__(self) -> None:
        if not 0.0 < self.kelly_multiplier <= MAX_KELLY_MULTIPLIER:
            raise ValueError(f"kelly_multiplier must be in (0, {MAX_KELLY_MULTIPLIER}]")
        if not 0.0 <= self.escalate_below < self.min_confidence <= 1.0:
            raise ValueError("require 0 <= escalate_below < min_confidence <= 1")
        if not 0.0 < self.near_limit_ratio < self.reduce_ratio <= 1.0:
            raise ValueError("require 0 < near_limit_ratio < reduce_ratio <= 1")


DEFAULT_POLICY_CONFIG = PolicyConfig()


@dataclass(frozen=True)
class PolicyOutcome:
    action: Action
    side: Direction = Direction.NEUTRAL
    contracts: int = 0
    reasons: tuple = field(default_factory=tuple)
    risk_state: RiskState = RiskState.SAFE
    p_used: Optional[float] = None
    calibrated: bool = False
    kelly_full: Optional[float] = None
    kelly_applied: Optional[float] = None


def code_risk_state(snap: MarketSnapshot, limits: ReflexLimits, cfg: PolicyConfig) -> RiskState:
    """Risk state from account numbers alone -- the judge cannot lower this."""
    dd_used = (snap.drawdown_pct / 100.0) / limits.max_drawdown_pct if limits.max_drawdown_pct > 0 else 1.0
    day_loss = max(0.0, -snap.daily_pnl_pct / 100.0)
    day_used = day_loss / limits.max_daily_loss_pct if limits.max_daily_loss_pct > 0 else 1.0
    used = max(dd_used, day_used)
    if used >= cfg.reduce_ratio:
        return RiskState.REDUCE
    if used >= cfg.near_limit_ratio:
        return RiskState.NEAR_LIMIT
    return RiskState.SAFE


def _entry_blockers(d: ReflexDecision, snap: MarketSnapshot, risk: RiskState, cfg: PolicyConfig) -> list[str]:
    reasons = []
    if d.direction == Direction.NEUTRAL:
        reasons.append("direction_neutral")
    if d.toxic_flow:
        reasons.append("toxic_flow")
    if d.setup_quality < cfg.min_setup_quality:
        reasons.append(f"setup_quality<{cfg.min_setup_quality}")
    if d.direction_confidence <= cfg.min_confidence:
        reasons.append(f"confidence<={cfg.min_confidence}")
    if risk != RiskState.SAFE:
        reasons.append(f"risk_state={risk.value}")
    if snap.quote_age_s is not None and snap.quote_age_s > cfg.max_quote_age_s:
        reasons.append("stale_quote")
    if snap.position != 0:
        reasons.append("position_open")  # exits/pyramiding are owned by the trade manager, not the reflex
    return reasons


def _size(
    p: float, reward_risk: float, equity: float, risk_per_contract_usd: float, drawdown_pct: float,
    limits: ReflexLimits, cfg: PolicyConfig, calibrated: bool,
) -> tuple[int, float, float, list[str]]:
    """Fractional Kelly -> dollar risk -> contracts, clamped by every cap."""
    q = 1.0 - p
    kelly_full = (reward_risk * p - q) / reward_risk
    if kelly_full <= 0:
        return 0, kelly_full, 0.0, ["no_edge_after_calibration"]
    kelly_applied = kelly_full * cfg.kelly_multiplier
    dollar_risk = equity * kelly_applied * drawdown_scale_factor(drawdown_pct)
    dollar_risk = min(dollar_risk, limits.max_trade_loss_usd)
    contracts = math.floor(dollar_risk / risk_per_contract_usd)
    notes = []
    if not calibrated and contracts > UNCALIBRATED_MAX_CONTRACTS:
        contracts = UNCALIBRATED_MAX_CONTRACTS
        notes.append("uncalibrated_capped_to_1")
    contracts = min(contracts, limits.max_contracts)
    if contracts <= 0:
        notes.append("size_rounds_to_zero")
    return contracts, kelly_full, kelly_applied, notes


def evaluate(
    decision: Optional[ReflexDecision],
    snap: MarketSnapshot,
    limits: ReflexLimits,
    equity: float,
    reward_risk: float,
    risk_per_contract_usd: float,
    calibrator: Optional[Calibrator] = None,
    cfg: Optional[PolicyConfig] = None,
) -> PolicyOutcome:
    """Gate + size one decision. Order of precedence: invalid -> risk reduce ->
    escalate -> entry gates -> sizing. Never raises on judge content."""
    cfg = cfg or DEFAULT_POLICY_CONFIG
    if decision is None:
        return PolicyOutcome(Action.HOLD, reasons=("no_valid_decision",))
    if reward_risk <= 0 or risk_per_contract_usd <= 0 or equity <= 0:
        return PolicyOutcome(Action.HOLD, reasons=("invalid_sizing_inputs",))

    risk = more_conservative(code_risk_state(snap, limits, cfg), decision.risk_state)
    if risk == RiskState.REDUCE:
        action = Action.REDUCE if snap.position != 0 else Action.HOLD
        return PolicyOutcome(action, reasons=("risk_state=reduce",), risk_state=risk)
    # A neutral read at low confidence is "no opinion" (HOLD), not a hard case;
    # escalating it would page the slow path on every quiet bar.
    weak_call = decision.direction != Direction.NEUTRAL and decision.direction_confidence < cfg.escalate_below
    if decision.regime == Regime.CRISIS or weak_call:
        why = "regime=crisis" if decision.regime == Regime.CRISIS else f"confidence<{cfg.escalate_below}"
        return PolicyOutcome(Action.ESCALATE, reasons=(why,), risk_state=risk)

    blockers = _entry_blockers(decision, snap, risk, cfg)
    if blockers:
        return PolicyOutcome(Action.HOLD, reasons=tuple(blockers), risk_state=risk)

    calibrated = calibrator is not None
    p = float(calibrator(decision.direction_confidence)) if calibrated else decision.direction_confidence
    if not math.isfinite(p):
        # min/max clamping would turn NaN into 1.0 (full Kelly) -- fail closed instead.
        return PolicyOutcome(Action.HOLD, reasons=("invalid_calibrated_probability",), risk_state=risk)
    p = max(0.0, min(1.0, p))
    contracts, k_full, k_applied, notes = _size(
        p, reward_risk, equity, risk_per_contract_usd, snap.drawdown_pct, limits, cfg, calibrated
    )
    action = Action.FIRE if contracts > 0 else Action.HOLD
    return PolicyOutcome(
        action,
        side=decision.direction if contracts > 0 else Direction.NEUTRAL,
        contracts=contracts,
        reasons=tuple(notes),
        risk_state=risk,
        p_used=p,
        calibrated=calibrated,
        kelly_full=k_full,
        kelly_applied=k_applied,
    )
