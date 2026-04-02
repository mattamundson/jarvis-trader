"""
MarketModule ABC — Standard interface all market modules must implement.
Each market (futures, options, polymarket, crypto) is a self-contained module.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class MarketStatus(str, Enum):
    OFFLINE = "offline"
    CONNECTING = "connecting"
    PAPER = "paper"
    LIVE = "live"
    HALTED = "halted"
    ERROR = "error"


@dataclass
class Position:
    symbol: str
    quantity: float
    avg_cost: float
    market_value: float
    unrealized_pnl: float
    side: str  # "long" | "short"
    market: str  # which module owns this
    opened_at: Optional[datetime] = None
    extra: dict = field(default_factory=dict)


@dataclass
class TradeSignal:
    symbol: str
    action: str  # "buy" | "sell" | "close"
    quantity: float
    confidence: float  # 0.0–1.0
    strategy: str
    market: str
    reason: str = ""
    params: dict = field(default_factory=dict)


@dataclass
class TradeResult:
    signal: TradeSignal
    executed: bool
    fill_price: Optional[float]
    fill_qty: Optional[float]
    realized_pnl: Optional[float]
    order_id: Optional[str]
    error: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class HealthStatus:
    market: str
    status: MarketStatus
    message: str
    daily_pnl: float = 0.0
    open_positions: int = 0
    last_trade_at: Optional[datetime] = None
    details: dict = field(default_factory=dict)


class MarketModule(ABC):
    """
    Abstract base class for all market trading modules.

    Each module manages its own broker connection, strategy execution,
    and position tracking. Modules report to MultiMarketOrchestrator.
    """

    market_name: str = ""
    daily_target: float = 0.0
    capital_allocated: float = 0.0

    @abstractmethod
    async def connect(self) -> bool:
        """Establish broker/exchange connection. Return True on success."""

    @abstractmethod
    async def get_positions(self) -> list[Position]:
        """Return all currently open positions for this market."""

    @abstractmethod
    async def get_daily_pnl(self) -> float:
        """Return today's realized + unrealized P&L in USD."""

    @abstractmethod
    async def run_strategy_cycle(self) -> list[TradeSignal]:
        """Run one strategy cycle. Return signals (may be empty)."""

    @abstractmethod
    async def execute_signal(self, signal: TradeSignal) -> TradeResult:
        """Execute a trade signal. Return result (executed or rejected)."""

    @abstractmethod
    async def shutdown(self) -> None:
        """Gracefully close positions and disconnect. Called on halt."""

    @abstractmethod
    def health_check(self) -> HealthStatus:
        """Return current health/status of this module."""

    def is_enabled(self) -> bool:
        """Override to add module-specific enable checks."""
        return True
