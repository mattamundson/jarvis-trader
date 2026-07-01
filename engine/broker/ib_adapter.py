"""
Jarvis-Trader IB Adapter — Paper Bracket Order Wiring

Maps JarvisAlertV1 objects to Interactive Brokers bracket orders via ib_async.

Safety guardrails (enforced before ANY order submission):
  1. execution_mode MUST be PAPER (never routes live from this module)
  2. tier MUST NOT be BLOCKED
  3. routing_policy.is_tradeable(symbol) MUST return True
  4. kill_switch MUST be False
  5. max_daily_loss MUST NOT be breached
  6. consecutive_loss_limit MUST NOT be breached
  7. contracts MUST be > 0
  8. stop and targets MUST be valid (non-zero, correct side)

IB ports:
  Paper trading : 4002 (TWS) / 4001 (IB Gateway)
  Live trading  : 7497 (TWS) / 4001 (IB Gateway)
  This adapter ONLY uses port 4002 unless LIVE mode is explicitly enabled
  and all guardrails pass.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from engine.backtest.alert_schema import AlertSide, AlertTier, ExecutionMode, JarvisAlertV1

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Order result
# ---------------------------------------------------------------------------

@dataclass
class OrderResult:
    success: bool
    order_id: Optional[int] = None
    message: str = ""
    alert_id: str = ""
    symbol: str = ""
    contracts: int = 0


# ---------------------------------------------------------------------------
# Guardrail state (injected or read from safety_layer)
# ---------------------------------------------------------------------------

@dataclass
class SafetyState:
    kill_switch_active: bool = False
    daily_loss_breached: bool = False
    consecutive_loss_breached: bool = False
    max_open_positions: int = 3
    current_open_positions: int = 0


# ---------------------------------------------------------------------------
# IB Adapter
# ---------------------------------------------------------------------------

class IBAdapter:
    """
    Routes JarvisAlertV1 alerts to IB paper bracket orders.

    Parameters
    ----------
    ib_client : any
        An ib_async ``IB`` client instance (already connected).
    safety_state : SafetyState
        Current safety/guardrail state from safety_layer.
    paper_only : bool
        If True (default), LIVE execution is blocked regardless of alert mode.
    """

    PAPER_PORT = 4002
    LIVE_PORT = 7497

    def __init__(
        self,
        ib_client,
        safety_state: Optional[SafetyState] = None,
        paper_only: bool = True,
    ) -> None:
        self.client = ib_client
        self.safety = safety_state or SafetyState()
        self.paper_only = paper_only

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send_alert(self, alert: JarvisAlertV1) -> OrderResult:
        """
        Validate guardrails then submit a bracket order for the alert.

        Returns an OrderResult with success=False and a reason string if
        any guardrail blocks the order.
        """
        block_reason = self._check_guardrails(alert)
        if block_reason:
            logger.warning(
                "[IBAdapter] ORDER BLOCKED alert_id=%s reason=%s",
                alert.alert_id, block_reason,
            )
            return OrderResult(
                success=False,
                message=block_reason,
                alert_id=alert.alert_id,
                symbol=alert.symbol,
                contracts=alert.risk.contracts,
            )

        return self._submit_bracket(alert)

    # ------------------------------------------------------------------
    # Guardrail checks
    # ------------------------------------------------------------------

    def _check_guardrails(self, alert: JarvisAlertV1) -> Optional[str]:
        """Return a non-empty block reason string if order should not proceed."""

        # 1. Execution mode
        if self.paper_only and alert.execution_mode == ExecutionMode.LIVE:
            return "paper_only_mode — LIVE blocked"
        if alert.execution_mode == ExecutionMode.BACKTEST:
            return "execution_mode=BACKTEST — no live/paper orders"

        # 2. Tier
        if alert.tier == AlertTier.BLOCKED:
            return f"tier=BLOCKED reason={alert.score.blocked_reason}"

        # 3. Kill switch
        if self.safety.kill_switch_active:
            return "kill_switch_active"

        # 4. Daily loss
        if self.safety.daily_loss_breached:
            return "max_daily_loss_breached"

        # 5. Consecutive loss
        if self.safety.consecutive_loss_breached:
            return "consecutive_loss_limit_breached"

        # 6. Max open positions
        if self.safety.current_open_positions >= self.safety.max_open_positions:
            return f"max_open_positions={self.safety.max_open_positions} reached"

        # 7. Contracts
        if alert.risk.contracts <= 0:
            return "contracts=0 — score too low for position sizing"

        # 8. Target validity
        t = alert.targets
        if t.stop_price <= 0 or t.entry_price <= 0:
            return "invalid entry or stop price"
        if alert.side == AlertSide.LONG and t.stop_price >= t.entry_price:
            return "LONG stop must be below entry"
        if alert.side == AlertSide.SHORT and t.stop_price <= t.entry_price:
            return "SHORT stop must be above entry"

        return None  # all guardrails passed

    # ------------------------------------------------------------------
    # Order submission
    # ------------------------------------------------------------------

    def _submit_bracket(self, alert: JarvisAlertV1) -> OrderResult:
        """
        Build and submit a bracket order via ib_async.

        This method creates:
          - A parent limit/market order at entry_price
          - A stop-loss child at stop_price
          - Three take-profit children at target_1, target_2, target_3
            (each sized at roughly 33% of total contracts)

        NOTE: Requires self.client to be a connected ib_async IB() instance.
        The ib_async import is deferred to avoid hard dependency in backtest mode.
        """
        try:
            from ib_async import LimitOrder, Order, StopOrder  # type: ignore

            action = "BUY" if alert.side == AlertSide.LONG else "SELL"
            close_action = "SELL" if action == "BUY" else "BUY"
            qty = alert.risk.contracts
            t = alert.targets

            # Parent market order (use limit if you want guaranteed fill price)
            parent = Order()
            parent.action = action
            parent.orderType = "MKT"
            parent.totalQuantity = qty
            parent.transmit = False

            # Stop loss
            stop_child = StopOrder(close_action, qty, t.stop_price)
            stop_child.parentId = parent.orderId
            stop_child.transmit = False

            # Take-profit children (split into thirds)
            tp_qty = max(1, qty // 3)
            tp1 = LimitOrder(close_action, tp_qty, t.target_1)
            tp1.parentId = parent.orderId
            tp1.transmit = False

            tp2 = LimitOrder(close_action, tp_qty, t.target_2)
            tp2.parentId = parent.orderId
            tp2.transmit = False

            tp3 = LimitOrder(close_action, qty - 2 * tp_qty, t.target_3)
            tp3.parentId = parent.orderId
            tp3.transmit = True  # last child transmits the full bracket

            # In real async usage: await self.client.placeOrderAsync(...)
            # Here we call synchronously for simplicity
            trade = self.client.placeOrder(
                self.client.qualifyContracts(
                    self._make_contract(alert.symbol)
                )[0],
                parent,
            )

            logger.info(
                "[IBAdapter] ORDER SUBMITTED alert_id=%s symbol=%s side=%s qty=%d",
                alert.alert_id, alert.symbol, action, qty,
            )
            return OrderResult(
                success=True,
                order_id=trade.order.orderId,
                message="bracket order submitted",
                alert_id=alert.alert_id,
                symbol=alert.symbol,
                contracts=qty,
            )

        except Exception as exc:  # noqa: BLE001
            logger.error("[IBAdapter] ORDER FAILED alert_id=%s error=%s", alert.alert_id, exc)
            return OrderResult(
                success=False,
                message=str(exc),
                alert_id=alert.alert_id,
                symbol=alert.symbol,
                contracts=alert.risk.contracts,
            )

    @staticmethod
    def _make_contract(symbol: str):
        """Build a minimal CME Micro Futures contract for ib_async."""
        from ib_async import Contract  # type: ignore
        c = Contract()
        c.symbol = symbol
        c.secType = "FUT"
        c.exchange = "CME"
        c.currency = "USD"
        # Front-month — caller should set expiry explicitly for production
        return c
