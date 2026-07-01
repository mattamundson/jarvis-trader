"""
Jarvis-Trader Signal Alert Schema — v1
Pydantic models for typed, versioned alert objects.
All downstream modules (scorer, IB adapter, dashboard) import from here.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class AlertTier(str, Enum):
    A_PLUS = "A_PLUS"
    A = "A"
    B = "B"
    C = "C"
    BLOCKED = "BLOCKED"


class AlertSide(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class ExecutionMode(str, Enum):
    BACKTEST = "BACKTEST"
    PAPER = "PAPER"
    LIVE = "LIVE"


class StructurePosition(str, Enum):
    BUYER_CONTROL = "BUYER_CONTROL"
    SELLER_CONTROL = "SELLER_CONTROL"
    NEUTRAL_STRUCTURE = "NEUTRAL_STRUCTURE"


class BiasState(str, Enum):
    STRONG_BULL = "STRONG_BULL"
    LEAN_BULL = "LEAN_BULL"
    STRONG_BEAR = "STRONG_BEAR"
    LEAN_BEAR = "LEAN_BEAR"
    NEUTRAL = "NEUTRAL"


class RegimeState(str, Enum):
    TRENDING_BULL = "TRENDING_BULL"
    TRENDING_BEAR = "TRENDING_BEAR"
    RANGE_BOUND = "RANGE_BOUND"
    EXHAUSTED = "EXHAUSTED"
    COMPRESSION = "COMPRESSION"


# ---------------------------------------------------------------------------
# Context sub-models
# ---------------------------------------------------------------------------

class IBContext(BaseModel):
    """Initial Balance context for the current session."""
    ib_high: Optional[float] = None
    ib_low: Optional[float] = None
    ib_mid: Optional[float] = None
    ib_range: Optional[float] = None
    ib_range_pct: Optional[float] = None
    ib_tier: Optional[Literal["NARROW", "NORMAL", "WIDE"]] = None
    broke_ib_high: bool = False
    broke_ib_low: bool = False
    c_period_confirmed: bool = False
    extension_prob_50: Optional[float] = None   # historical hit-rate for 50% extension
    extension_prob_100: Optional[float] = None  # historical hit-rate for 100% extension


class VWAPContext(BaseModel):
    """Anchored VWAP context at signal bar."""
    vwap: Optional[float] = None
    distance_pct: Optional[float] = None
    zscore: Optional[float] = None
    above_vwap: bool = False
    below_vwap: bool = False


class TrendContext(BaseModel):
    """Multi-timeframe trend indicator snapshot."""
    ema_8: Optional[float] = None
    ema_21: Optional[float] = None
    ema_34: Optional[float] = None
    adx: Optional[float] = None
    roc_10: Optional[float] = None
    stc_value: Optional[float] = None
    kama_value: Optional[float] = None
    trend_state: Optional[str] = None
    momentum_state: Optional[str] = None


class RiskPlan(BaseModel):
    """Position sizing and risk envelope."""
    base_risk_pct: float
    applied_risk_pct: float
    score_risk_multiplier: float
    contracts: int
    notional_risk: float
    max_contracts_allowed: int


class TargetPlan(BaseModel):
    """Entry, stop, and three-tier targets."""
    entry_price: float
    stop_price: float
    target_1: float
    target_2: float
    target_3: float
    stop_distance: float
    reward_to_risk_t1: Optional[float] = None
    reward_to_risk_t2: Optional[float] = None
    reward_to_risk_t3: Optional[float] = None


class ScoreBreakdown(BaseModel):
    """Component scores that sum to the total signal quality score."""
    total: float
    structure: float   # 0-40  IB + VA/VAL + structure position
    trend: float       # 0-30  VWAP, EMA ribbon, ADX
    momentum: float    # 0-20  STC, ROC
    volatility: float  # 0-10  ATR-consumed, regime
    risk_penalty: float = 0.0
    blocked_reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Root alert model
# ---------------------------------------------------------------------------

class JarvisAlertV1(BaseModel):
    """
    Canonical Jarvis-Trader signal alert — schema version jarvis-alert-v1.

    All fields are required unless Optional.  Downstream consumers MUST
    check ``tier != AlertTier.BLOCKED`` before routing to execution.
    """
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["jarvis-alert-v1"] = "jarvis-alert-v1"
    alert_id: str
    created_at: datetime
    run_id: str
    execution_mode: ExecutionMode

    # Instrument
    symbol: str
    timeframe: str
    session_date: str
    side: AlertSide
    tier: AlertTier

    # Market context
    regime: RegimeState
    bias: BiasState
    structure_position: StructurePosition
    raw_entry_signal: str

    # Scored components
    score: ScoreBreakdown
    ib_context: IBContext
    vwap_context: VWAPContext
    trend_context: TrendContext
    targets: TargetPlan
    risk: RiskPlan

    # Metadata
    filters: Dict[str, bool] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


def latest_schema_name() -> str:
    """Return the current canonical schema version string."""
    return "jarvis-alert-v1"
