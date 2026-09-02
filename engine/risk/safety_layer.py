"""
JARVIS TRADER - Safety Layer
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
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional

try:
    from config import settings
except ImportError:
    try:
        from engine.config import settings
    except ImportError:
        settings = None  # type: ignore[assignment]

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
    from risk.alert_manager import AlertManager
except ImportError:
    try:
        from engine.risk.alert_manager import AlertManager
    except ImportError:
        AlertManager = None  # type: ignore[assignment,misc]

try:
    from risk.loss_tracker import ConsecutiveLossTracker
except ImportError:
    try:
        from engine.risk.loss_tracker import ConsecutiveLossTracker
    except ImportError:
        ConsecutiveLossTracker = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)


def _schedule_background_coro(factory: Callable[[], Coroutine[Any, Any, Any]]) -> None:
    """
    Schedule *factory()* on the running loop, or no-op in sync contexts (tests, scripts).

    Never call ``asyncio.create_task(coro())`` when *coro* is built before *create_task*:
    if there is no running loop, the coroutine object would be discarded and Python
    emits ``RuntimeWarning: coroutine was never awaited``.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug("No running event loop - background coroutine not scheduled")
        return
    loop.create_task(factory())


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

    def __init__(self, config, ib_gateway=None, pnl_monitor=None, loss_tracker=None, db_path: Optional[str] = None, db_manager=None):
        """
        Parameters
        ----------
        config:
            JARVIS settings object (LIVE_TRADING_ENABLED, MAX_DAILY_LOSS_PCT, ...).
        ib_gateway : IBGatewayManager | None
            Optional IB Gateway handle used by submit_paper_order().
            Passing None keeps the SafetyLayer fully backward-compatible - all
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
        db_path : str | None
            Absolute path to the SQLite file used by the engine. When omitted or
            empty, kill-switch state is **not** persisted (tests, one-off scripts).
            ``main.py`` passes ``db_manager``'s path so restarts re-arm a latched kill switch.
        db_manager : DatabaseManager | None
            Optional DatabaseManager instance for P&L snapshot persistence.
            When provided, daily_pnl state is saved to SQLite on every sync
            and restored on startup so restarts don't reset intraday drawdown to 0.
        """
        self._config = config
        self._ib_gateway = ib_gateway  # used only by submit_paper_order()
        self._pnl_monitor: Optional[object] = pnl_monitor  # PnLMonitor | None
        self._loss_tracker: Optional[object] = loss_tracker  # ConsecutiveLossTracker | None
        self._db_manager = db_manager  # DatabaseManager | None - for P&L snapshot persistence
        self.schwab = (
            None  # SchwabConnector | None - injected after construction via attach_schwab()
        )
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

        # Tilt detector (optional — injected after construction)
        self.tilt_detector = None

        # Alert manager (optional — injected after construction via inject_alert_manager())
        self._alert_manager: Optional[object] = None  # AlertManager | None

        # Re-entry lockouts: symbol -> lockout_until datetime
        self._reentry_lockouts: dict[str, datetime] = {}

        # Resolve DB path for kill switch persistence
        self._db_path: Optional[str] = self._resolve_db_path(db_path)

        # Load persisted kill switch state
        self._load_kill_switch_state()

        # Restore today's P&L snapshot from SQLite if available - must be last in __init__
        self._load_pnl_snapshot()

    def attach_ib_gateway(self, gateway) -> None:
        """Wire in an IB gateway after construction (called after paper connector connects)."""
        self._ib_gateway = gateway

    def attach_schwab(self, connector) -> None:
        """Attach Schwab connector for equity/options order routing."""
        self.schwab = connector
        logger.info("SafetyLayer: Schwab connector attached")

    def inject_alert_manager(self, manager: object) -> None:
        """
        Wire in an AlertManager after construction.

        Called from main.py lifespan after both the WhatsApp notifier and
        SafetyLayer are initialised.  Passing None is a no-op (disables alerts).
        """
        self._alert_manager = manager
        logger.info("SafetyLayer: AlertManager injected — P&L push alerts active")

    # ── Kill Switch DB Persistence ────────────────────────────────────────

    def _resolve_db_path(self, db_path: Optional[str]) -> Optional[str]:
        """Return a non-empty SQLite path, or None to disable kill-switch persistence."""
        if db_path and str(db_path).strip():
            return str(db_path)
        return None

    def _load_pnl_snapshot(self) -> None:
        """
        Restore today's P&L state from SQLite on startup.

        If a snapshot exists for today, restores daily_pnl, current_equity,
        and equity_peak so the safety layer doesn't reset drawdown to 0 on
        engine restarts mid-session.
        """
        if self._db_manager is None:
            logger.debug("SafetyLayer: no db_manager - skipping P&L snapshot load")
            return
        try:
            today = date.today().isoformat()
            snap = self._db_manager.get_pnl_snapshot(today)
            if snap:
                self._daily_realized_pnl = float(snap.get("daily_pnl", 0.0))
                self._current_equity = float(snap.get("portfolio_equity", 0.0))
                peak = float(snap.get("peak_equity", 0.0))
                if peak > self._equity_peak:
                    self._equity_peak = peak
                logger.info(
                    "SafetyLayer: restored P&L snapshot for %s - daily_pnl=%+.2f equity=%.2f peak=%.2f",
                    today,
                    self._daily_realized_pnl,
                    self._current_equity,
                    self._equity_peak,
                )
            else:
                logger.debug("SafetyLayer: no P&L snapshot for %s - starting fresh", today)
        except Exception as exc:
            logger.warning("SafetyLayer: failed to load P&L snapshot from DB: %s", exc)

    def _persist_pnl_snapshot(self) -> None:
        """
        Write current daily P&L state to SQLite.

        Called synchronously after in-memory state is updated in sync_from_broker().
        DB failure is non-fatal - logged as a warning.
        """
        if self._db_manager is None:
            return
        try:
            today = date.today().isoformat()
            consecutive_losses = 0
            if self._loss_tracker is not None and hasattr(self._loss_tracker, "get_consecutive_losses"):
                consecutive_losses = self._loss_tracker.get_consecutive_losses()
            self._db_manager.upsert_pnl_snapshot(
                date=today,
                daily_pnl=self._daily_realized_pnl,
                portfolio_equity=self._current_equity,
                peak_equity=self._equity_peak,
                consecutive_losses=consecutive_losses,
            )
        except Exception as exc:
            logger.warning("SafetyLayer: failed to persist P&L snapshot to DB: %s", exc)

    def _load_kill_switch_state(self) -> None:
        """
        Read persisted kill switch state from SQLite on startup.

        If the DB is unavailable or the table does not yet exist, the kill
        switch remains inactive (fail-safe to trading paused, not trading
        enabled).  DB failure here is non-fatal - logged as a warning.
        """
        if self._db_path is None:
            logger.debug("SafetyLayer: no DB path - skipping kill switch state load")
            return
        try:
            import sqlite3
            conn = sqlite3.connect(self._db_path, timeout=5)
            conn.row_factory = sqlite3.Row
            try:
                row = conn.execute(
                    "SELECT value FROM system_state WHERE key = 'kill_switch_active'"
                ).fetchone()
                if row and row["value"] == "true":
                    reason_row = conn.execute(
                        "SELECT value FROM system_state WHERE key = 'kill_switch_reason'"
                    ).fetchone()
                    reason_str = reason_row["value"] if reason_row else None
                    self._kill_switch_active = True
                    if reason_str:
                        try:
                            self._kill_switch_reason = KillSwitchReason(reason_str)
                        except ValueError:
                            self._kill_switch_reason = KillSwitchReason.MANUAL
                    else:
                        self._kill_switch_reason = KillSwitchReason.MANUAL
                    logger.critical(
                        "SafetyLayer: kill switch restored from DB (reason=%s) - "
                        "trading remains HALTED until human deactivates",
                        self._kill_switch_reason.value if self._kill_switch_reason else "unknown",
                    )
                else:
                    logger.debug("SafetyLayer: kill switch not active in DB - starting clean")
            finally:
                conn.close()
        except Exception as exc:
            logger.warning("SafetyLayer: failed to load kill switch state from DB: %s", exc)

    def _persist_kill_switch_state(self, active: bool, reason: Optional[KillSwitchReason]) -> None:
        """
        Write kill switch state to SQLite.

        Called synchronously after in-memory state is updated.  DB failure is
        non-fatal - logged as a warning, the in-memory state change still takes
        effect immediately.
        """
        if self._db_path is None:
            return
        try:
            import sqlite3

            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
            active_str = "true" if active else "false"
            reason_str = reason.value if reason else ""
            conn = sqlite3.connect(self._db_path, timeout=5)
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO system_state (key, value, updated_at) VALUES (?, ?, ?)",
                    ("kill_switch_active", active_str, now),
                )
                conn.execute(
                    "INSERT OR REPLACE INTO system_state (key, value, updated_at) VALUES (?, ?, ?)",
                    ("kill_switch_reason", reason_str, now),
                )
                conn.commit()
                logger.debug(
                    "SafetyLayer: kill switch state persisted to DB (active=%s reason=%s)",
                    active_str, reason_str,
                )
            finally:
                conn.close()
        except Exception as exc:
            logger.warning("SafetyLayer: failed to persist kill switch state to DB: %s", exc)

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
        logger.critical(f"KILL SWITCH ACTIVATED: {reason.value}. {message}")
        # Persist state to SQLite (non-fatal if DB unavailable)
        self._persist_kill_switch_state(True, reason)
        # Log to PostgreSQL asynchronously (never block)
        _schedule_background_coro(
            lambda: self._log_safety_event(
                "kill_switch_activate",
                reason.value,
                {"reason": reason.value, "message": message},
            )
        )
        # OpenClaw WhatsApp alert (non-blocking, best-effort)
        try:
            from notifications.openclaw_notifier import notify_kill_switch as _oc_kill
        except Exception as exc:
            logger.debug("OpenClaw notifier unavailable: %s", exc)
        else:
            _reason_str = reason.value if hasattr(reason, "value") else str(reason)
            _schedule_background_coro(lambda: _oc_kill(reason=_reason_str, message=message))

    def deactivate_kill_switch(self, authorized_by: str = "human") -> None:
        """Resume trading. Only callable by human action (not by agents)."""
        self._kill_switch_active = False
        self._kill_switch_reason = None
        logger.info(f"Kill switch deactivated by: {authorized_by}")
        # Persist cleared state to SQLite (non-fatal if DB unavailable)
        self._persist_kill_switch_state(False, None)
        # Log to PostgreSQL asynchronously
        _schedule_background_coro(
            lambda: self._log_safety_event(
                "kill_switch_deactivate",
                f"Deactivated by {authorized_by}",
                {"authorized_by": authorized_by, "resolved": True},
            )
        )

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

    def _check_drawdown(self, portfolio_equity: float, warnings: list) -> RiskCheckResult:
        """Check max drawdown limits. Returns RiskCheckResult(approved=True) if passed."""
        if self._pnl_monitor is not None:
            drawdown = -self._pnl_monitor.get_drawdown_pct()
            if drawdown > self._config.MAX_DRAWDOWN_PCT:
                self.activate_kill_switch(
                    KillSwitchReason.MAX_DRAWDOWN,
                    f"Drawdown {drawdown:.1%} exceeded max {self._config.MAX_DRAWDOWN_PCT:.1%} (source: pnl_monitor)",
                )
                return RiskCheckResult(
                    approved=False, rejection_reason="Max drawdown breached - kill switch activated"
                )
            elif drawdown >= self._config.MAX_DRAWDOWN_PCT * 0.8:
                warnings.append(
                    f"Drawdown at {drawdown:.1%} - approaching {self._config.MAX_DRAWDOWN_PCT:.1%} limit"
                )
        elif self._equity_peak > 0:
            drawdown = (self._equity_peak - portfolio_equity) / self._equity_peak
            if drawdown > self._config.MAX_DRAWDOWN_PCT:
                self.activate_kill_switch(
                    KillSwitchReason.MAX_DRAWDOWN,
                    f"Drawdown {drawdown:.1%} exceeded max {self._config.MAX_DRAWDOWN_PCT:.1%}",
                )
                return RiskCheckResult(
                    approved=False, rejection_reason="Max drawdown breached - kill switch activated"
                )
            elif drawdown >= self._config.MAX_DRAWDOWN_PCT * 0.8:
                warnings.append(
                    f"Drawdown at {drawdown:.1%} - approaching {self._config.MAX_DRAWDOWN_PCT:.1%} limit"
                )
        return RiskCheckResult(approved=True, warnings=warnings)

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
                f"Consecutive losses: {consecutive_losses} - "
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
            if getattr(self._config, "ALLOW_PAPER_SIMULATED_ORDERS", False):
                # Explicit opt-in: route through simulated paper path, skip all gating
                return RiskCheckResult(approved=True)
            return RiskCheckResult(
                approved=False,
                rejection_reason="Live trading is disabled (LIVE_TRADING_ENABLED=False)",
            )
        if self._config.REQUIRE_HUMAN_APPROVAL:
            return RiskCheckResult(
                approved=False,
                rejection_reason="Human approval required (REQUIRE_HUMAN_APPROVAL=True) - this is normal in initial deployment",
            )
        return RiskCheckResult(approved=True)

    def _check_daily_loss_limit(self, portfolio_equity: float) -> RiskCheckResult:
        """Check daily loss limit."""
        daily_pnl = (
            self._pnl_monitor.get_daily_pnl() if self._pnl_monitor else self._daily_realized_pnl
        )
        if daily_pnl < -(portfolio_equity * self._config.MAX_DAILY_LOSS_PCT):
            self.activate_kill_switch(
                KillSwitchReason.DAILY_LOSS_LIMIT,
                f"Daily loss {daily_pnl:.2f} exceeded limit",
            )
            return RiskCheckResult(
                approved=False, rejection_reason="Daily loss limit breached - kill switch activated"
            )
        return RiskCheckResult(approved=True)

    def _check_order_value_limits(
        self, order: OrderRequest, portfolio_equity: float
    ) -> RiskCheckResult:
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

    def _check_order_rate(self) -> tuple[RiskCheckResult, float]:
        """Check order rate throttle. Returns (RiskCheckResult, timestamp)."""
        import time

        now = time.time()
        self._recent_order_timestamps = [t for t in self._recent_order_timestamps if now - t < 60]
        if len(self._recent_order_timestamps) >= self._config.MAX_ORDERS_PER_MINUTE:
            self.activate_kill_switch(
                KillSwitchReason.ANOMALOUS_ORDER_RATE,
                f"Order rate exceeded {self._config.MAX_ORDERS_PER_MINUTE}/min",
            )
            return (
                RiskCheckResult(
                    approved=False, rejection_reason="Anomalous order rate - kill switch activated"
                ),
                now,
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

        # Tilt detector check
        if self.tilt_detector is not None:
            tilt_state = self.tilt_detector.check()
            if tilt_state.position_size_multiplier == 0.0:
                return RiskCheckResult(
                    approved=False,
                    rejection_reason="Trading halted due to tilt detection (emotional/behavioral risk)",
                )
            elif tilt_state.severity in ("caution", "warning", "critical"):
                warnings.append(f"Tilt {tilt_state.severity}: behavioral risk indicators elevated")

        # Re-entry lockout check
        lockout_until = self._reentry_lockouts.get(order.symbol.upper())
        if lockout_until and datetime.now() < lockout_until:
            remaining = int((lockout_until - datetime.now()).total_seconds() / 60)
            return RiskCheckResult(
                approved=False,
                rejection_reason=f"RE_ENTRY_LOCKOUT: {order.symbol} locked out for {remaining} more minutes after stop-out",
            )

        # Loss tracker adjustment
        loss_result = self._apply_loss_tracker_adjustment(order, warnings)
        if isinstance(loss_result, RiskCheckResult):
            return loss_result
        adjusted_order, warnings = loss_result

        # All checks passed - log which broker will handle this order
        self._recent_order_timestamps.append(now)
        if adjusted_order.is_futures:
            broker_target = "IBKR (futures)"
        elif adjusted_order.is_options and self.schwab is not None:
            broker_target = "Schwab (options/equity)"
        else:
            broker_target = "IBKR (default)"
        import math as _math

        _est_val_display = (
            0
            if _math.isnan(adjusted_order.estimated_value)
            else int(adjusted_order.estimated_value)
        )
        logger.info(
            "Order approved: %s qty=%d est_value=$%d - routing to %s",
            adjusted_order.symbol,
            adjusted_order.quantity,
            _est_val_display,
            broker_target,
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
        No LLM reasoning happens here - pure deterministic gate.

        Parameters
        ----------
        symbol      : Ticker / futures root (e.g. "MES", "AAPL").
        action      : "BUY" or "SELL" (case-insensitive).
        quantity    : Positive integer - always pass the absolute lot size.
                      Direction is expressed via *action*.
        price       : Estimated execution price (used for value checks).
        order_type  : "MKT" (default) or "LMT".
        limit_price : Required when order_type == "LMT".

        Returns
        -------
        dict with keys:
            approved    (bool)   - True only when every safety check passed.
            reason      (str)    - Human-readable outcome (approval or rejection message).
            order_id    (str|None) - IB order ID string if the order was placed, else None.
            routed_to_ib (bool)  - True only when the order reached IB Gateway.
        """
        # ── 0. Kill switch - checked first, before anything else ──────────
        if self._kill_switch_active:
            reason = (
                f"Kill switch active: {self._kill_switch_reason.value}"
                if self._kill_switch_reason
                else "Kill switch active"
            )
            logger.warning(
                "submit_paper_order BLOCKED by kill switch - symbol=%s action=%s qty=%d: %s",
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
                "submit_paper_order REJECTED by SafetyLayer - symbol=%s action=%s qty=%d: %s",
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
                "submit_paper_order: safety checks PASSED - no IB gateway attached "
                "(dry-run mode). symbol=%s action=%s qty=%d",
                symbol,
                action,
                quantity,
            )
            return {
                "approved": True,
                "reason": "Safety checks passed - IB gateway not attached (dry-run)",
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
                "reason": "Safety checks passed - IB gateway not connected",
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
                "submit_paper_order ROUTED to IB Gateway (paper) - symbol=%s action=%s "
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
                "submit_paper_order: IB Gateway place_paper_order raised - symbol=%s: %s",
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

        # Persist P&L snapshot to SQLite so restarts don't lose intraday state
        self._persist_pnl_snapshot()

        # Auto-trigger daily loss check
        if daily_pnl < -(equity * self._config.MAX_DAILY_LOSS_PCT):
            self.activate_kill_switch(
                KillSwitchReason.DAILY_LOSS_LIMIT, f"Intraday sync: daily PnL {daily_pnl:.2f}"
            )

        # Push P&L alerts via AlertManager (deduped — each threshold fires once per day)
        if self._alert_manager is not None:
            try:
                daily_pnl_pct = (daily_pnl / equity) if equity > 0 else 0.0
                drawdown_pct = 0.0
                if self._pnl_monitor is not None and hasattr(self._pnl_monitor, "get_drawdown_pct"):
                    drawdown_pct = self._pnl_monitor.get_drawdown_pct()  # already negative (e.g. -0.08 = 8% down)
                elif self._equity_peak > 0:
                    drawdown_pct = -(self._equity_peak - equity) / self._equity_peak  # negative fraction
                consecutive_losses = 0
                if self._loss_tracker is not None and hasattr(
                    self._loss_tracker, "get_consecutive_losses"
                ):
                    consecutive_losses = self._loss_tracker.get_consecutive_losses()
                self._alert_manager.check_and_alert(
                    daily_pnl=daily_pnl,
                    daily_pnl_pct=daily_pnl_pct,
                    drawdown_pct=drawdown_pct,
                    consecutive_losses=consecutive_losses,
                    portfolio_equity=equity,
                )
            except Exception as _alert_exc:
                logger.warning("SafetyLayer: AlertManager.check_and_alert failed: %s", _alert_exc)

    def check_circuit_breakers(self) -> dict:
        """
        Return the current status of all circuit breakers as a single dict.

        This method is safe to call at any time - it does NOT activate the kill
        switch.  Use it for dashboard polling and the /safety/circuit-breakers
        API endpoint.

        Returns
        -------
        dict with keys:
            daily_pnl            (float)  - today's realized + unrealized P&L in $
            daily_limit          (float)  - maximum allowed daily loss in $ (negative)
            daily_pnl_pct        (float)  - daily P&L as fraction of starting balance
            daily_limit_pct      (float)  - configured daily loss limit (negative fraction)
            daily_limit_breached (bool)  - if daily loss limit has been breached
            drawdown_pct         (float)  - current drawdown from peak (negative)
            drawdown_limit_pct   (float)  - configured max drawdown (negative)
            drawdown_breached    (bool)  - if drawdown limit has been breached
            kill_switch_active   (bool)  - if emergency halt is engaged
            kill_switch_reason   (str)   - reason for kill switch if active
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

        # Set re-entry lockout after stop-out loss
        if pnl < 0:
            lockout_minutes = getattr(settings, "REENTRY_LOCKOUT_MINUTES", 240)
            self._reentry_lockouts[symbol.upper()] = datetime.now() + timedelta(
                minutes=lockout_minutes
            )
            logger.info("Re-entry lockout set for %s: %d minutes", symbol, lockout_minutes)

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

    def reset_daily_pnl(self) -> dict[str, float | str]:
        """
        Reset in-memory daily realized PnL counters (human / ops / testing).

        Does not modify PnLMonitor or broker snapshots - only SafetyLayer counters.
        """
        self._daily_realized_pnl = 0.0
        self._daily_order_count = 0
        logger.warning("Daily PnL counters reset via API")
        return {"status": "ok", "daily_realized_pnl": 0.0}

    def orders_in_last_minute(self) -> int:
        """Count of order timestamps in the rolling 60s window (for circuit-breaker UI)."""
        now = time.time()
        self._recent_order_timestamps = [t for t in self._recent_order_timestamps if now - t < 60]
        return len(self._recent_order_timestamps)

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

    def get_recommended_size(
        self,
        symbol: str,
        atr: float,
        account_value: float,
        current_drawdown: float = 0.0,
    ) -> dict:
        """
        Calculate recommended position size using ATR-based risk framework.

        ADVISORY ONLY - does not override hardcoded safety limits.
        If position_sizer recommends LESS than hardcoded max, use recommendation.
        If position_sizer recommends MORE than hardcoded max, use hardcoded max.

        Parameters
        ----------
        symbol : str
            Trading symbol (e.g., "MES", "MCL")
        atr : float
            Average True Range in points
        account_value : float
            Current account equity in dollars
        current_drawdown : float
            Current drawdown from peak as percentage (e.g., 5.5 for 5.5%)

        Returns
        -------
        dict with recommended position sizing details and hardcoded limits
        """
        try:
            from risk.position_sizer import calculate_position_size
        except ImportError:
            try:
                from engine.risk.position_sizer import calculate_position_size
            except ImportError:
                logger.error("[POSITION-SIZER] Failed to import calculate_position_size")
                return {
                    "error": "Position sizer module unavailable",
                    "symbol": symbol,
                    "recommended_contracts": 0,
                    "hardcoded_max_contracts": self._config.MAX_CONTRACTS_PER_INSTRUMENT,
                }

        # Map symbol to contract multiplier (futures only)
        multipliers = {
            "MES": 5.0,  # Micro E-mini S&P 500
            "MNQ": 2.0,  # Micro E-mini Nasdaq 100
            "M2K": 5.0,  # Micro E-mini Russell 2000
            "MCL": 10.0,  # Micro Crude Oil
            "MGC": 10.0,  # Micro Gold
            "MHG": 1.0,  # Micro Copper
            "MSI": 10.0,  # Micro Silver
            "ES": 50.0,  # E-mini S&P 500
            "NQ": 20.0,  # E-mini Nasdaq 100
            "RTY": 50.0,  # E-mini Russell 2000
            "CL": 100.0,  # Crude Oil
            "GC": 100.0,  # Gold
            "HG": 25.0,  # Copper
        }
        multiplier = multipliers.get(symbol.upper(), 5.0)

        # Call position_sizer with current config limits
        position_size = calculate_position_size(
            equity=account_value,
            risk_pct=1.0,  # 1% risk per trade
            atr=atr,
            contract_multiplier=multiplier,
            max_contracts=self._config.MAX_CONTRACTS_PER_INSTRUMENT,
            max_position_pct=self._config.MAX_POSITION_SIZE_PCT,
            drawdown_pct=current_drawdown,
        )

        recommended_contracts = min(
            position_size.contracts,
            self._config.MAX_CONTRACTS_PER_INSTRUMENT,
        )

        return {
            "symbol": symbol,
            "atr": atr,
            "account_value": account_value,
            "current_drawdown_pct": current_drawdown,
            "recommended_contracts": recommended_contracts,
            "position_sizer_contracts": position_size.contracts,
            "hardcoded_max_contracts": self._config.MAX_CONTRACTS_PER_INSTRUMENT,
            "hardcoded_max_position_pct": self._config.MAX_POSITION_SIZE_PCT,
            "risk_amount": position_size.risk_amount,
            "max_loss": position_size.max_loss,
            "sizing_method": position_size.sizing_method,
            "scale_factor": position_size.scale_factor,
        }

    def get_lockout_status(self, symbol: str) -> dict:
        """Return lockout status for a symbol."""
        lockout_until = self._reentry_lockouts.get(symbol.upper())
        if lockout_until and datetime.now() < lockout_until:
            remaining = int((lockout_until - datetime.now()).total_seconds() / 60)
            return {
                "locked": True,
                "symbol": symbol,
                "remaining_minutes": remaining,
                "lockout_until": lockout_until.isoformat(),
            }
        return {"locked": False, "symbol": symbol}

    async def _log_safety_event(
        self,
        event_type: str,
        reason: str,
        details: dict = None,
    ) -> None:
        """
        Log a safety event to PostgreSQL.

        Gracefully handles database unavailability - never blocks execution.

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
