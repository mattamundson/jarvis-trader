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

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional

try:
    from engine.execution.ib_gateway import IBGatewayManager

    _IB_GATEWAY_AVAILABLE = True
except ImportError:
    IBGatewayManager = None  # type: ignore[assignment,misc]
    _IB_GATEWAY_AVAILABLE = False

try:
    from risk.pnl_monitor import PnLMonitor
except ImportError:
    try:
        from engine.risk.pnl_monitor import PnLMonitor
    except ImportError:
        PnLMonitor = None  # type: ignore[assignment,misc]

try:
    from risk.loss_tracker import ConsecutiveLossTracker
except ImportError:
    try:
        from engine.risk.loss_tracker import ConsecutiveLossTracker
    except ImportError:
        ConsecutiveLossTracker = None  # type: ignore[assignment,misc]

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
    quantity: int  # Positive = buy, negative = sell
    order_type: str  # "market", "limit", "stop", "stop_limit"
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
    adjusted_order: Optional[OrderRequest] = None  # Order with position size adjusted for losses


class SafetyLayer:
    """
    Non-LLM risk management. Every order MUST pass through here.
    Instantiated once at startup and shared across all agents.
    """

    def __init__(self, config, ib_gateway=None, pnl_monitor=None, loss_tracker=None):
        """
        Parameters
        ----------
        config:
            JARVIS settings object (LIVE_TRADING_ENABLED, MAX_DAILY_LOSS_PCT, …).
        ib_gateway : IBGatewayManager | None
            Optional IB Gateway handle used by submit_paper_order().
            Passing None keeps the SafetyLayer fully backward-compatible — all
            existing callers that construct ``SafetyLayer(config)`` continue to
            work without changes.  The gateway is NEVER used by check_order()
            or any other existing method.
        pnl_monitor : PnLMonitor | None
            Optional PnLMonitor instance.  When provided, circuit-breaker checks
            in check_order() and sync_from_broker() read live P&L from the best
            available source (IB Gateway → SQLite → in-memory tracker) rather
            than relying solely on the values last set by sync_from_broker().
            Passing None preserves full backward-compatibility.
        loss_tracker : ConsecutiveLossTracker | None
            Optional ConsecutiveLossTracker instance. When provided, tracks
            consecutive losing trades and modulates position size accordingly.
            Passing None preserves full backward-compatibility.
        """
        self._config = config
        self._ib_gateway = ib_gateway  # used only by submit_paper_order()
        self._pnl_monitor: Optional[object] = pnl_monitor  # PnLMonitor | None
        self._loss_tracker: Optional[object] = loss_tracker  # ConsecutiveLossTracker | None
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

    def activate_kill_switch(self, reason: KillSwitchReason | str, message: str = "") -> None:
        """Halt all trading. Requires human re-authorization to resume."""
        self._kill_switch_active = True
        # Convert string to enum if needed (for backward compatibility with tests)
        if isinstance(reason, str):
            try:
                reason = KillSwitchReason[reason]
            except KeyError:
                logger.warning(f"Unknown kill switch reason: {reason}")
                reason = KillSwitchReason.MANUAL
        self._kill_switch_reason = reason
        logger.critical(f"🔴 KILL SWITCH ACTIVATED: {reason.value}. {message}")
        # Log to PostgreSQL asynchronously (never block)
        try:
            asyncio.create_task(
                self._log_safety_event(
                    "kill_switch_activate",
                    reason.value,
                    {"reason": reason.value, "message": message},
                )
            )
        except RuntimeError:
            # No running event loop (e.g., in tests or sync context)
            logger.debug("No running event loop for async logging")

    def deactivate_kill_switch(self, authorized_by: str = "human") -> None:
        """Resume trading. Only callable by human action (not by agents)."""
        self._kill_switch_active = False
        self._kill_switch_reason = None
        logger.info(f"✅ Kill switch deactivated by: {authorized_by}")
        # Log to PostgreSQL asynchronously
        try:
            asyncio.create_task(
                self._log_safety_event(
                    "kill_switch_deactivate",
                    f"Deactivated by {authorized_by}",
                    {"authorized_by": authorized_by, "resolved": True},
                )
            )
        except RuntimeError:
            # No running event loop (e.g., in tests or sync context)
            logger.debug("No running event loop for async logging")

    @property
    def is_killed(self) -> bool:
        return self._kill_switch_active

    def get_status(self) -> dict:
        """Return safety layer status for agents."""
        return {
            "is_killed": self._kill_switch_active,
            "kill_switch_reason": self._kill_switch_reason.value
            if self._kill_switch_reason
            else None,
            "daily_realized_pnl": self._daily_realized_pnl,
            "equity_peak": self._equity_peak,
            "current_equity": self._current_equity,
            "recent_order_count": len(self._recent_order_timestamps),
        }

    # ── Pre-Trade Checks ─────────────────────────────────────────────────

    def _check_drawdown(self, portfolio_equity: float, warnings: list) -> RiskCheckResult | None:
        """Check max drawdown limits. Returns None if passed."""
        if self._pnl_monitor is not None:
            drawdown = -self._pnl_monitor.get_drawdown_pct()
            if drawdown > self._config.MAX_DRAWDOWN_PCT:
                self.activate_kill_switch(
                    KillSwitchReason.MAX_DRAWDOWN,
                    f"Drawdown {drawdown:.1%} exceeded max {self._config.MAX_DRAWDOWN_PCT:.1%} (source: pnl_monitor)",
                )
                return RiskCheckResult(
                    approved=False, rejection_reason="Max drawdown breached — kill switch activated"
                )
            elif drawdown >= self._config.MAX_DRAWDOWN_PCT * 0.8:
                warnings.append(
                    f"Drawdown at {drawdown:.1%} — approaching {self._config.MAX_DRAWDOWN_PCT:.1%} limit"
                )
        elif self._equity_peak > 0:
            drawdown = (self._equity_peak - portfolio_equity) / self._equity_peak
            if drawdown > self._config.MAX_DRAWDOWN_PCT:
                self.activate_kill_switch(
                    KillSwitchReason.MAX_DRAWDOWN,
                    f"Drawdown {drawdown:.1%} exceeded max {self._config.MAX_DRAWDOWN_PCT:.1%}",
                )
                return RiskCheckResult(
                    approved=False, rejection_reason="Max drawdown breached — kill switch activated"
                )
            elif drawdown >= self._config.MAX_DRAWDOWN_PCT * 0.8:
                warnings.append(
                    f"Drawdown at {drawdown:.1%} — approaching {self._config.MAX_DRAWDOWN_PCT:.1%} limit"
                )
        return None

    def _apply_loss_tracker_adjustment(
        self, order: OrderRequest, warnings: list
    ) -> RiskCheckResult | tuple[OrderRequest, list]:
        """Apply loss tracker adjustments. Returns error result or (adjusted_order, warnings)."""
        if self._loss_tracker is None:
            return order, warnings

        if self._loss_tracker.is_halted():
            return RiskCheckResult(
                approved=False, rejection_reason=self._loss_tracker.get_halt_reason()
            )

        multiplier = self._loss_tracker.get_position_size_multiplier()
        if multiplier < 1.0:
            reduced_quantity = max(1, int(abs(order.quantity) * multiplier))
            adjusted_order = OrderRequest(
                symbol=order.symbol,
                quantity=reduced_quantity if order.quantity > 0 else -reduced_quantity,
                order_type=order.order_type,
                limit_price=order.limit_price,
                stop_price=order.stop_price,
                is_futures=order.is_futures,
                is_options=order.is_options,
                estimated_value=order.estimated_value * multiplier,
            )
            consecutive_losses = self._loss_tracker.get_consecutive_losses()
            warnings.append(
                f"Consecutive losses: {consecutive_losses} — "
                f"position size reduced by {(1.0 - multiplier):.0%} "
                f"(qty: {order.quantity} → {adjusted_order.quantity})"
            )
            logger.warning(
                f"Position size reduction applied: {order.symbol} qty {order.quantity} → "
                f"{adjusted_order.quantity} (multiplier={multiplier:.2f})"
            )
            return adjusted_order, warnings
        return order, warnings

    def _check_kill_switch(self) -> RiskCheckResult:
        """Check kill switch status."""
        if self._kill_switch_active:
            return RiskCheckResult(
                approved=False,
                rejection_reason=f"Kill switch active: {self._kill_switch_reason.value if self._kill_switch_reason else 'unknown'}",
            )
        return RiskCheckResult(approved=True)

    def _check_gating_conditions(self) -> RiskCheckResult:
        """Check live trading enabled and human approval conditions."""
        if not self._config.LIVE_TRADING_ENABLED:
            return RiskCheckResult(
                approved=False,
                rejection_reason="Live trading is disabled (LIVE_TRADING_ENABLED=False)",
            )
        if self._config.REQUIRE_HUMAN_APPROVAL:
            return RiskCheckResult(
                approved=False,
                rejection_reason="Human approval required (REQUIRE_HUMAN_APPROVAL=True) — this is normal in initial deployment",
            )
        return RiskCheckResult(approved=True)

    def _check_daily_loss_limit(self, portfolio_equity: float) -> RiskCheckResult:
        """Check daily loss limit."""
        daily_pnl = self._pnl_monitor.get_daily_pnl() if self._pnl_monitor else self._daily_realized_pnl
        if daily_pnl < -(portfolio_equity * self._config.MAX_DAILY_LOSS_PCT):
            self.activate_kill_switch(
                KillSwitchReason.DAILY_LOSS_LIMIT,
                f"Daily loss {daily_pnl:.2f} exceeded limit",
            )
            return RiskCheckResult(
                approved=False, rejection_reason="Daily loss limit breached — kill switch activated"
            )
        return RiskCheckResult(approved=True)

    def _check_order_value_limits(self, order: OrderRequest, portfolio_equity: float) -> RiskCheckResult:
        """Check order size and position size limits."""
        if order.estimated_value > self._config.MAX_SINGLE_ORDER_VALUE:
            return RiskCheckResult(
                approved=False,
                rejection_reason=f"Order value ${order.estimated_value:,.0f} exceeds max ${self._config.MAX_SINGLE_ORDER_VALUE:,.0f}",
            )
        position_pct = order.estimated_value / portfolio_equity if portfolio_equity > 0 else 1.0
        if position_pct > self._config.MAX_POSITION_SIZE_PCT:
            return RiskCheckResult(
                approved=False,
                rejection_reason=f"Position size {position_pct:.1%} exceeds max {self._config.MAX_POSITION_SIZE_PCT:.1%}",
            )
        return RiskCheckResult(approved=True)

    def _check_order_rate(self) -> RiskCheckResult:
        """Check order rate throttle."""
        import time
        now = time.time()
        self._recent_order_timestamps = [t for t in self._recent_order_timestamps if now - t < 60]
        if len(self._recent_order_timestamps) >= self._config.MAX_ORDERS_PER_MINUTE:
            self.activate_kill_switch(
                KillSwitchReason.ANOMALOUS_ORDER_RATE,
                f"Order rate exceeded {self._config.MAX_ORDERS_PER_MINUTE}/min",
            )
            return RiskCheckResult(
                approved=False, rejection_reason="Anomalous order rate — kill switch activated"
            )
        return RiskCheckResult(approved=True), now

    def _check_contract_limits(self, order: OrderRequest) -> RiskCheckResult:
        """Check futures contract limits."""
        if order.is_futures and abs(order.quantity) > self._config.MAX_CONTRACTS_PER_INSTRUMENT:
            return RiskCheckResult(
                approved=False,
                rejection_reason=f"Requested {abs(order.quantity)} contracts exceeds max {self._config.MAX_CONTRACTS_PER_INSTRUMENT}",
            )
        return RiskCheckResult(approved=True)

    def check_order(self, order: OrderRequest, portfolio_equity: float) -> RiskCheckResult:
        """
        Run all pre-trade safety checks.
        Returns approved=False if ANY check fails.
        Hard limits are non-negotiable.
        """
        warnings = []

        # Run sequential checks, return early on failure
        for check_fn in [
            lambda: self._check_kill_switch(),
            lambda: self._check_gating_conditions(),
            lambda: self._check_daily_loss_limit(portfolio_equity),
            lambda: self._check_drawdown(portfolio_equity, warnings),
            lambda: self._check_order_value_limits(order, portfolio_equity),
            lambda: self._check_contract_limits(order),
        ]:
            result = check_fn()
            if isinstance(result, tuple):
                result, _ = result
            if not result.approved:
                return result

        # Order rate check returns timestamp
        rate_result, now = self._check_order_rate()
        if not rate_result.approved:
            return rate_result

        # Drawdown check
        drawdown_result = self._check_drawdown(portfolio_equity, warnings)
        if drawdown_result is not None and not drawdown_result.approved:
            return drawdown_result

        # Loss tracker adjustment
        loss_result = self._apply_loss_tracker_adjustment(order, warnings)
        if isinstance(loss_result, RiskCheckResult):
            return loss_result
        adjusted_order, warnings = loss_result

        # All checks passed
        self._recent_order_timestamps.append(now)
        logger.info(
            f"✅ Order approved: {adjusted_order.symbol} qty={adjusted_order.quantity} est_value=${adjusted_order.estimated_value:,.0f}"
        )
        return RiskCheckResult(
            approved=True,
            warnings=warnings,
            adjusted_order=adjusted_order if adjusted_order != order else None,
        )

    # ── Paper Order Submission (Safety → IB Gateway) ──────────────────────

    async def submit_paper_order(
        self,
        symbol: str,
        action: str,
        quantity: int,
        price: float,
        order_type: str = "MKT",
        limit_price: float | None = None,
    ) -> dict:
        """
        Run all safety checks then, if they pass, route the order to IB
        Gateway in paper-trading mode (port 4002).

        This is the ONLY approved path from the SafetyLayer to the broker.
        No LLM reasoning happens here — pure deterministic gate.

        Parameters
        ----------
        symbol      : Ticker / futures root (e.g. "MES", "AAPL").
        action      : "BUY" or "SELL" (case-insensitive).
        quantity    : Positive integer — always pass the absolute lot size.
                      Direction is expressed via *action*.
        price       : Estimated execution price (used for value checks).
        order_type  : "MKT" (default) or "LMT".
        limit_price : Required when order_type == "LMT".

        Returns
        -------
        dict with keys:
            approved    (bool)   — True only when every safety check passed.
            reason      (str)    — Human-readable outcome (approval or rejection message).
            order_id    (str|None) — IB order ID string if the order was placed, else None.
            routed_to_ib (bool)  — True only when the order reached IB Gateway.
        """
        # ── 0. Kill switch — checked first, before anything else ──────────
        if self._kill_switch_active:
            reason = (
                f"Kill switch active: {self._kill_switch_reason.value}"
                if self._kill_switch_reason
                else "Kill switch active"
            )
            logger.warning(
                "submit_paper_order BLOCKED by kill switch — symbol=%s action=%s qty=%d: %s",
                symbol,
                action,
                quantity,
                reason,
            )
            return {"approved": False, "reason": reason, "order_id": None, "routed_to_ib": False}

        # ── 1. Build an OrderRequest so we can re-use check_order() fully ─
        action_upper = action.upper()
        signed_qty = quantity if action_upper == "BUY" else -quantity
        estimated_value = abs(quantity) * price

        # Detect futures by common micro/mini root symbols (heuristic; callers
        # can override by subclassing or by building the OrderRequest directly
        # and calling check_order() + submit_paper_order separately).
        _FUTURES_ROOTS = {
            "MES",
            "MNQ",
            "M2K",
            "MCL",
            "MGC",
            "MHG",
            "MSI",
            "ES",
            "NQ",
            "RTY",
            "CL",
            "GC",
            "HG",
        }
        is_futures = symbol.upper() in _FUTURES_ROOTS

        ib_order_type = order_type.lower()
        # Normalise "MKT"→"market", "LMT"→"limit" for OrderRequest
        if ib_order_type in ("mkt", "market"):
            normalised_order_type = "market"
        elif ib_order_type in ("lmt", "limit"):
            normalised_order_type = "limit"
        else:
            normalised_order_type = ib_order_type

        order = OrderRequest(
            symbol=symbol,
            quantity=signed_qty,
            order_type=normalised_order_type,
            limit_price=limit_price,
            is_futures=is_futures,
            estimated_value=estimated_value,
        )

        # ── 2. Full pre-trade safety gate ─────────────────────────────────
        # check_order() re-checks the kill switch internally (check #0 above
        # is an early-exit optimisation to avoid building OrderRequest at all
        # when we already know the kill switch is on).
        portfolio_equity = self._current_equity if self._current_equity > 0 else estimated_value
        risk_result = self.check_order(order, portfolio_equity)

        if not risk_result.approved:
            logger.warning(
                "submit_paper_order REJECTED by SafetyLayer — symbol=%s action=%s qty=%d: %s",
                symbol,
                action,
                quantity,
                risk_result.rejection_reason,
            )
            return {
                "approved": False,
                "reason": risk_result.rejection_reason or "Safety check failed",
                "order_id": None,
                "routed_to_ib": False,
            }

        if risk_result.warnings:
            for w in risk_result.warnings:
                logger.warning("submit_paper_order safety warning (order allowed): %s", w)

        # ── 3. Route to IB Gateway if available ───────────────────────────
        if self._ib_gateway is None:
            logger.info(
                "submit_paper_order: safety checks PASSED — no IB gateway attached "
                "(dry-run mode). symbol=%s action=%s qty=%d",
                symbol,
                action,
                quantity,
            )
            return {
                "approved": True,
                "reason": "Safety checks passed — IB gateway not attached (dry-run)",
                "order_id": None,
                "routed_to_ib": False,
            }

        if not self._ib_gateway.is_connected():
            logger.error(
                "submit_paper_order: safety checks PASSED but IB gateway is NOT connected. "
                "symbol=%s action=%s qty=%d",
                symbol,
                action,
                quantity,
            )
            return {
                "approved": True,
                "reason": "Safety checks passed — IB gateway not connected",
                "order_id": None,
                "routed_to_ib": False,
            }

        try:
            order_id = await self._ib_gateway.place_paper_order(
                symbol=symbol,
                action=action_upper,
                quantity=quantity,
                order_type=order_type.upper(),
                limit_price=limit_price,
            )
            logger.info(
                "submit_paper_order ROUTED to IB Gateway (paper) — symbol=%s action=%s "
                "qty=%d order_type=%s order_id=%s",
                symbol,
                action_upper,
                quantity,
                order_type.upper(),
                order_id,
            )
            return {
                "approved": True,
                "reason": "Order submitted to IB Gateway (paper trading)",
                "order_id": str(order_id) if order_id is not None else None,
                "routed_to_ib": True,
            }
        except Exception as exc:
            logger.error(
                "submit_paper_order: IB Gateway place_paper_order raised — symbol=%s: %s",
                symbol,
                exc,
                exc_info=True,
            )
            return {
                "approved": True,
                "reason": f"Safety checks passed but IB Gateway raised: {exc}",
                "order_id": None,
                "routed_to_ib": False,
            }

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
                KillSwitchReason.DAILY_LOSS_LIMIT, f"Intraday sync: daily PnL {daily_pnl:.2f}"
            )

    def check_circuit_breakers(self) -> dict:
        """
        Return the current status of all circuit breakers as a single dict.

        This method is safe to call at any time — it does NOT activate the kill
        switch.  Use it for dashboard polling and the /safety/circuit-breakers
        API endpoint.

        Returns
        -------
        dict with keys:
            daily_pnl            (float)  — today's realized + unrealized P&L in $
            daily_limit          (float)  — maximum allowed daily loss in $ (negative)
            daily_pnl_pct        (float)  — daily P&L as fraction of starting balance
            daily_limit_pct      (float)  — configured daily loss limit (negative fraction)
            daily_limit_breached (bool)  — if daily loss limit has been breached
            drawdown_pct         (float)  — current drawdown from peak (negative)
            drawdown_limit_pct   (float)  — configured max drawdown (negative)
            drawdown_breached    (bool)  — if drawdown limit has been breached
            kill_switch_active   (bool)  — if emergency halt is engaged
            kill_switch_reason   (str)   — reason for kill switch if active
        """
        # Use PnLMonitor when available; fall back to in-memory values
        if self._pnl_monitor is not None:
            daily_pnl_for_check = self._pnl_monitor.get_daily_pnl()
        else:
            daily_pnl_for_check = self._daily_realized_pnl

        # Daily loss circuit breaker
        daily_limit = (
            -(self._current_equity * self._config.MAX_DAILY_LOSS_PCT)
            if self._current_equity > 0
            else 0
        )
        daily_pnl_pct = (
            (daily_pnl_for_check / self._current_equity) if self._current_equity > 0 else 0
        )
        daily_limit_pct = -self._config.MAX_DAILY_LOSS_PCT
        daily_limit_breached = daily_pnl_for_check < daily_limit

        # Drawdown circuit breaker
        drawdown_pct = 0.0
        if self._pnl_monitor is not None:
            drawdown_pct = -self._pnl_monitor.get_drawdown_pct()
        elif self._equity_peak > 0:
            drawdown_pct = (self._equity_peak - self._current_equity) / self._equity_peak
        drawdown_limit_pct = -self._config.MAX_DRAWDOWN_PCT
        drawdown_breached = drawdown_pct > self._config.MAX_DRAWDOWN_PCT

        return {
            "daily_pnl": daily_pnl_for_check,
            "daily_limit": daily_limit,
            "daily_pnl_pct": daily_pnl_pct,
            "daily_limit_pct": daily_limit_pct,
            "daily_limit_breached": daily_limit_breached,
            "drawdown_pct": drawdown_pct,
            "drawdown_limit_pct": drawdown_limit_pct,
            "drawdown_breached": drawdown_breached,
            "kill_switch_active": self._kill_switch_active,
            "kill_switch_reason": self._kill_switch_reason.value
            if self._kill_switch_reason
            else None,
        }

    # ── Loss Tracking API ──────────────────────────────────────────────────

    def record_trade_result(self, symbol: str, pnl: float) -> None:
        """
        Record a trade result to the loss tracker.

        Called by the trader agent or risk manager after a trade closes.

        Parameters
        ----------
        symbol : str
            Trading symbol (e.g., "MES", "AAPL")
        pnl : float
            Profit/loss in dollars
        """
        if self._loss_tracker is not None:
            is_win = self._loss_tracker.record_trade(symbol, pnl)
            logger.info(f"Trade recorded: {symbol} PnL=${pnl:.2f} ({'WIN' if is_win else 'LOSS'})")
        else:
            logger.debug(f"Loss tracker not available; trade not recorded: {symbol} PnL=${pnl:.2f}")

    def get_loss_tracker_status(self) -> dict:
        """
        Return current loss tracker status.

        Returns
        -------
        dict with comprehensive loss tracking state
        """
        if self._loss_tracker is None:
            return {"enabled": False, "message": "Loss tracker not available"}
        return {"enabled": True, **self._loss_tracker.get_status()}

    def reset_loss_tracker(self, symbol: Optional[str] = None) -> dict:
        """
        Manually reset loss tracker (human intervention).

        Parameters
        ----------
        symbol : str | None
            If None, reset global counter. Otherwise reset for this symbol.

        Returns
        -------
        dict with updated status
        """
        if self._loss_tracker is None:
            return {"status": "Loss tracker not available"}

        self._loss_tracker.reset(symbol=symbol)
        return {"status": "Reset successful", **self._loss_tracker.get_status()}

    async def _log_safety_event(
        self,
        event_type: str,
        reason: str,
        details: dict = None,
    ) -> None:
        """
        Log a safety event to PostgreSQL.

        Gracefully handles database unavailability — never blocks execution.

        Args:
            event_type: Type of event (kill_switch_activate, kill_switch_deactivate, etc.)
            reason: Human-readable reason
            details: Event details dict
        """
        try:
            from database import repository

            await repository.insert_safety_event(
                event_type=event_type,
                reason=reason,
                details=details,
                resolved=details.get("resolved", False) if details else False,
            )
            logger.debug(f"[DB] Safety event logged: {event_type}")
        except Exception as e:
            # Never block safety operations due to logging errors
            logger.warning(f"[DB] Failed to log safety event: {e}")
