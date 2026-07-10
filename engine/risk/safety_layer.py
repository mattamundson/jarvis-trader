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
from zoneinfo import ZoneInfo

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
    from utils.position_sizing import INSTRUMENT_MULTIPLIERS as _FUTURES_POINT_VALUE
except ImportError:
    from engine.utils.position_sizing import INSTRUMENT_MULTIPLIERS as _FUTURES_POINT_VALUE

try:
    from risk.loss_tracker import ConsecutiveLossTracker
except ImportError:
    try:
        from engine.risk.loss_tracker import ConsecutiveLossTracker
    except ImportError:
        ConsecutiveLossTracker = None  # type: ignore[assignment,misc]

try:
    from backtest.signals import DO_NOT_TRADE_SYMBOLS
except ImportError:
    from engine.backtest.signals import DO_NOT_TRADE_SYMBOLS

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
    EMERGENCY_FLATTEN = "emergency_flatten"


class HaltLevel(Enum):
    """Ordered escalation tiers for trading halt state.

    NORMAL → SOFT_HALT → HARD_HALT → EMERGENCY_FLATTEN is the escalation path.
    Downgrade (HARD_HALT → NORMAL) requires human deactivation via the API.
    """

    NORMAL = "normal"
    SOFT_HALT = "soft_halt"  # Position size reduced by loss tracker
    HARD_HALT = "hard_halt"  # Kill switch active — all new orders rejected
    EMERGENCY_FLATTEN = "emergency_flatten"  # Hard halt + positions being liquidated


# Symbols eligible to hold overnight (23h markets); subject to MAX_OVERNIGHT_CONTRACTS.
_OVERNIGHT_SYMBOLS: frozenset[str] = frozenset({"MES"})
_CT_ZONE = ZoneInfo("America/Chicago")
_OVERNIGHT_CUTOFF_HOUR = 15  # 15:00 CT â€” CME RTH close for equity futures

# IBKR overnight maintenance margin per contract (USD). These are the figures
# used by the futures-sizing gate when `order.is_futures=True`. Notional-based
# gating is wrong for futures: 1 MES is $7,130 notional but only ~$1,320 margin.
# Source: IBKR futures margin requirements 2026 (CME micro + mini). Conservative
# overnight figures â€” day-trade margin is lower. Update when IBKR revises.
_FUTURES_MARGIN_BY_ROOT: dict[str, float] = {
    # Micros
    "MES": 1320.0,  # E-mini S&P 500 micro
    "MNQ": 1780.0,  # E-mini Nasdaq-100 micro
    "M2K": 900.0,  # E-mini Russell 2000 micro
    "MCL": 1100.0,  # WTI crude micro
    "MGC": 1400.0,  # Gold micro
    "MHG": 600.0,  # Copper micro
    "MSI": 1500.0,  # Silver micro
    # Minis (roughly 10x the micros)
    "ES": 13200.0,
    "NQ": 17800.0,
    "RTY": 9000.0,
    "CL": 11000.0,
    "GC": 14000.0,
    "HG": 6000.0,
}

# Points-to-USD multiplier for futures loss estimation.
# Sourced from engine/utils/position_sizing.INSTRUMENT_MULTIPLIERS (imported above
# as _FUTURES_POINT_VALUE for back-compat). Used for the $50-per-trade-max-loss
# safety gate at line ~680.


