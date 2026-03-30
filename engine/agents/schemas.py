"""
JARVIS TRADER — Inter-Agent Communication Schemas
Typed dataclasses for the 5-stage trading pipeline.

Pipeline:
  Stage 1 (Analyze): TechnicalAnalyst, NewsAnalyst, SocialAnalyst, FundamentalAnalyst
  Stage 2 (Debate): BullResearcher, BearResearcher → Debate
  Stage 3 (Trade): Trader
  Stage 4 (Risk): RiskManager
  Stage 5 (Fund): FundManager
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any


# ── Enums ─────────────────────────────────────────────────────────────────────

class Action(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    CLOSE = "CLOSE"
    REDUCE = "REDUCE"


class OrderType(Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


class MarketRegime(Enum):
    TRENDING_BULL = "TRENDING_BULL"
    TRENDING_BEAR = "TRENDING_BEAR"
    RANGE_BOUND = "RANGE_BOUND"
    COMPRESSION = "COMPRESSION"
    EXHAUSTED = "EXHAUSTED"
    UNKNOWN = "UNKNOWN"


class TrendDirection(Enum):
    STRONG_BULL = "STRONG_BULL"
    LEAN_BULL = "LEAN_BULL"
    NEUTRAL = "NEUTRAL"
    LEAN_BEAR = "LEAN_BEAR"
    STRONG_BEAR = "STRONG_BEAR"


class EntrySignal(Enum):
    ENTRY_NOW = "ENTRY_NOW"
    WAIT_FOR_PULLBACK = "WAIT_FOR_PULLBACK"
    FADE_EXTREME = "FADE_EXTREME"
    NO_TRADE = "NO_TRADE"


# ── Sub-Components ─────────────────────────────────────────────────────────────

@dataclass
class ATRLevels:
    """ATR-Fibonacci levels from Saty ATR Levels script."""
    atr_value: float = 0.0
    prior_close: float = 0.0
    trigger_up: float = 0.0    # prior_close + 0.236 * atr
    trigger_down: float = 0.0  # prior_close - 0.236 * atr
    levels_up: Dict[str, float] = field(default_factory=dict)   # "0.382": price, etc.
    levels_down: Dict[str, float] = field(default_factory=dict)
    range_consumed_pct: float = 0.0  # 0-100+
    ema_8: float = 0.0
    ema_21: float = 0.0
    ema_34: float = 0.0
    ema_trend: str = "neutral"  # "bullish"/"bearish"/"neutral"

    def to_dict(self) -> dict:
        return {
            "atr_value": self.atr_value,
            "prior_close": self.prior_close,
            "trigger_up": self.trigger_up,
            "trigger_down": self.trigger_down,
            "levels_up": self.levels_up,
            "levels_down": self.levels_down,
            "range_consumed_pct": self.range_consumed_pct,
            "ema_8": self.ema_8,
            "ema_21": self.ema_21,
            "ema_34": self.ema_34,
            "ema_trend": self.ema_trend,
        }


@dataclass
class IBLevels:
    """Initial Balance levels from Corey IBv1 script."""
    ib_high: float = 0.0
    ib_low: float = 0.0
    ib_range: float = 0.0
    quad_25: float = 0.0
    quad_50: float = 0.0
    quad_75: float = 0.0
    ext_50_up: float = 0.0
    ext_100_up: float = 0.0
    ext_300_up: float = 0.0
    ext_50_down: float = 0.0
    ext_100_down: float = 0.0
    ext_300_down: float = 0.0
    current_price_vs_ib: str = "inside"  # "above"/"below"/"inside"

    def to_dict(self) -> dict:
        return {
            "ib_high": self.ib_high,
            "ib_low": self.ib_low,
            "ib_range": self.ib_range,
            "quad_25": self.quad_25,
            "quad_50": self.quad_50,
            "quad_75": self.quad_75,
            "ext_50_up": self.ext_50_up,
            "ext_100_up": self.ext_100_up,
            "ext_300_up": self.ext_300_up,
            "ext_50_down": self.ext_50_down,
            "ext_100_down": self.ext_100_down,
            "ext_300_down": self.ext_300_down,
            "current_price_vs_ib": self.current_price_vs_ib,
        }


@dataclass
class TPOData:
    """Volume/Time Profile data."""
    poc: float = 0.0
    vah: float = 0.0
    val: float = 0.0
    profile_high: float = 0.0
    profile_low: float = 0.0
    va_balance: float = 0.0
    imbalance: str = "balanced"  # "bullish"/"bearish"/"balanced"
    tpo_score: float = 0.0       # -5 to +5 composite
    vpoc_levels: List[float] = field(default_factory=list)
    price_location: str = "in_va"  # "above_vah"/"in_va"/"below_val"

    def to_dict(self) -> dict:
        return {
            "poc": self.poc,
            "vah": self.vah,
            "val": self.val,
            "profile_high": self.profile_high,
            "profile_low": self.profile_low,
            "va_balance": self.va_balance,
            "imbalance": self.imbalance,
            "tpo_score": self.tpo_score,
            "vpoc_levels": self.vpoc_levels,
            "price_location": self.price_location,
        }


@dataclass
class KeltnerBands:
    """Multi-timeframe Keltner Channel data."""
    timeframe: str = "5m"
    basis: float = 0.0
    inner_upper: float = 0.0   # +1.5x ATR
    inner_lower: float = 0.0
    outer_upper: float = 0.0   # +2.0x ATR
    outer_lower: float = 0.0
    extreme_upper: float = 0.0  # +3.0x ATR
    extreme_lower: float = 0.0
    macd_closed_door_up: bool = False
    macd_closed_door_down: bool = False

    def to_dict(self) -> dict:
        return {
            "timeframe": self.timeframe,
            "basis": self.basis,
            "inner_upper": self.inner_upper,
            "inner_lower": self.inner_lower,
            "outer_upper": self.outer_upper,
            "outer_lower": self.outer_lower,
            "extreme_upper": self.extreme_upper,
            "extreme_lower": self.extreme_lower,
            "macd_closed_door_up": self.macd_closed_door_up,
            "macd_closed_door_down": self.macd_closed_door_down,
        }


@dataclass
class MomentumSignals:
    """All momentum indicator readings."""
    stc_value: float = 50.0
    stc_signal: str = "neutral"  # "oversold"/"overbought"/"rising"/"falling"/"neutral"
    phase_value: float = 0.0
    phase_signal: str = "neutral"  # "compression"/"extended_up"/"extended_down"/"neutral"
    kama_value: float = 0.0
    kama_signal: str = "neutral"  # "long"/"short"/"neutral"
    volume_buy_pct: float = 50.0
    volume_sell_pct: float = 50.0
    volume_signal: str = "balanced"  # "buyer_dominant"/"seller_dominant"/"balanced"
    trin: Optional[float] = None
    vix: Optional[float] = None
    breadth_signal: str = "neutral"  # "capitulation"/"blow_off"/"neutral"

    def to_dict(self) -> dict:
        return {
            "stc_value": self.stc_value,
            "stc_signal": self.stc_signal,
            "phase_value": self.phase_value,
            "phase_signal": self.phase_signal,
            "kama_value": self.kama_value,
            "kama_signal": self.kama_signal,
            "volume_buy_pct": self.volume_buy_pct,
            "volume_sell_pct": self.volume_sell_pct,
            "volume_signal": self.volume_signal,
            "trin": self.trin,
            "vix": self.vix,
            "breadth_signal": self.breadth_signal,
        }


# ── Stage 1 Outputs ────────────────────────────────────────────────────────────

@dataclass
class TechnicalReport:
    """Output of TechnicalAnalyst agent (Stage 1)."""
    symbol: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    timeframe: str = "1d"
    current_price: float = 0.0
    regime: MarketRegime = MarketRegime.UNKNOWN
    trend: TrendDirection = TrendDirection.NEUTRAL
    entry_signal: EntrySignal = EntrySignal.NO_TRADE
    atr_levels: ATRLevels = field(default_factory=ATRLevels)
    ib_levels: IBLevels = field(default_factory=IBLevels)
    tpo_data: TPOData = field(default_factory=TPOData)
    keltner_5m: KeltnerBands = field(default_factory=lambda: KeltnerBands(timeframe="5m"))
    keltner_15m: KeltnerBands = field(default_factory=lambda: KeltnerBands(timeframe="15m"))
    keltner_30m: KeltnerBands = field(default_factory=lambda: KeltnerBands(timeframe="30m"))
    keltner_4h: KeltnerBands = field(default_factory=lambda: KeltnerBands(timeframe="4h"))
    momentum: MomentumSignals = field(default_factory=MomentumSignals)
    key_support: List[float] = field(default_factory=list)
    key_resistance: List[float] = field(default_factory=list)
    stop_level: float = 0.0
    target_1: float = 0.0
    target_2: float = 0.0
    target_3: float = 0.0
    confidence: float = 0.0
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "timeframe": self.timeframe,
            "current_price": self.current_price,
            "regime": self.regime.value,
            "trend": self.trend.value,
            "entry_signal": self.entry_signal.value,
            "atr_levels": self.atr_levels.to_dict(),
            "ib_levels": self.ib_levels.to_dict(),
            "tpo_data": self.tpo_data.to_dict(),
            "keltner_5m": self.keltner_5m.to_dict(),
            "keltner_15m": self.keltner_15m.to_dict(),
            "keltner_30m": self.keltner_30m.to_dict(),
            "keltner_4h": self.keltner_4h.to_dict(),
            "momentum": self.momentum.to_dict(),
            "key_support": self.key_support,
            "key_resistance": self.key_resistance,
            "stop_level": self.stop_level,
            "target_1": self.target_1,
            "target_2": self.target_2,
            "target_3": self.target_3,
            "confidence": self.confidence,
            "notes": self.notes,
        }


@dataclass
class NewsReport:
    """Output of NewsAnalyst agent (Stage 1)."""
    symbol: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    sentiment: str = "neutral"
    sentiment_score: float = 0.0  # -1 to +1
    key_headlines: List[str] = field(default_factory=list)
    macro_events: List[str] = field(default_factory=list)
    risk_events: List[str] = field(default_factory=list)
    confidence: float = 0.0
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "sentiment": self.sentiment,
            "sentiment_score": self.sentiment_score,
            "key_headlines": self.key_headlines,
            "macro_events": self.macro_events,
            "risk_events": self.risk_events,
            "confidence": self.confidence,
            "notes": self.notes,
        }


@dataclass
class SocialReport:
    """Output of SocialAnalyst agent (Stage 1)."""
    symbol: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    options_flow: str = "neutral"  # "bullish_sweep"/"bearish_sweep"/"neutral"
    put_call_ratio: Optional[float] = None
    dark_pool_activity: str = "neutral"  # "buying"/"selling"/"neutral"
    sentiment_score: float = 0.0  # -1 to +1
    confidence: float = 0.0
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "options_flow": self.options_flow,
            "put_call_ratio": self.put_call_ratio,
            "dark_pool_activity": self.dark_pool_activity,
            "sentiment_score": self.sentiment_score,
            "confidence": self.confidence,
            "notes": self.notes,
        }


@dataclass
class FundamentalReport:
    """Output of FundamentalAnalyst agent (Stage 1)."""
    symbol: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    earnings_date: Optional[str] = None
    economic_events: List[str] = field(default_factory=list)
    sector_strength: str = "neutral"  # "strong"/"weak"/"neutral"
    macro_bias: str = "neutral"       # "bullish"/"bearish"/"neutral"
    confidence: float = 0.0
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "earnings_date": self.earnings_date,
            "economic_events": self.economic_events,
            "sector_strength": self.sector_strength,
            "macro_bias": self.macro_bias,
            "confidence": self.confidence,
            "notes": self.notes,
        }


# ── Stage 2 Outputs ────────────────────────────────────────────────────────────

@dataclass
class ResearchCase:
    """Output of Bull/Bear Researcher agents (Stage 2)."""
    symbol: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    direction: str = "bull"  # "bull"/"bear"
    thesis: str = ""
    technical_signals: List[str] = field(default_factory=list)
    news_signals: List[str] = field(default_factory=list)
    risk_factors: List[str] = field(default_factory=list)
    price_target: float = 0.0
    stop_level: float = 0.0
    confidence: float = 0.0
    signal_count: int = 0  # how many of 5 layers align

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "direction": self.direction,
            "thesis": self.thesis,
            "technical_signals": self.technical_signals,
            "news_signals": self.news_signals,
            "risk_factors": self.risk_factors,
            "price_target": self.price_target,
            "stop_level": self.stop_level,
            "confidence": self.confidence,
            "signal_count": self.signal_count,
        }


@dataclass
class DebateResult:
    """Output of Debate agent (Stage 2)."""
    symbol: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    bull_score: float = 0.0  # 0-10
    bear_score: float = 0.0  # 0-10
    winner: str = "neutral"  # "bull"/"bear"/"neutral"
    margin: float = 0.0
    consensus_direction: TrendDirection = TrendDirection.NEUTRAL
    key_bull_points: List[str] = field(default_factory=list)
    key_bear_points: List[str] = field(default_factory=list)
    recommended_action: Action = Action.HOLD
    conviction: float = 0.0  # 0-1
    rationale: str = ""

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "bull_score": self.bull_score,
            "bear_score": self.bear_score,
            "winner": self.winner,
            "margin": self.margin,
            "consensus_direction": self.consensus_direction.value,
            "key_bull_points": self.key_bull_points,
            "key_bear_points": self.key_bear_points,
            "recommended_action": self.recommended_action.value,
            "conviction": self.conviction,
            "rationale": self.rationale,
        }


# ── Stage 3 Output ─────────────────────────────────────────────────────────────

@dataclass
class TradeDecision:
    """Output of Trader agent (Stage 3)."""
    symbol: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    action: Action = Action.HOLD
    order_type: OrderType = OrderType.LIMIT
    entry_price: float = 0.0
    stop_price: float = 0.0
    target_1: float = 0.0
    target_2: float = 0.0
    target_3: float = 0.0
    risk_reward: float = 0.0
    suggested_contracts: int = 1
    timeframe: str = "intraday"
    entry_signal_basis: str = ""  # which Layer 4 signal triggered
    conviction: float = 0.0
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "action": self.action.value,
            "order_type": self.order_type.value,
            "entry_price": self.entry_price,
            "stop_price": self.stop_price,
            "target_1": self.target_1,
            "target_2": self.target_2,
            "target_3": self.target_3,
            "risk_reward": self.risk_reward,
            "suggested_contracts": self.suggested_contracts,
            "timeframe": self.timeframe,
            "entry_signal_basis": self.entry_signal_basis,
            "conviction": self.conviction,
            "notes": self.notes,
        }


# ── Stage 4 Output ─────────────────────────────────────────────────────────────

@dataclass
class RiskDecision:
    """Output of RiskManager agent (Stage 4)."""
    symbol: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    approved: bool = False
    modified: bool = False
    original_action: Action = Action.HOLD
    approved_action: Action = Action.HOLD
    approved_contracts: int = 0
    approved_stop: float = 0.0
    approved_target_1: float = 0.0
    max_daily_loss_remaining: float = 0.0
    current_drawdown_pct: float = 0.0
    kill_switch_triggered: bool = False
    rejection_reason: Optional[str] = None
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "approved": self.approved,
            "modified": self.modified,
            "original_action": self.original_action.value,
            "approved_action": self.approved_action.value,
            "approved_contracts": self.approved_contracts,
            "approved_stop": self.approved_stop,
            "approved_target_1": self.approved_target_1,
            "max_daily_loss_remaining": self.max_daily_loss_remaining,
            "current_drawdown_pct": self.current_drawdown_pct,
            "kill_switch_triggered": self.kill_switch_triggered,
            "rejection_reason": self.rejection_reason,
            "notes": self.notes,
        }


# ── Stage 5 Output ─────────────────────────────────────────────────────────────

@dataclass
class FundDecision:
    """Output of FundManager agent (Stage 5 — final go/no-go)."""
    symbol: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    execute: bool = False
    action: Action = Action.HOLD
    contracts: int = 0
    entry_price: float = 0.0
    stop_price: float = 0.0
    target_1: float = 0.0
    target_2: float = 0.0
    portfolio_weight_pct: float = 0.0
    correlation_check: str = "ok"  # "ok"/"correlated"/"rejected"
    final_conviction: float = 0.0
    execution_notes: str = ""
    human_approval_required: bool = True

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "execute": self.execute,
            "action": self.action.value,
            "contracts": self.contracts,
            "entry_price": self.entry_price,
            "stop_price": self.stop_price,
            "target_1": self.target_1,
            "target_2": self.target_2,
            "portfolio_weight_pct": self.portfolio_weight_pct,
            "correlation_check": self.correlation_check,
            "final_conviction": self.final_conviction,
            "execution_notes": self.execution_notes,
            "human_approval_required": self.human_approval_required,
        }


# ── Helper Functions ───────────────────────────────────────────────────────────

def pipeline_summary(fund_decision: FundDecision) -> str:
    """Return a one-line human-readable summary of the final decision."""
    if not fund_decision.execute:
        return f"[NO TRADE] {fund_decision.symbol} — {fund_decision.execution_notes[:80]}"

    direction = "LONG" if fund_decision.action == Action.BUY else "SHORT"
    approval = "⚠️ NEEDS APPROVAL" if fund_decision.human_approval_required else "✅ AUTO"
    return (
        f"[{approval}] {direction} {fund_decision.contracts}x {fund_decision.symbol} "
        f"@ {fund_decision.entry_price:.2f} | Stop: {fund_decision.stop_price:.2f} | "
        f"T1: {fund_decision.target_1:.2f} | Conviction: {fund_decision.final_conviction:.0%}"
    )
