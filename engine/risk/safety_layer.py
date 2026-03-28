"""
JARVIS TRADER — Safety Layer
================================
CRITICAL: This module is HARDCODED in Python. NO LLM reasoning in the safety path.
All risk controls are enforced here before any order reaches a broker.

Design principle from TradeTrap paper:
  - Portfolio state of record comes from broker API, NEVER from agent memory
  - Hard limits cannot be overridden by agent reasoning
  - Kill switch can only be re-enabled by human (Matt)
"""
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class KillSwitchReason(Enum):
    MANUAL = "manual"
    DAILY_LOSS_LIMIT = "daily_loss_limit"
    MAX_DRAWDOWN = "max_drawdown"
    MARKET_CIRCUIT_BREAKER = "market_circuit_breaker"
    DATA_FEED_LOSS = "data_feed_loss"
    BROKER_DISCONNECT = "broker_disconnect"
    ANOMALOUS_ORDER_RATE = "anomalous_order_rate"


@dataclass
class OrderRequest:
    symbol: str
    quantity: int          # Positive = buy, negative = sell
    order_type: str        # "market", "limit", "stop", "stop_limit"
    limit_price: float | None = None
    stop_price: float | None = None
    is_futures: bool = False
    is_options: bool = False
    estimated_value: float = 0.0


@dataclass
class RiskCheckResult:
    approved: bool
    rejection_reason: str | None = None
    warnings: list[str] = field(default_factory=list)