def _futures_margin_required(symbol: str, quantity: int) -> float | None:
    """
    Return estimated IBKR maintenance margin in USD for `quantity` contracts
    of `symbol`, or None if the root is not in our margin table (caller falls
    back to notional-based gating).
    """
    margin_per = _FUTURES_MARGIN_BY_ROOT.get(symbol.upper())
    if margin_per is None:
        return None
    return margin_per * abs(quantity)


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
    stark_signal: str | None = None
    #: Originating strategy id, for the pre-trade promotion gate. None = untagged
    #: (manual/dashboard) order, governed by human-approval + gate-v2 elsewhere;
    #: automated strategy orders should populate this so the promotion gate can
    #: enforce that only promoted strategies reach a broker. Threading it through
    #: the executor construction sites is the Phase-2 follow-on.
    strategy_id: str | None = None


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

    def __init__(
        self,
        config,
        ib_gateway=None,
        pnl_monitor=None,
        loss_tracker=None,
        db_path: Optional[str] = None,
        db_manager=None,
    ):
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
            available source (IB Gateway â†’ SQLite â†’ in-memory tracker) rather
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
        self._emergency_flatten_activated: bool = False

        # Daily tracking (reset at market open)
        self._daily_realized_pnl: float = 0.0
        self._daily_order_count: int = 0
        self._daily_date: date = date.today()

        # Peak equity for drawdown calculation (from broker API, not agent)
        self._equity_peak: float = 0.0
        self._current_equity: float = 0.0

        # Orders per minute tracking
        self._recent_order_timestamps: list[float] = []

        # Tilt detector (optional â€” injected after construction)
        self.tilt_detector = None

        # Alert manager (optional â€” injected after construction via inject_alert_manager())
        self._alert_manager: Optional[object] = None  # AlertManager | None

        # Re-entry lockouts: symbol -> lockout_until datetime
        self._reentry_lockouts: dict[str, datetime] = {}

        # Resolve DB path for kill switch persistence
        self._db_path: Optional[str] = self._resolve_db_path(db_path)

        # Load persisted kill switch state
        self._load_kill_switch_state()

        # Restore today's P&L snapshot from SQLite if available
        self._load_pnl_snapshot()

        # Ensure equity_peak and current_equity are populated even when no
        # db_manager exists or snapshot was empty.  Without this, circuit
        # breakers are inert (daily_limit=0, drawdown check skipped).
        if self._equity_peak == 0.0 or self._current_equity == 0.0:
            self._seed_equity_from_pnl_monitor()

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
        logger.info("SafetyLayer: AlertManager injected â€” P&L push alerts active")

    # â”€â”€ Kill Switch DB Persistence â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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

        When snapshot data is incomplete (peak_equity=0), seeds from PnLMonitor
        or INITIAL_CAPITAL so circuit breakers are never inert.
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

    def _seed_equity_from_pnl_monitor(self) -> None:
        """
        Bootstrap _current_equity and _equity_peak from PnLMonitor or config.

        Called once at startup when snapshot restoration left values at 0.
        Source priority: PnLMonitor (SQLite) â†’ INITIAL_CAPITAL config.
        """
        # Try PnLMonitor first (reads SQLite daily_pnl table)
        if self._pnl_monitor is not None:
            try:
                state = self._pnl_monitor.get_current_pnl_state()
                balance = float(getattr(state, "current_balance", 0.0) or 0.0)
                if balance > 0:
                    if self._current_equity == 0.0:
                        self._current_equity = balance
                    if self._equity_peak == 0.0:
                        self._equity_peak = max(balance, self._current_equity)
                    logger.info(
                        "SafetyLayer: seeded from PnLMonitor â€” equity=%.2f peak=%.2f",
                        self._current_equity,
                        self._equity_peak,
                    )
                    self._persist_pnl_snapshot()
                    return
            except Exception as exc:
                logger.warning("SafetyLayer: PnLMonitor seed failed: %s", exc)

        # Fall back to configured INITIAL_CAPITAL
        try:
            initial = float(getattr(self._config, "INITIAL_CAPITAL", 0.0) or 0.0)
        except (TypeError, ValueError):
            initial = 0.0
        if initial > 0:
            if self._current_equity == 0.0:
                self._current_equity = initial
            if self._equity_peak == 0.0:
                self._equity_peak = max(initial, self._current_equity)
            logger.info(
                "SafetyLayer: seeded from INITIAL_CAPITAL â€” equity=%.2f peak=%.2f",
                self._current_equity,
                self._equity_peak,
            )
            self._persist_pnl_snapshot()

    def _persist_pnl_snapshot(self) -> None:
        """
        Write current daily P&L state to SQLite.

        Called synchronously after in-memory state is updated in sync_from_broker().
        DB failure is non-fatal - logged as a warning.
        """
        if self._db_manager is None:
            if not getattr(self, "_db_manager_warned", False):
                logger.warning(
                    "SafetyLayer: pnl_snapshots writes DISABLED â€” db_manager was not "
                    "passed to __init__. Kill-switch state will still persist via "
                    "db_path, but upsert_pnl_snapshot() will silently no-op every "
                    "60s sync. Pass db_manager=<DatabaseManager> to restore writes."
                )
                self._db_manager_warned = True
            return
        try:
            today = date.today().isoformat()
            consecutive_losses = 0
            if self._loss_tracker is not None and hasattr(
                self._loss_tracker, "get_consecutive_losses"
            ):
                consecutive_losses = self._loss_tracker.get_consecutive_losses()
            # Preserve realized_peak_equity from the existing snapshot row so
            # the C5 readiness criterion is not disrupted by upsert paths that
            # don't compute the realized (closed-trades-only) peak.
            existing_snap = self._db_manager.get_pnl_snapshot(today)
            realized_peak = existing_snap.get("realized_peak_equity") if existing_snap else None
            self._db_manager.upsert_pnl_snapshot(
                date=today,
                daily_pnl=self._daily_realized_pnl,
                portfolio_equity=self._current_equity,
                peak_equity=self._equity_peak,
                consecutive_losses=consecutive_losses,
                realized_peak_equity=realized_peak,
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
                    flatten_row = conn.execute(
                        "SELECT value FROM system_state WHERE key = 'emergency_flatten_activated'"
                    ).fetchone()
                    if flatten_row and flatten_row["value"] == "true":
                        self._emergency_flatten_activated = True
                        logger.critical(
                            "SafetyLayer: emergency flatten state restored from DB - "
                            "positions may still be open"
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
                flatten_str = "true" if self._emergency_flatten_activated else "false"
                conn.execute(
                    "INSERT OR REPLACE INTO system_state (key, value, updated_at) VALUES (?, ?, ?)",
                    ("emergency_flatten_activated", flatten_str, now),
                )
                conn.commit()
                logger.debug(
                    "SafetyLayer: kill switch state persisted to DB (active=%s reason=%s)",
                    active_str,
                    reason_str,
                )
            finally:
                conn.close()
        except Exception as exc:
            logger.warning("SafetyLayer: failed to persist kill switch state to DB: %s", exc)

    # â”€â”€ Kill Switch â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def activate_kill_switch(self, reason: KillSwitchReason | str, message: str = "") -> None:
        """Halt all trading. Requires human re-authorization to resume.

        State-transition-only side effects: the breach checks (drawdown, daily
        loss) call this on EVERY scan while a breach persists. Without a guard
        each call re-fired the OpenClaw alert, re-logged CRITICAL, and
        re-scheduled the bracket cancel — the ~10/min kill-switch alert spam.
        We now run the notify/persist/cancel side effects only on a real
        transition (inactive→active) or a change of reason; a re-activation on
        the same reason is a no-op beyond a debug line. The latch itself still
        requires a manual deactivate to clear (unchanged).
        """
        # Normalize reason first so the transition comparison is reliable.
        if isinstance(reason, str):
            try:
                reason = KillSwitchReason[reason]
            except KeyError:
                logger.warning(f"Unknown kill switch reason: {reason}")
                reason = KillSwitchReason.MANUAL

        already_active = self._kill_switch_active
        same_reason = already_active and self._kill_switch_reason == reason
        self._kill_switch_active = True
        self._kill_switch_reason = reason

        if same_reason:
            logger.debug(
                "Kill switch re-activation suppressed (already active: %s) — "
                "no duplicate alert/persist/cancel.",
                reason.value,
            )
            return

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

        # Account-level bracket cancel: prevent pending entry orders from
        # filling after halt (§6.7 — additive to per-trade STP/TP protection).
        # Leaves STP/TP children alive so already-open positions stay protected.
        _gw = self._ib_gateway

        async def _cancel_pending_bracket_entries() -> None:
            try:
                from brokers.active_bracket_registry import (
                    get_registry as _get_bracket_registry,
                )

                result = await _get_bracket_registry().cancel_all_entries(_gw)
                if result["cancelled"]:
                    logger.critical(
                        "activate_kill_switch: cancelled %d pending bracket entries: %s",
                        len(result["cancelled"]),
                        result["cancelled"],
                    )
                if result.get("errors"):
                    logger.error(
                        "activate_kill_switch: %d bracket cancel errors: %s",
                        len(result["errors"]),
                        result["errors"],
                    )
            except Exception as _exc:
                logger.warning(
                    "activate_kill_switch: bracket entry cancel raised (non-fatal): %s", _exc
                )

        _schedule_background_coro(_cancel_pending_bracket_entries)

    def deactivate_kill_switch(self, authorized_by: str = "human") -> None:
        """Resume trading. Only callable by human action (not by agents)."""
        self._kill_switch_active = False
        self._kill_switch_reason = None
        self._emergency_flatten_activated = False
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

    # ── Halt Level / Tiered Escalation ────────────────────────────────────────

    @property
    def current_halt_level(self) -> HaltLevel:
        """Synthesize existing state into a single escalation tier.

        Hierarchy (highest wins):
          EMERGENCY_FLATTEN > HARD_HALT > SOFT_HALT > NORMAL
        """
        if self._emergency_flatten_activated:
            return HaltLevel.EMERGENCY_FLATTEN
        if self._kill_switch_active:
            return HaltLevel.HARD_HALT
        if self._loss_tracker is not None and hasattr(
            self._loss_tracker, "get_position_size_multiplier"
        ):
            if self._loss_tracker.get_position_size_multiplier() < 1.0:
                return HaltLevel.SOFT_HALT
        return HaltLevel.NORMAL

    async def emergency_flatten_and_halt(self, reason: str = "emergency") -> dict:
        """Tiered escalation: hard halt + liquidate all open positions.

        Step 1: Activate kill switch (blocks new orders immediately, synchronous).
        Step 2: Mark emergency flatten activated (persisted to DB).
        Step 3: Liquidate all positions via MKT orders (async, best-effort).

        Returns a dict with halt_level, kill_switch_activated, flattened,
        order_ids, and errors from flatten_all_positions().
        """
        self.activate_kill_switch(
            KillSwitchReason.EMERGENCY_FLATTEN,
            f"Emergency flatten triggered: {reason}",
        )
        self._emergency_flatten_activated = True
        self._persist_kill_switch_state(True, self._kill_switch_reason)
        flatten_result = await self.flatten_all_positions()
        return {
            "halt_level": HaltLevel.EMERGENCY_FLATTEN.value,
            "kill_switch_activated": True,
            **flatten_result,
        }

    # ── Per-Account Kill Switch (parallel-paper only) ──────────────────────────
    # These functions are ADDITIVE — they do not modify the global kill switch.
    # All four are no-ops (fall back to global state) when ENABLE_PARALLEL_PAPER
    # is not set to "1", so existing single-account behavior is unchanged.

    def _parallel_paper_enabled(self) -> bool:
        """Return True iff ENABLE_PARALLEL_PAPER=1 is set in the environment."""
        import os

        return os.environ.get("ENABLE_PARALLEL_PAPER", "0") == "1"

    def get_per_account_kill_state(self, account_id: str) -> dict:
        """
        Return current per-account kill state from the DB.

        When ENABLE_PARALLEL_PAPER is not set, returns a synthetic record that
        mirrors the global kill switch state so callers can treat the return
        value uniformly.

        Returns
        -------
        dict with keys:
            account_id      (str)
            active          (bool)
            triggered_at    (str|None)
            reason          (str|None)
            trigger_metric  (str|None)
            trigger_value   (float|None)
            cleared_at      (str|None)
        """
        if not self._parallel_paper_enabled():
            return {
                "account_id": account_id,
                "active": self._kill_switch_active,
                "triggered_at": None,
                "reason": (self._kill_switch_reason.value if self._kill_switch_reason else None),
                "trigger_metric": None,
                "trigger_value": None,
                "cleared_at": None,
            }
        if self._db_path is None:
            return {
                "account_id": account_id,
                "active": False,
                "triggered_at": None,
                "reason": None,
                "trigger_metric": None,
                "trigger_value": None,
                "cleared_at": None,
            }
        try:
            import sqlite3

            conn = sqlite3.connect(self._db_path, timeout=5)
            conn.row_factory = sqlite3.Row
            try:
                row = conn.execute(
                    "SELECT * FROM per_account_kill_state WHERE account_id = ?",
                    (account_id,),
                ).fetchone()
            finally:
                conn.close()
            if row is None:
                return {
                    "account_id": account_id,
                    "active": False,
                    "triggered_at": None,
                    "reason": None,
                    "trigger_metric": None,
                    "trigger_value": None,
                    "cleared_at": None,
                }
            return {
                "account_id": account_id,
                "active": bool(row["active"]),
                "triggered_at": row["triggered_at"],
                "reason": row["reason"],
                "trigger_metric": row["trigger_metric"],
                "trigger_value": row["trigger_value"],
                "cleared_at": row["cleared_at"],
            }
        except Exception as exc:
            logger.warning(
                "SafetyLayer: get_per_account_kill_state(%s) failed: %s", account_id, exc
            )
            return {
                "account_id": account_id,
                "active": False,
                "triggered_at": None,
                "reason": None,
                "trigger_metric": None,
                "trigger_value": None,
                "cleared_at": None,
            }

    def trigger_per_account_kill(
        self, account_id: str, metric: str, value: float, reason: str
    ) -> None:
        """
        Halt a single paper account.

        Sets active=1 for account_id in per_account_kill_state.  Does NOT touch
        the global kill switch.  No-op when ENABLE_PARALLEL_PAPER is not set.

        Parameters
        ----------
        account_id:     'A' or 'B'
        metric:         trigger metric — 'max_daily_loss' | 'max_drawdown' | 'consecutive_loss'
        value:          actual metric value at trigger time (e.g. pnl=-$112.50)
        reason:         human-readable description
        """
        if not self._parallel_paper_enabled():
            logger.debug(
                "trigger_per_account_kill: ENABLE_PARALLEL_PAPER not set — no-op for %s",
                account_id,
            )
            return
        if self._db_path is None:
            logger.warning(
                "trigger_per_account_kill: no DB path — cannot persist state for %s", account_id
            )
            return
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        try:
            import sqlite3

            conn = sqlite3.connect(self._db_path, timeout=5)
            try:
                conn.execute(
                    """
                    INSERT INTO per_account_kill_state
                        (account_id, active, triggered_at, reason, trigger_metric, trigger_value, cleared_at)
                    VALUES (?, 1, ?, ?, ?, ?, NULL)
                    ON CONFLICT(account_id) DO UPDATE SET
                        active = 1,
                        triggered_at = excluded.triggered_at,
                        reason = excluded.reason,
                        trigger_metric = excluded.trigger_metric,
                        trigger_value = excluded.trigger_value,
                        cleared_at = NULL
                    """,
                    (account_id, now, reason, metric, value),
                )
                conn.commit()
            finally:
                conn.close()
            logger.critical(
                "PER-ACCOUNT KILL: account=%s metric=%s value=%s reason=%s",
                account_id,
                metric,
                value,
                reason,
            )
        except Exception as exc:
            logger.warning("trigger_per_account_kill(%s): DB write failed: %s", account_id, exc)

    def clear_per_account_kill(self, account_id: str, notes: str = "") -> None:
        """
        Resume a halted paper account.

        Sets active=0 and records cleared_at.  No-op when ENABLE_PARALLEL_PAPER
        is not set.  Human-only path — should be called from the /safety/account
        API route, not from automated risk checks.
        """
        if not self._parallel_paper_enabled():
            logger.debug(
                "clear_per_account_kill: ENABLE_PARALLEL_PAPER not set — no-op for %s",
                account_id,
            )
            return
        if self._db_path is None:
            return
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        try:
            import sqlite3

            conn = sqlite3.connect(self._db_path, timeout=5)
            try:
                conn.execute(
                    """
                    INSERT INTO per_account_kill_state
                        (account_id, active, triggered_at, reason, trigger_metric, trigger_value, cleared_at)
                    VALUES (?, 0, NULL, ?, NULL, NULL, ?)
                    ON CONFLICT(account_id) DO UPDATE SET
                        active = 0,
                        cleared_at = excluded.cleared_at,
                        reason = COALESCE(excluded.reason, reason)
                    """,
                    (account_id, notes or None, now),
                )
                conn.commit()
            finally:
                conn.close()
            logger.info(
                "SafetyLayer: per-account kill cleared for account=%s notes=%r",
                account_id,
                notes,
            )
        except Exception as exc:
            logger.warning("clear_per_account_kill(%s): DB write failed: %s", account_id, exc)

    def is_account_halted(self, account_id: str) -> bool:
        """
        Return True if this account should NOT emit orders.

        An account is halted if EITHER:
          1. The GLOBAL kill switch is active (defense in depth), OR
          2. ENABLE_PARALLEL_PAPER=1 AND the per-account kill is active for this account.

        When ENABLE_PARALLEL_PAPER is not set, this is equivalent to ``is_killed``.
        """
        if self._kill_switch_active:
            return True
        if not self._parallel_paper_enabled():
            return False
        state = self.get_per_account_kill_state(account_id)
        return bool(state.get("active", False))

    def get_status(self) -> dict:
        """Return safety layer status for agents.

        CONTRACT — both ``is_killed`` and ``kill_switch_active`` are emitted and
        MUST always carry the SAME value. The two names exist because callers
        historically read one or the other; emitting only one silently bypassed
        every gate that read the other (the 2026-06-15 inert-kill-switch defect
        spanned 12+ in-process gates: scanner, schedulers, pipeline_router,
        approval_queue, autonomous enqueue, agents). Do NOT "dedup" these keys —
        the redundancy is load-bearing. ``test_kill_switch_status_contract``
        enforces it; removing a key fails that test.
        """
        killed = self._kill_switch_active
        return {
            "is_killed": killed,
            "kill_switch_active": killed,  # alias — see contract note above; keep in lock-step
            "kill_switch_reason": (
                self._kill_switch_reason.value if self._kill_switch_reason else None
            ),
            "daily_realized_pnl": self._daily_realized_pnl,
            "equity_peak": self._equity_peak,
            "current_equity": self._current_equity,
            "recent_order_count": len(self._recent_order_timestamps),
        }

    # â”€â”€ Pre-Trade Checks â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
                f"(qty: {order.quantity} â†’ {adjusted_order.quantity})"
            )
            logger.warning(
                f"Position size reduction applied: {order.symbol} qty {order.quantity} â†’ "
                f"{adjusted_order.quantity} (multiplier={multiplier:.2f})"
            )
            return adjusted_order, warnings
        return order, warnings

    def _check_do_not_trade_symbols(self, order: OrderRequest) -> RiskCheckResult:
        """Hard block: never route an order for a halted symbol, regardless of caller."""
        if order.symbol.upper() in DO_NOT_TRADE_SYMBOLS:
            return RiskCheckResult(
                approved=False,
                rejection_reason=f"DO_NOT_TRADE_SYMBOLS: {order.symbol} is halted, no orders permitted",
            )
        return RiskCheckResult(approved=True)

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
        # Defensive read (matches the getattr pattern at line ~1705 and the
        # ALLOW_PAPER_SIMULATED_ORDERS read below): a config missing this flag
        # must NEVER enable live trading — default to False (paper / disabled).
        if not getattr(self._config, "LIVE_TRADING_ENABLED", False):
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
        """Check daily loss limit (both PCT and absolute USD)."""
        pnl_state = self._pnl_monitor.get_current_pnl_state() if self._pnl_monitor else None
        total_pnl = pnl_state.total_pnl if pnl_state else self._daily_realized_pnl
        realized_pnl = pnl_state.daily_realized_pnl if pnl_state else self._daily_realized_pnl

        # 1. Check relative limit (e.g. -2%) against TOTAL P&L (standard)
        rel_limit = -(portfolio_equity * self._config.MAX_DAILY_LOSS_PCT)
        if total_pnl < rel_limit:
            self.activate_kill_switch(
                KillSwitchReason.DAILY_LOSS_LIMIT,
                f"Daily total P&L {total_pnl:.2f} exceeded pct limit ({self._config.MAX_DAILY_LOSS_PCT:.1%})",
            )
            return RiskCheckResult(
                approved=False,
                rejection_reason="Daily loss pct limit reached - kill switch activated",
            )

        # 2. Check absolute limit (e.g. -$1,000) against REALIZED P&L (per Battle
        #    Plan) — but only latch when >=2 realized trades closed today. A lone
        #    breach is almost always a phantom/data error, since a real single
        #    trade is already capped at MAX_TRADE_LOSS_USD ($50/ticket). On
        #    2026-07-01 a single phantom -$266 latched this gate and halted
        #    trading for the day. min-2-trades policy (Amo, 2026-07-02). The PCT
        #    gate above (TOTAL P&L incl. open MTM) is intentionally UNCHANGED.
        #    Fail-safe: an unknown count (no db) preserves the old always-latch.
        abs_limit = -getattr(self._config, "MAX_DAILY_LOSS_USD", 100.0)
        if realized_pnl < abs_limit:
            trade_count = self._today_realized_trade_count()
            if trade_count is not None and trade_count < 2:
                logger.warning(
                    "[SafetyLayer] Daily realized loss %.2f breached flat USD limit "
                    "($%.0f) on only %d realized trade(s) today — likely a phantom; "
                    "NOT latching (min-2-trades gate).",
                    realized_pnl,
                    abs(abs_limit),
                    trade_count,
                )
            else:
                count_str = "unknown" if trade_count is None else str(trade_count)
                self.activate_kill_switch(
                    KillSwitchReason.DAILY_LOSS_LIMIT,
                    f"Daily realized loss {realized_pnl:.2f} exceeded flat USD limit "
                    f"(${abs(abs_limit):.0f}) across {count_str} trades",
                )
                return RiskCheckResult(
                    approved=False,
                    rejection_reason="Daily realized loss limit reached - kill switch activated",
                )

        return RiskCheckResult(approved=True)

    def _today_realized_trade_count(self) -> Optional[int]:
        """Count of closed paper_trades that exited today (UTC), or None.

        Feeds the flat USD daily-loss gate's min-2-trades guard. Returns None on
        any failure or when no db_manager is wired, so the caller fails SAFE
        (latches) rather than skipping a genuine breach.
        """
        db = self._db_manager
        if db is None or not hasattr(db, "count_closed_trades_on_date"):
            return None
        try:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            return int(db.count_closed_trades_on_date(today))
        except Exception as exc:
            logger.debug("[SafetyLayer] realized trade-count lookup failed: %s", exc)
            return None

    def _check_trade_loss_gate(self, order: OrderRequest) -> RiskCheckResult:
        """
        Damage control: reject any order where requested stop distance * qty
        exceeds MAX_TRADE_LOSS_USD ($50).
        """
        if order.stop_price is None:
            # Entry without stop is permitted by safety layer (e.g. manual flattening),
            # but usually blocked earlier by strategy policy for directional trades.
            return RiskCheckResult(approved=True)

        abs_qty = abs(order.quantity)
        entry_px = order.limit_price or order.estimated_value / abs_qty if abs_qty != 0 else 0
        if entry_px == 0:
            return RiskCheckResult(approved=True)  # Cannot compute risk without entry price

        points_at_risk = abs(entry_px - order.stop_price)

        if order.is_futures:
            multiplier = _FUTURES_POINT_VALUE.get(order.symbol.upper(), 1.0)
            dollar_risk = points_at_risk * multiplier * abs(order.quantity)
        else:
            # Equities / Options: Notional points * qty usually map 1:1 to USD for stocks,
            # or require complex Greeks for options. For now, use simple multiplier.
            dollar_risk = points_at_risk * abs(order.quantity)

        max_risk = getattr(self._config, "MAX_TRADE_LOSS_USD", 50.0)
        if dollar_risk > max_risk:
            return RiskCheckResult(
                approved=False,
                rejection_reason=(
                    f"TRADE_LOSS_LIMIT: Potential loss ${dollar_risk:.2f} "
                    f"exceeds max ${max_risk:.2f} per ticket "
                    f"({order.symbol} @ {entry_px:.2f}, stop {order.stop_price:.2f})"
                ),
            )

        return RiskCheckResult(approved=True)

    def _check_order_value_limits(
        self, order: OrderRequest, portfolio_equity: float
    ) -> RiskCheckResult:
        """
        Check order size and position size limits.

        Futures branch: uses IBKR maintenance margin (via `_FUTURES_MARGIN_BY_ROOT`)
        instead of notional value, and `MAX_FUTURES_MARGIN_PCT` instead of
        `MAX_POSITION_SIZE_PCT`. Notional-based gating is wrong for futures â€”
        1 MES at $7,130 notional is only ~$1,320 margin, so a notional-based
        5% cap would reject every futures order on a $10K account.

        Non-futures path: unchanged â€” notional vs `MAX_SINGLE_ORDER_VALUE` and
        `MAX_POSITION_SIZE_PCT`.

        Unknown futures root (not in `_FUTURES_MARGIN_BY_ROOT`): falls back to
        notional-based gating so unrecognized symbols never silently bypass.
        """
        if order.is_futures:
            margin = _futures_margin_required(order.symbol, order.quantity)
            if margin is not None:
                if portfolio_equity <= 0:
                    return RiskCheckResult(
                        approved=False,
                        rejection_reason="Cannot size futures order against zero portfolio equity",
                    )
                margin_pct = margin / portfolio_equity
                max_pct = getattr(self._config, "MAX_FUTURES_MARGIN_PCT", 0.30)
                if margin_pct > max_pct:
                    return RiskCheckResult(
                        approved=False,
                        rejection_reason=(
                            f"Futures margin {margin_pct:.1%} exceeds max {max_pct:.1%} "
                            f"(margin ${margin:,.0f} vs equity ${portfolio_equity:,.0f}, "
                            f"{abs(order.quantity)} {order.symbol.upper()})"
                        ),
                    )
                return RiskCheckResult(approved=True)
            # Unknown futures root â€” fall through to notional-based check below.

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
        """Check futures contract limits, including overnight cap after 15:00 CT."""
        if order.is_futures and abs(order.quantity) > self._config.MAX_CONTRACTS_PER_INSTRUMENT:
            return RiskCheckResult(
                approved=False,
                rejection_reason=f"Requested {abs(order.quantity)} contracts exceeds max {self._config.MAX_CONTRACTS_PER_INSTRUMENT}",
            )
        sym = order.symbol.upper()
        if order.is_futures and sym in _OVERNIGHT_SYMBOLS:
            now_ct = datetime.now(_CT_ZONE)
            if now_ct.hour >= _OVERNIGHT_CUTOFF_HOUR:
                limit = self._config.MAX_OVERNIGHT_CONTRACTS
                if abs(order.quantity) > limit:
                    logger.warning(
                        "OVERNIGHT_CONTRACT_LIMIT: %s rejected %d contracts after 15:00 CT (max %d)",
                        sym,
                        abs(order.quantity),
                        limit,
                    )
                    return RiskCheckResult(
                        approved=False,
                        rejection_reason=(
                            f"OVERNIGHT_LIMIT: {sym} allows max {limit} contract(s) after 15:00 CT, "
                            f"requested {abs(order.quantity)}"
                        ),
                    )
        return RiskCheckResult(approved=True)

    def _check_stark_tpo_constraint(self, order: OrderRequest) -> RiskCheckResult:
        """Ensure order strictly obeys the Stark-TPO math signal."""
        if order.stark_signal:
            sig = order.stark_signal.upper()
            if sig == "HOLD" and order.quantity != 0:
                return RiskCheckResult(
                    approved=False, rejection_reason="STARK_TPO_CONSTRAINT: Math edge demands HOLD."
                )
            if "LONG" in sig and order.quantity < 0:
                return RiskCheckResult(
                    approved=False,
                    rejection_reason=f"STARK_TPO_CONSTRAINT: Math demands {sig} but order is SHORT.",
                )
            if "SHORT" in sig and order.quantity > 0:
                return RiskCheckResult(
                    approved=False,
                    rejection_reason=f"STARK_TPO_CONSTRAINT: Math demands {sig} but order is LONG.",
                )
        return RiskCheckResult(approved=True)

    def _check_promotion_gate(self, order: OrderRequest) -> RiskCheckResult:
        """Hard pre-trade promotion gate: a strategy-tagged order may reach a
        broker only if its strategy is cleared for live capital.

        Scope: this gate governs *automated, strategy-tagged* orders. An untagged
        order (``strategy_id`` is None — manual/dashboard) is out of scope here;
        those are gated by human-approval + gate-v2 at approval time, so this check
        passes them through.

        Shadow-default OFF: when ``PROMOTION_GATE_ENFORCE`` is unset/false, an
        un-promoted strategy is *logged* (so impact is observable) but NOT blocked —
        identical-shape to the ``GATE_V2_ENFORCE_*`` flags. Flipping the flag makes
        the block hard (Amo Tier-3). Default-deny: a tagged strategy not in the
        (currently empty) promoted set is treated as un-promoted.
        """
        from backtest.live_promotion_gate import (  # noqa: PLC0415 — lazy, cycle-free
            is_strategy_promoted,
            promotion_gate_enforced,
        )

        sid = getattr(order, "strategy_id", None)
        if sid is None or is_strategy_promoted(sid):
            return RiskCheckResult(approved=True)

        # Strategy is tagged but NOT promoted.
        if not promotion_gate_enforced():
            logger.warning(
                "PROMOTION_GATE shadow: strategy '%s' is not cleared for live "
                "capital (order would be BLOCKED if PROMOTION_GATE_ENFORCE=1)",
                sid,
            )
            return RiskCheckResult(approved=True)

        return RiskCheckResult(
            approved=False,
            rejection_reason=(
                f"PROMOTION_GATE: strategy '{sid}' is not cleared for live capital "
                "(failed the enforced definition-of-done)"
            ),
        )

    def check_order(self, order: OrderRequest, portfolio_equity: float) -> RiskCheckResult:
        """
        Run all pre-trade safety checks.
        Returns approved=False if ANY check fails.
        Hard limits are non-negotiable.
        """
        warnings = []

        # Run sequential checks, return early on failure
        for check_fn in [
            lambda: self._check_do_not_trade_symbols(order),
            lambda: self._check_kill_switch(),
            lambda: self._check_gating_conditions(),
            lambda: self._check_promotion_gate(order),
            lambda: self._check_daily_loss_limit(portfolio_equity),
            lambda: self._check_drawdown(portfolio_equity, warnings),
            lambda: self._check_order_value_limits(order, portfolio_equity),
            lambda: self._check_trade_loss_gate(order),
            lambda: self._check_contract_limits(order),
            lambda: self._check_stark_tpo_constraint(order),
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

    # â”€â”€ Paper Order Submission (Safety â†’ IB Gateway) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    async def submit_paper_order(
        self,
        symbol: str,
        action: str,
        quantity: int,
        price: float,
        order_type: str = "MKT",
        limit_price: float | None = None,
        stop_price: float | None = None,
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
        # â”€â”€ 0. Kill switch - checked first, before anything else â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

        # â”€â”€ 1. Build an OrderRequest so we can re-use check_order() fully â”€
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
        # Normalise "MKT"â†’"market", "LMT"â†’"limit" for OrderRequest
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
            stop_price=stop_price,
            is_futures=is_futures,
            estimated_value=estimated_value,
        )

        # â”€â”€ 2. Full pre-trade safety gate â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

        # â”€â”€ 3. Route to IB Gateway if available â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

            # HB-1: Broker-side Stop Orders atomically linked
            if order_id is not None and stop_price is not None:
                stp_action = "SELL" if action_upper == "BUY" else "BUY"
                await self._ib_gateway.place_paper_order(
                    symbol=symbol,
                    action=stp_action,
                    quantity=quantity,
                    order_type="STP",
                    aux_price=stop_price,
                    parent_order_id=order_id,
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

    async def submit_paper_bracket_order(
        self,
        symbol: str,
        action: str,
        quantity: int,
        price: float,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        order_type: str = "MKT",
        limit_price: float | None = None,
    ) -> dict:
        """
        Place an atomic bracket order: Entry + Stop-Loss + Take-Profit (OCO).
        Runs safety checks for the entry order. If approved, exit legs are
        automatically linked in the paper simulator.
        """
        # ── 0. Kill switch check ──────────
        if self._kill_switch_active:
            return {
                "approved": False,
                "reason": "Kill switch active",
                "order_id": None,
                "routed_to_ib": False,
            }

        # ── 1. Validate the entry order risk ──────────
        action_upper = action.upper()
        signed_qty = quantity if action_upper == "BUY" else -quantity
        estimated_value = abs(quantity) * price

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

        req = OrderRequest(
            symbol=symbol.upper(),
            quantity=signed_qty,
            order_type=order_type.lower(),
            limit_price=limit_price,
            # stop_price MUST be wired through: _check_trade_loss_gate() short-
            # circuits to approved=True whenever order.stop_price is None, so
            # omitting it here made the $50/ticket MAX_TRADE_LOSS_USD gate a
            # no-op for every bracket order regardless of entry/stop distance
            # (part of the trade #287 root cause, alongside the caller-side
            # entry_price mis-wiring fixed in main.py's watchlist scan loop).
            stop_price=stop_loss,
            is_futures=is_futures,
            estimated_value=estimated_value,
        )

        portfolio_equity = self._current_equity if self._current_equity > 0 else estimated_value
        check_result = self.check_order(req, portfolio_equity)

        if not check_result.approved:
            return {
                "approved": False,
                "reason": check_result.rejection_reason or "Safety check failed",
                "order_id": None,
                "routed_to_ib": False,
            }

        # ── 2. Route bracket to IB Gateway (paper) ──────────
        if self._ib_gateway is None:
            return {
                "approved": False,
                "reason": "Broker connector unavailable",
                "order_id": None,
                "routed_to_ib": False,
            }

        final_order = check_result.adjusted_order or req
        result = await self._ib_gateway.place_bracket_order(
            symbol=final_order.symbol,
            action=action_upper,
            quantity=abs(int(final_order.quantity)),
            entry_type=final_order.order_type,
            limit_price=final_order.limit_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )

        if result.get("status") == "placed":
            return {
                "approved": True,
                "reason": "Bracket approved and routed to IBKR",
                "entry_id": result.get("entry_id"),
                "sl_id": result.get("sl_id"),
                "tp_id": result.get("tp_id"),
                "routed_to_ib": True,
                "warnings": check_result.warnings,
            }

        return {
            "approved": True,
            "reason": f"Safety check PASSED, but broker placement failed: {result.get('error')}",
            "order_id": None,
            "routed_to_ib": False,
        }

    async def _verify_parent_linkage(
        self,
        child_order_id: Optional[str],
        entry_id: str,
    ) -> bool:
        # True iff IB reports child_order_id with parent_order_id == entry_id.
        # Works for both IBGatewayConnector (paper) and IBGatewayManager (live).
        if child_order_id is None:
            return False
        try:
            status = await self._ib_gateway.get_order_status(str(child_order_id))
        except Exception as exc:
            logger.warning(
                "_verify_parent_linkage: get_order_status raised - child=%s: %s",
                child_order_id,
                exc,
            )
            return False
        if not isinstance(status, dict):
            return False
        parent = status.get("parent_order_id")
        if parent is None:
            return False
        return str(parent) == str(entry_id)

    async def submit_entry_with_stop(
        self,
        symbol: str,
        action: str,
        quantity: int,
        price: float,
        stop_price: float,
        target_price: Optional[float] = None,
    ) -> dict:
        """
        Submit a MKT entry + broker-side child STP, and (optionally) a child
        LMT take-profit, all linked to the same parent entry order.

        Closes HB-1 from the 2026-04-22 deployment-verification review:
        the trader agent computed stop_price but no code path submitted it
        to IBKR, so any engine crash mid-trade left positions unprotected.
        The optional TP (``target_price``) completes the bracket: symmetric
        engine-crash protection on winners, not just losers.

        Parameters
        ----------
        target_price : float, optional
            Take-profit limit price.  When provided, a LMT child is placed
            after the STP, linked to the same parent entry.  STP and TP are
            both opposite-side of the entry (BUY entry → SELL STP + SELL TP).
            Omit to submit entry + STP only (preserves pre-2026-04-23
            behavior).

        Returns
        -------
        dict with keys:
            approved       : entry passed SafetyLayer
            reason         : outcome message
            entry_order_id : broker id of the MKT entry (None if blocked)
            stp_order_id   : broker id of the STP child (None if entry blocked
                             or STP placement raised)
            stp_linked     : True iff the STP carries parent_order_id == entry
            tp_order_id    : broker id of the TP child (None if not requested,
                             entry blocked, or TP placement raised)
            tp_linked      : True iff the TP carries parent_order_id == entry
            routed_to_ib   : True iff entry reached IB Gateway
        """
        entry_res = await self.submit_paper_order(
            symbol=symbol,
            action=action,
            quantity=quantity,
            price=price,
            order_type="MKT",
            limit_price=None,
            stop_price=stop_price,
        )
        if not entry_res.get("approved") or not entry_res.get("routed_to_ib"):
            return {
                "approved": entry_res.get("approved", False),
                "reason": entry_res.get("reason", "Entry rejected"),
                "entry_order_id": entry_res.get("order_id"),
                "stp_order_id": None,
                "stp_linked": False,
                "tp_order_id": None,
                "tp_linked": False,
                "routed_to_ib": entry_res.get("routed_to_ib", False),
            }

        entry_id = entry_res["order_id"]
        child_action = "SELL" if action.upper() == "BUY" else "BUY"

        # --- Child STP (stop-loss) ---
        try:
            stp_id_raw = await self._ib_gateway.place_paper_order(
                symbol=symbol,
                action=child_action,
                quantity=quantity,
                order_type="STP",
                limit_price=None,
                aux_price=stop_price,
                parent_order_id=entry_id,
            )
            stp_id = str(stp_id_raw) if stp_id_raw is not None else None
        except Exception as exc:
            logger.error(
                "submit_entry_with_stop: STP child placement raised - symbol=%s: %s",
                symbol,
                exc,
                exc_info=True,
            )
            stp_id = None

        if stp_id is None:
            logger.critical(
                "submit_entry_with_stop: STP child failed — attempting to cancel entry "
                "order %s to prevent unprotected position (symbol=%s)",
                entry_id,
                symbol,
            )
            if self._ib_gateway is not None and hasattr(self._ib_gateway, "cancel_order"):
                try:
                    await self._ib_gateway.cancel_order(entry_id)
                    logger.critical(
                        "submit_entry_with_stop: entry order %s cancel submitted after STP failure (symbol=%s)",
                        entry_id,
                        symbol,
                    )
                except Exception as _ce:
                    logger.critical(
                        "submit_entry_with_stop: cancel of entry %s ALSO failed — position may be live without stop (symbol=%s): %s",
                        entry_id,
                        symbol,
                        _ce,
                    )
            else:
                logger.critical(
                    "submit_entry_with_stop: no cancel_order available — entry %s may be live without stop (symbol=%s)",
                    entry_id,
                    symbol,
                )
            return {
                "approved": False,
                "reason": "STP child placement failed — entry cancelled to prevent unprotected position",
                "entry_order_id": entry_id,
                "stp_order_id": None,
                "stp_linked": False,
                "tp_order_id": None,
                "tp_linked": False,
                "routed_to_ib": True,
            }

        # --- Child TP (take-profit) — opt-in via target_price ---
        tp_id: Optional[str] = None
        _live_trading = bool(getattr(settings, "LIVE_TRADING_ENABLED", False))
        if target_price is not None and not _live_trading:
            logger.info(
                "submit_entry_with_stop: TP placement skipped in paper mode "
                "(paper connector fills LMT immediately) — symbol=%s target=%.2f",
                symbol,
                float(target_price),
            )
        elif target_price is not None and _live_trading:
            try:
                tp_id_raw = await self._ib_gateway.place_paper_order(
                    symbol=symbol,
                    action=child_action,
                    quantity=quantity,
                    order_type="LMT",
                    limit_price=float(target_price),
                    aux_price=None,
                    parent_order_id=entry_id,
                )
                tp_id = str(tp_id_raw) if tp_id_raw is not None else None
            except Exception as exc:
                logger.error(
                    "submit_entry_with_stop: TP child placement raised - symbol=%s: %s",
                    symbol,
                    exc,
                    exc_info=True,
                )
                tp_id = None

        reason_parts = ["Entry"]
        if stp_id is not None:
            reason_parts.append("STP")
        if tp_id is not None:
            reason_parts.append("TP")
        reason = " + ".join(reason_parts) + " submitted"

        # Bump the bracket-trade sidecar counter consumed by /system/mes-sprint-gate.
        # Decoupled from paper_trades.notes because the writer chain is unreliable
        # (mirror path drops notes; some INSERT paths hardcode notes='').
        if stp_id is not None:
            try:
                import json as _json
                from pathlib import Path as _Path

                _sidecar = (
                    _Path(__file__).resolve().parent.parent / "data" / "bracket_trade_count.json"
                )
                _sidecar.parent.mkdir(parents=True, exist_ok=True)
                _state: dict = {}
                if _sidecar.exists():
                    try:
                        _state = _json.loads(_sidecar.read_text(encoding="utf-8")) or {}
                    except Exception:
                        _state = {}
                sym_upper = symbol.upper()
                sym_state = _state.setdefault(sym_upper, {"count": 0})
                sym_state["count"] = int(sym_state.get("count", 0) or 0) + 1
                sym_state["last_entry_order_id"] = entry_id
                sym_state["last_at"] = datetime.now(timezone.utc).isoformat()
                _sidecar.write_text(_json.dumps(_state), encoding="utf-8")
            except Exception as exc:  # noqa: BLE001 — counter must never block trade
                logger.warning("submit_entry_with_stop: bracket sidecar bump failed: %s", exc)

        return {
            "approved": True,
            "reason": reason,
            "entry_order_id": entry_id,
            "stp_order_id": stp_id,
            "stp_linked": await self._verify_parent_linkage(stp_id, entry_id),
            "tp_order_id": tp_id,
            "tp_linked": await self._verify_parent_linkage(tp_id, entry_id),
            "routed_to_ib": True,
        }

    async def flatten_all_positions(self) -> dict:
        """
        Emergency close of every open position via MKT orders.

        Used by POST /safety/flatten-all. Kill switch blocks new discretionary
        orders but leaves existing positions open; this is the operator path
        to liquidate them.
        """
        if self._ib_gateway is None:
            return {
                "flattened": [],
                "order_ids": [],
                "errors": [{"error": "No IB gateway attached"}],
            }

        try:
            positions = await self._ib_gateway.get_positions()
        except Exception as exc:
            return {
                "flattened": [],
                "order_ids": [],
                "errors": [{"error": f"get_positions raised: {exc}"}],
            }

        flattened: list[str] = []
        order_ids: list[str] = []
        errors: list[dict] = []

        for pos in positions or []:
            symbol = pos.get("symbol")
            qty = int(pos.get("position", 0) or 0)
            if not symbol or qty == 0:
                continue
            close_action = "SELL" if qty > 0 else "BUY"
            try:
                oid = await self._ib_gateway.place_paper_order(
                    symbol=symbol,
                    action=close_action,
                    quantity=abs(qty),
                    order_type="MKT",
                    limit_price=None,
                )
                if oid is not None:
                    flattened.append(symbol)
                    order_ids.append(str(oid))
                else:
                    errors.append({"symbol": symbol, "error": "place_paper_order returned None"})
            except Exception as exc:
                errors.append({"symbol": symbol, "error": str(exc)})

        logger.warning(
            "flatten_all_positions: closed=%d errors=%d",
            len(flattened),
            len(errors),
        )
        return {"flattened": flattened, "order_ids": order_ids, "errors": errors}

    # â”€â”€ Portfolio State Sync (from broker, NOT from agents) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def sync_from_broker(self, equity: float, daily_pnl: float) -> None:
        """
        Called every 60 seconds with ground truth from broker API.
        This is the ONLY way portfolio state is updated â€” never via agent memory.
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

        # Push P&L alerts via AlertManager (deduped â€” each threshold fires once per day)
        if self._alert_manager is not None:
            try:
                daily_pnl_pct = (daily_pnl / equity) if equity > 0 else 0.0
                drawdown_pct = 0.0
                if self._pnl_monitor is not None and hasattr(self._pnl_monitor, "get_drawdown_pct"):
                    drawdown_pct = (
                        self._pnl_monitor.get_drawdown_pct()
                    )  # already negative (e.g. -0.08 = 8% down)
                elif self._equity_peak > 0:
                    drawdown_pct = (
                        -(self._equity_peak - equity) / self._equity_peak
                    )  # negative fraction
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

        # Resolve best-available equity for circuit breaker math.
        # _current_equity may be 0 if sync_from_broker() was never called
        # (no broker connected).  PnLMonitor reads SQLite and is always fresh.
        equity_for_limits = self._current_equity
        if equity_for_limits <= 0 and self._pnl_monitor is not None:
            try:
                pm_state = self._pnl_monitor.get_current_pnl_state()
                equity_for_limits = float(getattr(pm_state, "current_balance", 0.0) or 0.0)
            except Exception as exc:
                logger.debug("SafetyLayer: PnLMonitor equity fallback failed: %s", exc)

        # Daily loss circuit breaker
        daily_limit = (
            -(equity_for_limits * self._config.MAX_DAILY_LOSS_PCT) if equity_for_limits > 0 else 0
        )
        daily_pnl_pct = (daily_pnl_for_check / equity_for_limits) if equity_for_limits > 0 else 0
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
            "kill_switch_reason": (
                self._kill_switch_reason.value if self._kill_switch_reason else None
            ),
        }

    # â”€â”€ Loss Tracking API â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
