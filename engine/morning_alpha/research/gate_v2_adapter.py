from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Callable, Sequence

from pydantic import BaseModel, ConfigDict, Field


class PromotionState(StrEnum):
    IDEA = "idea"
    BACKTESTED = "backtested"
    WFO_VALIDATED = "wfo_validated"
    GATE_V2_PASSED = "gate_v2_passed"
    PAPER = "paper"
    FORWARD_VALIDATED = "forward_validated"
    LIVE_ELIGIBLE = "live_eligible"
    DEGRADED = "degraded"
    RETIRED = "retired"


@dataclass(frozen=True)
class MorningAlphaResearchRun:
    strategy_key: str
    total_historical_trades: int
    trade_returns_r: tuple[float, ...]
    oos_results: Sequence[Any]
    n_grid_combos: int
    fixed_params_metrics: dict[str, Any]
    cost_sweep_metrics: dict[str, Any]
    sparse_strategy_approved: bool = False


class PromotionVerdict(BaseModel):
    model_config = ConfigDict(frozen=True)

    strategy_key: str
    state: PromotionState
    gate_invoked: bool
    gate_verdict: str | None = None
    passed_via: str | None = None
    reasons: tuple[str, ...] = ()
    gate_metrics: dict[str, Any] = Field(default_factory=dict)


GateFn = Callable[[list[Any], int, dict, dict], dict]


def _canonical_gate() -> GateFn:
    from backtest.wfo_lifecycle import compute_gate_v2

    return compute_gate_v2


class MorningAlphaGateV2:
    """Promotion adapter around the repository's canonical Gate-v2 implementation."""

    def __init__(self, gate_fn: GateFn | None = None, *, normal_min_trades: int = 200) -> None:
        self.gate_fn = gate_fn or _canonical_gate()
        self.normal_min_trades = normal_min_trades

    def evaluate(self, run: MorningAlphaResearchRun) -> PromotionVerdict:
        reasons: list[str] = []
        if run.total_historical_trades < 0:
            reasons.append("total_historical_trades must be non-negative")
        if len(run.trade_returns_r) != run.total_historical_trades:
            reasons.append("trade_returns_r count must equal total_historical_trades")
        if not run.sparse_strategy_approved and run.total_historical_trades < self.normal_min_trades:
            reasons.append(f"normal setup family requires at least {self.normal_min_trades} historical trades")
        if not run.oos_results:
            reasons.append("OOS results are required before Gate-v2")
        if not run.fixed_params_metrics:
            reasons.append("fixed-parameter metrics are required before Gate-v2")
        if not run.cost_sweep_metrics:
            reasons.append("cost/slippage sweep metrics are required before Gate-v2")
        if run.n_grid_combos < 1:
            reasons.append("n_grid_combos must be >= 1")
        if reasons:
            return PromotionVerdict(strategy_key=run.strategy_key, state=PromotionState.BACKTESTED, gate_invoked=False, reasons=tuple(reasons))
        gate_result = self.gate_fn(list(run.oos_results), run.n_grid_combos, run.fixed_params_metrics, run.cost_sweep_metrics)
        passed = gate_result.get("verdict") == "PASS"
        state = PromotionState.GATE_V2_PASSED if passed else PromotionState.WFO_VALIDATED
        return PromotionVerdict(strategy_key=run.strategy_key, state=state, gate_invoked=True, gate_verdict=gate_result.get("verdict"), passed_via=gate_result.get("passed_via"), reasons=tuple(gate_result.get("reasons", ())), gate_metrics=dict(gate_result))


def advance_promotion_state(state: PromotionState, *, paper_started: bool = False, forward_validated: bool = False, live_approved: bool = False) -> PromotionState:
    """Advance only through explicit post-Gate-v2 evidence; Gate PASS is never live authorization."""
    if state is PromotionState.GATE_V2_PASSED and paper_started:
        return PromotionState.PAPER
    if state is PromotionState.PAPER and forward_validated:
        return PromotionState.FORWARD_VALIDATED
    if state is PromotionState.FORWARD_VALIDATED and live_approved:
        return PromotionState.LIVE_ELIGIBLE
    return state


class ValidationPrerequisite(BaseModel):
    model_config = ConfigDict(frozen=True)
    level: str = Field(pattern=r"^L[6-9]$")
    status: str = Field(min_length=1)
    identity_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class EvidenceGatedGateV2:
    """Require complete L6-L9 evidence before delegating to canonical Gate-v2 adapter."""

    REQUIRED_LEVELS = ("L6", "L7", "L8", "L9")

    def __init__(self, adapter: MorningAlphaGateV2) -> None:
        self.adapter = adapter

    def evaluate(self, run: MorningAlphaResearchRun, evidence: Sequence[ValidationPrerequisite]) -> PromotionVerdict:
        by_level = {row.level: row for row in evidence}
        reasons: list[str] = []
        for level in self.REQUIRED_LEVELS:
            row = by_level.get(level)
            if row is None:
                reasons.append(f"{level} evidence is required before Gate-v2")
            elif row.status != "complete":
                reasons.append(f"{level} evidence status must be complete; got {row.status}")
        identities = {row.identity_hash for row in evidence if row.level in self.REQUIRED_LEVELS}
        if len(identities) > 1:
            reasons.append("L6-L9 validation identity mismatch")
        if reasons:
            return PromotionVerdict(strategy_key=run.strategy_key, state=PromotionState.WFO_VALIDATED, gate_invoked=False, reasons=tuple(reasons))
        return self.adapter.evaluate(run)