class SafetyLayer:
    """
    Non-LLM risk management. Every order MUST pass through here.
    Instantiated once at startup and shared across all agents.
    """

    def __init__(self, config):
        self._config = config
        self._kill_switch_active = False
        self._kill_switch_reason: KillSwitchReason | None = None

        # Daily tracking (reset at market open)
        self._daily_realized_pnl: float = 0.0
        self._daily_order_count: int = 0
        self._daily_date: date = date.today()

        # Peak equity for drawdown calculation (from broker API, not agent)
        self._equity_peak: float = 0.0
        self._current_equity: float = 0.0

        # Orders per minute tracking
        self._recent_order_timestamps: list[float] = []

    # ── Kill Switch ───────────────────────────────────────────────────────

    def activate_kill_switch(self, reason: KillSwitchReason, message: str = "") -> None:
        """Halt all trading. Requires human re-authorization to resume."""
        self._kill_switch_active = True
        self._kill_switch_reason = reason
        logger.critical(f"🔴 KILL SWITCH ACTIVATED: {reason.value}. {message}")

    def deactivate_kill_switch(self, authorized_by: str = "human") -> None:
        """Resume trading. Only callable by human action (not by agents)."""
        self._kill_switch_active = False
        self._kill_switch_reason = None
        logger.info(f"✅ Kill switch deactivated by: {authorized_by}")

    @property
    def is_killed(self) -> bool:
        return self._kill_switch_active

    # ── Pre-Trade Checks ─────────────────────────────────────────────────

    def check_order(self, order: OrderRequest, portfolio_equity: float) -> RiskCheckResult:
        """
        Run all pre-trade safety checks.
        Returns approved=False if ANY check fails.
        Hard limits are non-negotiable.
        """
        warnings = []

        # 0. Kill switch
        if self._kill_switch_active:
            return RiskCheckResult(
                approved=False,
                rejection_reason=f"Kill switch active: {self._kill_switch_reason.value if self._kill_switch_reason else 'unknown'}"
            )

        # 1. Live trading gate
        if not self._config.LIVE_TRADING_ENABLED:
            return RiskCheckResult(
                approved=False,
                rejection_reason="Live trading is disabled (LIVE_TRADING_ENABLED=False)"
            )

        # 2. Human approval gate
        if self._config.REQUIRE_HUMAN_APPROVAL:
            return RiskCheckResult(
                approved=False,
                rejection_reason="Human approval required (REQUIRE_HUMAN_APPROVAL=True) — this is normal in initial deployment"
            )

        # 3. Daily loss limit
        if self._daily_realized_pnl < -(portfolio_equity * self._config.MAX_DAILY_LOSS_PCT):
            self.activate_kill_switch(
                KillSwitchReason.DAILY_LOSS_LIMIT,
                f"Daily loss {self._daily_realized_pnl:.2f} exceeded limit"
            )
            return RiskCheckResult(
                approved=False,
                rejection_reason="Daily loss limit breached — kill switch activated"
            )

        # 4. Max drawdown
        if self._equity_peak > 0:
            drawdown = (self._equity_peak - portfolio_equity) / self._equity_peak
            if drawdown > self._config.MAX_DRAWDOWN_PCT:
                self.activate_kill_switch(
                    KillSwitchReason.MAX_DRAWDOWN,
                    f"Drawdown {drawdown:.1%} exceeded max {self._config.MAX_DRAWDOWN_PCT:.1%}"
                )
                return RiskCheckResult(
                    approved=False,
                    rejection_reason="Max drawdown breached — kill switch activated"
                )
            elif drawdown > self._config.MAX_DRAWDOWN_PCT * 0.8:
                warnings.append(f"Drawdown at {drawdown:.1%} — approaching {self._config.MAX_DRAWDOWN_PCT:.1%} limit")

        # 5. Order size limit
        if order.estimated_value > self._config.MAX_SINGLE_ORDER_VALUE:
            return RiskCheckResult(
                approved=False,
                rejection_reason=f"Order value ${order.estimated_value:,.0f} exceeds max ${self._config.MAX_SINGLE_ORDER_VALUE:,.0f}"
            )

        # 6. Position size limit
        position_pct = order.estimated_value / portfolio_equity if portfolio_equity > 0 else 1.0
        if position_pct > self._config.MAX_POSITION_SIZE_PCT:
            return RiskCheckResult(
                approved=False,
                rejection_reason=f"Position size {position_pct:.1%} exceeds max {self._config.MAX_POSITION_SIZE_PCT:.1%}"
            )

        # 7. Order rate throttle (anti-runaway)
        import time
        now = time.time()
        self._recent_order_timestamps = [t for t in self._recent_order_timestamps if now - t < 60]
        if len(self._recent_order_timestamps) >= self._config.MAX_ORDERS_PER_MINUTE:
            self.activate_kill_switch(
                KillSwitchReason.ANOMALOUS_ORDER_RATE,
                f"Order rate exceeded {self._config.MAX_ORDERS_PER_MINUTE}/min"
            )
            return RiskCheckResult(
                approved=False,
                rejection_reason="Anomalous order rate — kill switch activated"
            )

        # 8. Futures-specific: contract limits
        if order.is_futures and abs(order.quantity) > self._config.MAX_CONTRACTS_PER_INSTRUMENT:
            return RiskCheckResult(
                approved=False,
                rejection_reason=f"Requested {abs(order.quantity)} contracts exceeds max {self._config.MAX_CONTRACTS_PER_INSTRUMENT}"
            )

        # All checks passed
        self._recent_order_timestamps.append(now)
        logger.info(f"✅ Order approved: {order.symbol} qty={order.quantity} est_value=${order.estimated_value:,.0f}")
        return RiskCheckResult(approved=True, warnings=warnings)

    # ── Portfolio State Sync (from broker, NOT from agents) ───────────────

    def sync_from_broker(self, equity: float, daily_pnl: float) -> None:
        """
        Called every 60 seconds with ground truth from broker API.
        This is the ONLY way portfolio state is updated — never via agent memory.
        """
        self._current_equity = equity
        self._daily_realized_pnl = daily_pnl

        if equity > self._equity_peak:
            self._equity_peak = equity

        # Auto-trigger daily loss check
        if daily_pnl < -(equity * self._config.MAX_DAILY_LOSS_PCT):
            self.activate_kill_switch(
                KillSwitchReason.DAILY_LOSS_LIMIT,
                f"Intraday sync: daily PnL {daily_pnl:.2f}"
            )

    def get_status(self) -> dict:
        return {
            "kill_switch_active": self._kill_switch_active,
            "kill_switch_reason": self._kill_switch_reason.value if self._kill_switch_reason else None,
            "live_trading_enabled": self._config.LIVE_TRADING_ENABLED,
            "require_human_approval": self._config.REQUIRE_HUMAN_APPROVAL,
            "daily_pnl": self._daily_realized_pnl,
            "equity_peak": self._equity_peak,
            "current_equity": self._current_equity,
            "drawdown_pct": (
                (self._equity_peak - self._current_equity) / self._equity_peak
                if self._equity_peak > 0 else 0.0
            ),
            "orders_last_minute": len(self._recent_order_timestamps),
        }
