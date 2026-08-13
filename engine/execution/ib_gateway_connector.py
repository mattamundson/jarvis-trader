"""
IB GATEWAY CONNECTOR — Paper Trading Foundation (March 2026)
==============================================================
Implements the Interactive Brokers API using IBKRpy (ib_insync wrapper).

STATUS: Paper trading mode READY for 30-day forward test.
Live connection to real IB Gateway NOT YET IMPLEMENTED.

When PAPER_TRADING=True:
  - All orders are simulated with small random slippage (0-2 ticks)
  - Fills logged to data/paper_trades.json
  - Account balances and positions are mocked but realistic
  - No actual orders sent to any broker

When PAPER_TRADING=False:
  - Will raise NotImplementedError("IB Gateway live connection not yet implemented")
  - Prevents accidental live trading before implementation is complete

INTERFACE:
  This connector matches the pattern of SchwabConnector and must implement:
  - connect() / disconnect()
  - is_connected() — method, same as IBGatewayManager / SafetyLayer.submit_paper_order
  - submit_order(), cancel_order(), get_order_status()
  - place_paper_order() — post-safety path for SafetyLayer routing
  - get_positions(), get_account_balance()
  - get_quote() (mock in paper mode)
  All methods are async except is_connected.
"""

from __future__ import annotations

import asyncio
import logging
import random
import uuid
from datetime import datetime
from enum import Enum
from typing import Callable, Optional

logger = logging.getLogger(__name__)

__all__ = ["IBGatewayConnector", "ConnectionState"]


class ConnectionState(Enum):
    """State transitions for IB Gateway connection."""

    CONNECTED = "connected"
    DISCONNECTING = "disconnecting"
    RECONNECTING = "reconnecting"
    FAILED = "failed"


_FUTURES_ROOTS = frozenset(
    {
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
)


class IBGatewayConnector:
    """
    Paper trading connector for Interactive Brokers Gateway.

    Provides a unified async interface for order management, position tracking,
    and market data. In paper trading mode, all orders are logged to JSON instead
    of sent to the broker.

    PAPER TRADING FLOW:
    1. Order submitted → validated by safety layer
    2. IBGatewayConnector receives order dict
    3. In paper mode: generate UUID, timestamp, calculate fill price with slippage
    4. Log to data/paper_trades.json
    5. Return immediate fill with realistic P&L

    When ready for live trading, replace order logging with actual IB API calls.
    """

    def __init__(self, settings, safety_layer, portfolio_tracker=None, trades_file=None):
        """
        Initialize the IB Gateway connector.

        Args:
            settings: TradingConfig with PAPER_TRADING, IBKR_HOST, IBKR_PORT, etc.
            safety_layer: RiskSafetyLayer for pre-trade validation
            portfolio_tracker: Optional ``PortfolioTracker`` — when set, paper fills
                can mirror to the engine API book via ``PaperTradeLogger`` (see execution README).
            trades_file: Optional ``Path`` override for the paper-fill JSON log,
                forwarded to ``PaperTradeLogger``. Tests MUST pass a ``tmp_path``
                value here — omitting it silently writes real fills into the
                production ``engine/data/paper_trades.json`` (2026-08-13 incident:
                offline connector tests polluted the live-readiness scoreboard).
        """
        self._settings = settings
        self._safety_layer = safety_layer
        self._portfolio_tracker = portfolio_tracker
        self._trades_file = trades_file
        self._connected = False
        self._ib_client = None  # Will hold ib_insync.IB() when live trading is implemented
        self._paper_trade_logger = None  # Lazy-loaded on first use
        self._market_data_manager = None  # Real-price source; attach_market_data()
        self._account_summary = {
            "equity": 10000.0,
            "cash": 10000.0,
            "buying_power": 40000.0,
        }
        self._positions = {}
        self._open_orders = {}

        # Connection resilience
        self._connection_state = ConnectionState.FAILED
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 3
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._sim_task: Optional[asyncio.Task] = None
        self._on_disconnect_callback: Optional[Callable] = None
        self._last_heartbeat: Optional[datetime] = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def connect(self) -> bool:
        """
        Connect to IB Gateway with resilience.

        In paper trading mode: just initializes local state and paper trade logger.
        In live mode: Would connect to IB Gateway at IBKR_HOST:IBKR_PORT.

        Returns:
            True if successfully connected (or in paper mode simulation)
        """
        if self._settings.PAPER_TRADING:
            logger.info(
                "IBGatewayConnector: Paper trading mode active. "
                "Orders will be logged to data/paper_trades.json"
            )
            # Initialize paper trade logger on first connect
            from execution.paper_trade_logger import PaperTradeLogger  # noqa: PLC0415

            self._paper_trade_logger = PaperTradeLogger(
                self._settings,
                portfolio_tracker=self._portfolio_tracker,
                trades_file=self._trades_file,
            )
            self._connected = True
            self._connection_state = ConnectionState.CONNECTED
            self._reconnect_attempts = 0
            self._last_heartbeat = datetime.utcnow()

            # Notify safety layer of connection state change
            self._notify_connection_state(ConnectionState.CONNECTED)

            # Start heartbeat monitoring if not already running
            if self._heartbeat_task is None or self._heartbeat_task.done():
                self._heartbeat_task = asyncio.create_task(self._heartbeat())

            # Start paper sim loop if not already running (Phase 2.3)
            if self._sim_task is None or self._sim_task.done():
                self._sim_task = asyncio.create_task(self._paper_sim_loop())

            logger.info(
                "IBGatewayConnector: Connected. Heartbeat started. State=%s",
                self._connection_state.value,
            )
            return True

        # Live mode: not yet implemented
        logger.error(
            "IBGatewayConnector: Live connection to IB Gateway not yet implemented. "
            "Set PAPER_TRADING=True for now."
        )
        self._connected = False
        self._connection_state = ConnectionState.FAILED
        self._notify_connection_state(ConnectionState.FAILED)
        return False

    async def disconnect(self) -> bool:
        """
        Disconnect from IB Gateway.

        In paper trading mode: just clears local state.
        In live mode: Would disconnect from IB Gateway.

        Returns:
            True if successfully disconnected
        """
        self._connection_state = ConnectionState.DISCONNECTING
        logger.info("IBGatewayConnector: Disconnecting. State=%s", self._connection_state.value)

        # Cancel heartbeat task if running
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                logger.debug("IBGatewayConnector: Heartbeat task cancelled")

        if self._ib_client:
            try:
                # Phase 3 (live trading): call self._ib_client.disconnect() for clean shutdown
                pass
            except Exception as exc:
                logger.error("Error disconnecting from IB Gateway: %s", exc)

        self._connected = False
        self._connection_state = ConnectionState.FAILED
        self._notify_connection_state(ConnectionState.FAILED)
        logger.info("IBGatewayConnector: Disconnected")
        return True

    def is_connected(self) -> bool:
        """Return True if connected to IB Gateway (or in paper trading simulation)."""
        return self._connected

    async def _reconnect(self) -> bool:
        """
        Attempt to reconnect with exponential backoff.

        Retries: 3 attempts at 2s, 4s, 8s intervals
        On persistent failure, logs CRITICAL and emits safety event

        Returns:
            True if reconnect succeeded, False if all retries exhausted
        """
        if self._reconnect_attempts >= self._max_reconnect_attempts:
            logger.critical(
                "IBGatewayConnector: Max reconnect attempts (%d) exhausted. Connection FAILED.",
                self._max_reconnect_attempts,
            )
            self._connection_state = ConnectionState.FAILED
            self._notify_connection_state(ConnectionState.FAILED)
            return False

        self._reconnect_attempts += 1
        backoff_seconds = 2**self._reconnect_attempts  # 2, 4, 8
        logger.warning(
            "IBGatewayConnector: Reconnect attempt %d/%d. " "Waiting %d seconds before retry.",
            self._reconnect_attempts,
            self._max_reconnect_attempts,
            backoff_seconds,
        )

        self._connection_state = ConnectionState.RECONNECTING
        self._notify_connection_state(ConnectionState.RECONNECTING)

        await asyncio.sleep(backoff_seconds)

        # Attempt reconnect
        success = await self.connect()
        if success:
            logger.info(
                "IBGatewayConnector: Reconnection succeeded on attempt %d",
                self._reconnect_attempts,
            )
            self._connection_state = ConnectionState.CONNECTED
            self._notify_connection_state(ConnectionState.CONNECTED)
            return True

        # If still failed, try next retry
        return await self._reconnect()

    async def _heartbeat(self) -> None:
        """
        Monitor connection health every 5 seconds.

        Checks if connection is still active.
        If TCP dropout exceeds 15 seconds, triggers DEADMAN SWITCH to flatten positions.
        """
        heartbeat_interval = 5
        timeout_threshold = 15

        while True:
            try:
                if not self._connected:
                    logger.warning(
                        "IBGatewayConnector: Heartbeat detected disconnection. "
                        "Triggering auto-reconnect."
                    )
                    self._reconnect_attempts = 0
                    await self._reconnect()
                else:
                    now = datetime.utcnow()
                    if self._last_heartbeat:
                        delta = (now - self._last_heartbeat).total_seconds()
                        if delta > timeout_threshold and not self._settings.PAPER_TRADING:
                            logger.critical(
                                f"IBGatewayConnector: Connectivity delta {delta:.1f}s exceeded "
                                f"{timeout_threshold}s limit! TRIGGERING DEADMAN SWITCH."
                            )
                            await self._trigger_deadman_switch()

                    # Simulated update of heartbeat for paper mode
                    self._last_heartbeat = now
                    logger.debug(
                        "IBGatewayConnector: Heartbeat OK. State=%s",
                        self._connection_state.value,
                    )

                await asyncio.sleep(heartbeat_interval)

            except asyncio.CancelledError:
                logger.debug("IBGatewayConnector: Heartbeat task cancelled")
                break

    async def _paper_sim_loop(self) -> None:
        """
        Background task for paper trading simulation.
        Checks open stop/limit orders against current prices and triggers fills.
        Also implements OCO cancellation.
        """
        while True:
            try:
                if not self._settings.PAPER_TRADING or not self._connected:
                    await asyncio.sleep(5)
                    continue

                # 1. Collect symbols needing quotes
                symbols = {
                    o["symbol"] for o in self._open_orders.values() if o["status"] == "pending"
                }
                if not symbols:
                    await asyncio.sleep(2)
                    continue

                # 2. Update quotes
                for symbol in symbols:
                    quote = await self.get_quote(symbol)
                    if not quote or "last" not in quote:
                        continue

                    price = quote["last"]

                    # 3. Check for fills
                    to_fill = []
                    for oid, order in self._open_orders.items():
                        if order["symbol"] != symbol or order["status"] != "pending":
                            continue

                        qty = order["quantity"]
                        filled = False

                        if order["order_type"] == "stop":
                            stop_px = order.get("stop_price")
                            if stop_px:
                                if (qty > 0 and price >= stop_px) or (qty < 0 and price <= stop_px):
                                    filled = True
                        elif order["order_type"] == "limit":
                            limit_px = order.get("limit_price")
                            if limit_px:
                                if (qty > 0 and price <= limit_px) or (qty < 0 and price >= limit_px):
                                    filled = True

                        if filled:
                            to_fill.append((oid, price))

                    # 4. Execute fills and OCO
                    for oid, fill_px in to_fill:
                        await self._fill_paper_order(oid, fill_px)

                await asyncio.sleep(1)  # Poll every second for simulation

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"IBGatewayConnector: Simulation loop error: {e}")
                await asyncio.sleep(5)

    async def _fill_paper_order(self, order_id: str, price: float):
        """Execute a paper fill for a pending stop/limit order."""
        order = self._open_orders.get(order_id)
        if not order or order["status"] != "pending":
            return

        order["status"] = "filled"
        order["filled_price"] = price
        order["fill_time"] = datetime.utcnow().isoformat() + "Z"

        symbol = order["symbol"]
        qty = order["quantity"]

        # Update position
        if symbol not in self._positions:
            self._positions[symbol] = 0
        self._positions[symbol] += qty

        # Update cash
        self._account_summary["cash"] -= qty * price

        logger.info("[SIM] Paper order %s FILLED @ %.2f (OCO-active)", order_id, price)

        # Log via PaperTradeLogger
        try:
            if self._paper_trade_logger:
                await self._paper_trade_logger.log_trade(
                    {
                        "order_id": order_id,
                        "symbol": symbol,
                        "quantity": qty,
                        "order_type": order["order_type"],
                        "filled_price": price,
                        "fill_time": order["fill_time"],
                        "is_futures": order.get("is_futures", False),
                    }
                )
        except Exception as exc:
            logger.error("Failed to log sim fill: %s", exc)

        # OCO Cancellation
        oco_id = order.get("oco_peer_id")
        if oco_id and oco_id in self._open_orders:
            oco_order = self._open_orders[oco_id]
            if oco_order["status"] == "pending":
                oco_order["status"] = "cancelled"
                logger.info("[SIM] OCO cancelled peer order: %s", oco_id)

    async def _trigger_deadman_switch(self) -> None:
        """
        Emergency liquidation protocol.
        Loops through all active positions and hits the bid/ask with MARKET orders
        to neutralize margin exposure immediately due to communication loss.
        """
        self._connection_state = ConnectionState.FAILED
        self._notify_connection_state(ConnectionState.FAILED)

        positions = await self.get_positions()
        for pos in positions:
            qty = pos.get("position", 0)
            if qty == 0:
                continue

            symbol = pos.get("symbol")
            is_futures = pos.get("is_futures", False)
            # Inverse the quantity to flatten
            action = "SELL" if qty > 0 else "BUY"
            abs_qty = abs(qty)

            logger.critical(f"DEADMAN SWITCH: Flattening {abs_qty} {symbol} ({action} MKT)")
            await self.submit_order(
                {
                    "symbol": symbol,
                    "quantity": -qty if qty > 0 else abs_qty,
                    "order_type": "market",
                    "is_futures": is_futures,
                },
                self._account_summary["equity"],
            )

    def _notify_connection_state(self, state: ConnectionState) -> None:
        """
        Notify safety layer of connection state changes.

        Args:
            state: New connection state
        """
        try:
            if hasattr(self._safety_layer, "on_connection_state_change"):
                self._safety_layer.on_connection_state_change(state)
                logger.debug(
                    "IBGatewayConnector: SafetyLayer notified of state change: %s",
                    state.value,
                )
        except Exception as exc:
            logger.error(
                "IBGatewayConnector: Failed to notify SafetyLayer of state change: %s",
                exc,
                exc_info=True,
            )

    def set_on_disconnect_callback(self, callback: Callable[[ConnectionState], None]) -> None:
        """
        Register a callback to be invoked on disconnect events.

        Args:
            callback: Callable that accepts a ConnectionState enum value
        """
        self._on_disconnect_callback = callback
        logger.debug("IBGatewayConnector: Disconnect callback registered")

    # ── Order Execution ───────────────────────────────────────────────────────

    async def submit_order(self, order: dict, portfolio_equity: float) -> dict:
        """
        Submit an order (futures, equity, or options).

        In paper trading mode:
          - Logs order to data/paper_trades.json
          - Simulates immediate fill with 0-2 tick slippage
          - Returns order dict with order_id, filled_price, slippage

        In live mode:
          - Would send order to IB Gateway via ib_insync API
          - Return live broker order ID and status

        Args:
            order: Order dict with symbol, quantity, order_type, limit_price, etc.
            portfolio_equity: Current portfolio equity (for risk checks)

        Returns:
            {
                "status": "placed" | "rejected" | "error",
                "order_id": str,  # UUID in paper mode, broker ID in live
                "symbol": str,
                "quantity": int,
                "order_type": str,
                "filled_price": float,
                "slippage_ticks": int,
                "fill_time": str,  # ISO 8601 timestamp
            }
        """
        if not self.is_connected():
            logger.error("IBGatewayConnector: Not connected")
            return {"status": "error", "reason": "Not connected to IB Gateway"}

        symbol = order.get("symbol", "UNKNOWN")
        quantity = int(order.get("quantity", 0))
        order_type = order.get("order_type", "market")
        limit_price = order.get("limit_price")
        is_futures = order.get("is_futures", False)
        is_options = order.get("is_options", False)

        logger.info(
            "IBGatewayConnector.submit_order | symbol=%s qty=%d type=%s limit=%s "
            "is_futures=%s is_options=%s equity=$%.0f",
            symbol,
            quantity,
            order_type,
            limit_price,
            is_futures,
            is_options,
            portfolio_equity,
        )

        # ── Safety layer check (mandatory) ────────────────────────────────────
        from risk.safety_layer import OrderRequest  # noqa: PLC0415

        order_req = OrderRequest(
            symbol=symbol,
            quantity=quantity,
            order_type=order_type,
            limit_price=limit_price,
            is_futures=is_futures,
            is_options=is_options,
        )

        risk_result = self._safety_layer.check_order(order_req, portfolio_equity)
        if not risk_result.approved:
            logger.warning(
                "IBGatewayConnector order REJECTED by safety layer | symbol=%s reason=%s",
                symbol,
                risk_result.rejection_reason,
            )
            return {
                "status": "rejected",
                "reason": risk_result.rejection_reason,
                "warnings": risk_result.warnings,
            }

        if risk_result.warnings:
            for w in risk_result.warnings:
                logger.warning("IBGatewayConnector order warning | %s", w)

        # PRB-01: check_order() may return an adjusted_order with a reduced
        # quantity (loss-tracker de-risking after consecutive losses). The
        # order actually filled below MUST reflect that reduced size, not the
        # caller's original `quantity` -- discarding adjusted_order here
        # previously meant the safety layer believed it had de-risked while
        # full-size paper fills still went out (2026-07-29 prod-readiness
        # audit). This is the OrderRouter's live futures/equity paper path.
        final_order = risk_result.adjusted_order or order_req
        final_quantity = int(final_order.quantity)
        if final_quantity != quantity:
            logger.warning(
                "IBGatewayConnector.submit_order: risk-adjusted size %d -> %d for symbol=%s",
                quantity,
                final_quantity,
                symbol,
            )
            order = {**order, "quantity": final_quantity}

        # ── Paper trading: simulate fill with slippage ────────────────────────
        if self._settings.PAPER_TRADING:
            return await self._submit_paper_order(order, risk_result.warnings)

        # ── Live trading: not yet implemented ─────────────────────────────────
        raise NotImplementedError(
            "IB Gateway live connection not yet implemented. "
            "Set PAPER_TRADING=True for paper trading mode."
        )

    async def _submit_paper_order(self, order: dict, warnings: list[str]) -> dict:
        """
        Simulate order submission in paper trading mode.

        Generates a fill price with small random slippage (0-2 ticks),
        logs to paper_trades.json, and returns immediate fill.
        """
        symbol = order.get("symbol", "UNKNOWN")
        quantity = int(order.get("quantity", 0))
        order_type = order.get("order_type", "market")
        limit_price = order.get("limit_price")
        is_futures = order.get("is_futures", False)

        # Generate order ID (UUID for paper trades)
        order_id = str(uuid.uuid4())

        # Get market quote (mock for paper trading). A transient quote-feed
        # failure must not abort the simulated fill — degrade to the same
        # fallback the no-quote branch already uses (limit_price or 100.0).
        try:
            quote = await self.get_quote(symbol)
        except Exception as exc:
            logger.warning(
                "IBGatewayConnector: get_quote raised for %s (%s) — using fallback price",
                symbol,
                exc,
            )
            quote = None
        if not quote or "error" in quote:
            # No live price and no mock entry. A limit price is still a valid
            # basis; otherwise REFUSE to book a phantom fill (the old code
            # defaulted to 100.0, which poisoned paper_trades). 2026-06-22 fix.
            if limit_price and limit_price > 0:
                mid_price = limit_price
            else:
                logger.warning(
                    "IBGatewayConnector: no price for %s and no limit_price — "
                    "rejecting paper order (refusing phantom fill)",
                    symbol,
                )
                return {
                    "status": "rejected",
                    "reason": "no_price_basis",
                    "order_id": order_id,
                    "symbol": symbol,
                    "filled": False,
                }
        else:
            mid_price = quote.get("mid") or quote.get("last") or (limit_price or 0.0)
            if not mid_price or mid_price <= 0:
                if limit_price and limit_price > 0:
                    mid_price = limit_price
                else:
                    logger.warning(
                        "IBGatewayConnector: non-positive price for %s — "
                        "rejecting paper order (refusing phantom fill)",
                        symbol,
                    )
                    return {
                        "status": "rejected",
                        "reason": "no_price_basis",
                        "order_id": order_id,
                        "symbol": symbol,
                        "filled": False,
                    }

        # Calculate fill price with slippage (0-2 ticks)
        # For futures: tick size is 0.25 (1 point = 4 ticks)
        # For equities/options: tick size varies but use 0.01 for simplicity
        tick_size = 0.25 if is_futures else 0.01
        slippage_ticks = random.randint(0, 2)
        slippage_direction = 1 if quantity > 0 else -1  # Buy: ask side, Sell: bid side
        slippage_amount = slippage_ticks * tick_size * slippage_direction
        filled_price = mid_price + slippage_amount

        fill_time = datetime.utcnow().isoformat() + "Z"

        # Log to paper trades file
        try:
            if self._paper_trade_logger is None:
                from execution.paper_trade_logger import PaperTradeLogger  # noqa: PLC0415

                self._paper_trade_logger = PaperTradeLogger(
                    self._settings,
                    portfolio_tracker=self._portfolio_tracker,
                    trades_file=self._trades_file,
                )

            await self._paper_trade_logger.log_trade(
                {
                    "order_id": order_id,
                    "symbol": symbol,
                    "quantity": quantity,
                    "order_type": order_type,
                    "limit_price": limit_price,
                    "filled_price": filled_price,
                    "slippage_ticks": slippage_ticks,
                    "fill_time": fill_time,
                    "is_futures": is_futures,
                }
            )
        except Exception as exc:
            logger.error("Failed to log paper trade: %s", exc, exc_info=True)

        # Update local positions for subsequent balance queries
        if symbol not in self._positions:
            self._positions[symbol] = 0
        self._positions[symbol] += quantity

        # Update cash balance
        trade_value = abs(quantity) * filled_price
        if quantity > 0:
            self._account_summary["cash"] -= trade_value
        else:
            self._account_summary["cash"] += trade_value

        logger.info(
            "IBGatewayConnector paper order FILLED | order_id=%s symbol=%s qty=%d "
            "filled_price=%.2f slippage=%d ticks fill_time=%s",
            order_id,
            symbol,
            quantity,
            filled_price,
            slippage_ticks,
            fill_time,
        )

        result = {
            "status": "placed",
            "order_id": order_id,
            "symbol": symbol,
            "quantity": quantity,
            "order_type": order_type,
            "limit_price": limit_price,
            "filled_price": filled_price,
            "slippage_ticks": slippage_ticks,
            "fill_time": fill_time,
            "is_futures": is_futures,
        }
        if warnings:
            result["warnings"] = warnings

        return result

    async def place_bracket_order(
        self,
        symbol: str,
        action: str,
        quantity: int,
        entry_type: str = "MKT",
        limit_price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> dict:
        """
        Place an atomic bracket order: Entry + Stop-Loss + Take-Profit (OCO).
        Implements Phase 2.3 OMS v2 logic for futures.
        """
        if not self.is_connected():
            return {"status": "error", "error": "Not connected"}

        # 1. Place the main entry order
        entry_id = await self.place_paper_order(
            symbol=symbol,
            action=action,
            quantity=quantity,
            order_type=entry_type,
            limit_price=limit_price,
        )

        if not entry_id:
            return {"status": "error", "error": "Failed to place entry order"}

        # 2. Setup the exit legs (linked via parent_order_id)
        exit_action = "SELL" if action.upper() == "BUY" else "BUY"
        sl_id = None
        tp_id = None

        if stop_loss:
            sl_id = await self.place_paper_order(
                symbol=symbol,
                action=exit_action,
                quantity=quantity,
                order_type="STP",
                aux_price=stop_loss,
                parent_order_id=entry_id,
            )

        if take_profit:
            tp_id = await self.place_paper_order(
                symbol=symbol,
                action=exit_action,
                quantity=quantity,
                order_type="LMT",
                limit_price=take_profit,
                parent_order_id=entry_id,
            )

        # 3. Mark the relationship for OCO simulation
        if sl_id and tp_id:
            # We track these locally in _open_orders to simulate OCO
            self._open_orders[sl_id]["oco_peer_id"] = tp_id
            self._open_orders[tp_id]["oco_peer_id"] = sl_id

        return {
            "status": "placed",
            "entry_id": entry_id,
            "sl_id": sl_id,
            "tp_id": tp_id,
            "symbol": symbol,
            "action": action,
            "quantity": quantity,
        }

    async def place_paper_order(
        self,
        symbol: str,
        action: str,
        quantity: int,
        order_type: str = "MKT",
        limit_price: Optional[float] = None,
        aux_price: Optional[float] = None,
        parent_order_id: Optional[str] = None,
    ) -> Optional[str]:
        """
        Record a paper fill after ``SafetyLayer`` has already validated the order.

        STP child orders pass ``aux_price`` + ``parent_order_id`` and are held
        as ``pending`` in ``_open_orders`` without touching positions until the
        stop would trigger (paper sim does not currently model trigger).
        """
        if not self._settings.PAPER_TRADING:
            raise NotImplementedError(
                "IB Gateway live connection not yet implemented. "
                "Set PAPER_TRADING=True for paper trading mode."
            )
        if not self.is_connected():
            logger.error("place_paper_order: not connected")
            return None

        action_upper = action.upper()
        if action_upper not in ("BUY", "SELL") or quantity <= 0:
            return None

        signed_qty = quantity if action_upper == "BUY" else -quantity
        ot_upper = order_type.upper()
        if ot_upper in ("MKT", "MARKET"):
            internal_ot = "market"
        elif ot_upper in ("LMT", "LIMIT"):
            internal_ot = "limit"
        elif ot_upper in ("STP", "STOP"):
            internal_ot = "stop"
        else:
            internal_ot = order_type.lower()

        sym_upper = symbol.upper()
        is_futures = sym_upper in _FUTURES_ROOTS

        if internal_ot == "stop":
            if aux_price is None:
                logger.error("place_paper_order: aux_price required for STP order")
                return None
            stp_id = str(uuid.uuid4())
            self._open_orders[stp_id] = {
                "status": "pending",
                "order_id": stp_id,
                "symbol": symbol,
                "quantity": signed_qty,
                "order_type": "stop",
                "stop_price": aux_price,
                "limit_price": limit_price,
                "is_futures": is_futures,
                "parent_order_id": parent_order_id,
            }
            logger.info(
                "IBGatewayConnector STP accepted | id=%s sym=%s qty=%d stop=%.2f parent=%s",
                stp_id,
                symbol,
                signed_qty,
                aux_price,
                parent_order_id,
            )
            return stp_id

        order = {
            "symbol": symbol,
            "quantity": signed_qty,
            "order_type": internal_ot,
            "limit_price": limit_price,
            "is_futures": is_futures,
        }

        res = await self._submit_paper_order(order, [])
        if res.get("status") == "placed":
            oid = res.get("order_id")
            if oid is not None:
                oid_str = str(oid)
                self._open_orders[oid_str] = {
                    "status": "filled",
                    "order_id": oid_str,
                    "symbol": symbol,
                    "quantity": signed_qty,
                    "order_type": internal_ot,
                    "limit_price": limit_price,
                    "filled_price": res.get("filled_price"),
                    "fill_time": res.get("fill_time"),
                    "is_futures": is_futures,
                    "parent_order_id": parent_order_id,
                }
                return oid_str
        return None

    async def cancel_order(self, order_id: str) -> dict:
        """
        Cancel an open order.

        In paper trading mode: removes from local _open_orders
        In live mode: Would send cancellation to IB Gateway

        Args:
            order_id: Order ID to cancel

        Returns:
            {"status": "cancelled" | "not_found" | "error"}
        """
        if not self.is_connected():
            return {"status": "error", "reason": "Not connected"}

        if self._settings.PAPER_TRADING:
            if order_id in self._open_orders:
                del self._open_orders[order_id]
                logger.info("IBGatewayConnector: Paper order cancelled: %s", order_id)
                return {"status": "cancelled", "order_id": order_id}
            logger.warning("IBGatewayConnector: Order not found: %s", order_id)
            return {"status": "not_found", "order_id": order_id}

        raise NotImplementedError(
            "IB Gateway live connection not yet implemented. "
            "Set PAPER_TRADING=True for paper trading mode."
        )

    async def modify_order(self, order_id: str, new_price: float) -> dict:
        """
        Modify a pending paper order's price.
        """
        if not self.is_connected():
            return {"status": "error", "reason": "Not connected"}

        if self._settings.PAPER_TRADING:
            if order_id not in self._open_orders:
                return {"status": "error", "error": "Order not found"}

            order = self._open_orders[order_id]
            if order["status"] != "pending":
                return {
                    "status": "error",
                    "error": f"Cannot modify order in status: {order['status']}",
                }

            if order["order_type"] == "stop":
                order["stop_price"] = new_price
            elif order["order_type"] == "limit":
                order["limit_price"] = new_price

            logger.info(
                "IBGatewayConnector: Paper order %s modified to price %.2f",
                order_id,
                new_price,
            )
            return {"status": "modified", "order_id": order_id, "new_price": new_price}

        raise NotImplementedError("Live order modification not yet implemented.")

    async def get_order_status(self, order_id: str) -> dict:
        """
        Get the status of a specific order.

        In paper trading mode: returns status from _open_orders
        In live mode: Would query IB Gateway

        Args:
            order_id: Order ID to query

        Returns:
            {
                "order_id": str,
                "symbol": str,
                "quantity": int,
                "status": "filled" | "pending" | "cancelled" | "rejected",
                ...
            }
        """
        if not self.is_connected():
            return {"status": "error", "reason": "Not connected"}

        if self._settings.PAPER_TRADING:
            if order_id in self._open_orders:
                return self._open_orders[order_id]
            logger.warning("IBGatewayConnector: Order not found: %s", order_id)
            return {"status": "not_found", "order_id": order_id}

        raise NotImplementedError(
            "IB Gateway live connection not yet implemented. "
            "Set PAPER_TRADING=True for paper trading mode."
        )

    # ── Account Methods ───────────────────────────────────────────────────────

    def get_cached_position(self, symbol: str) -> Optional[float]:
        """
        Sync, no-I/O net position for ``symbol`` from the paper-sim's own
        ``self._positions`` book — the duck-typed counterpart to
        ``IBGatewayManager.get_cached_position()``.

        Required by ``SafetyLayer.check_order()``'s cumulative-position cap
        (CUMULATIVE_POSITION_CAP, 2026-08-03 incident): that check calls
        ``self._ib_gateway.get_cached_position(sym)`` regardless of which
        gateway implementation is wired in, per ``order_gateway_factory``'s
        duck-typing contract. This connector is the DEFAULT gateway
        (simulator) whenever ``IB_PAPER_BROKER_ENABLED`` is unset, so without
        this method the cap check silently fails open on every paper order.

        Unlike the real-broker version, there's no "not connected" ambiguity
        here — ``_positions`` is authoritative paper-sim state, so a symbol
        with no recorded fill is a genuine, known zero, not "cannot verify."
        """
        return float(self._positions.get(symbol.upper(), 0.0))

    async def get_positions(self) -> list[dict]:
        """
        Return positions in the same list shape as ``IBGatewayManager.get_positions``
        (for ``IBOrderManager.sync_positions_from_ib`` / ``reconcile``).
        """
        if not self.is_connected():
            return []

        if self._settings.PAPER_TRADING:
            out: list[dict] = []
            for symbol, quantity in self._positions.items():
                if quantity == 0:
                    continue
                # A transient quote-feed failure must not break position
                # marking — degrade to the same fallback the no-quote branch
                # below already uses (current_price = 100.0).
                try:
                    quote = await self.get_quote(symbol)
                except Exception as exc:
                    logger.warning(
                        "IBGatewayConnector: get_quote raised marking %s (%s) — using fallback price",
                        symbol,
                        exc,
                    )
                    quote = None
                if quote and "error" not in quote:
                    current_price = float(quote.get("last", 100.0))
                else:
                    current_price = 100.0
                sym_upper = symbol.upper()
                sec_type = "FUT" if sym_upper in _FUTURES_ROOTS else "STK"
                pos_int = int(quantity)
                out.append(
                    {
                        "symbol": symbol,
                        "sec_type": sec_type,
                        "exchange": "PAPER",
                        "currency": "USD",
                        "position": pos_int,
                        "avg_cost": current_price,
                        "market_price": current_price,
                        "market_value": pos_int * current_price,
                        "unrealized_pnl": None,
                        "is_futures": sym_upper in _FUTURES_ROOTS,
                    }
                )
            return out

        raise NotImplementedError(
            "IB Gateway live connection not yet implemented. "
            "Set PAPER_TRADING=True for paper trading mode."
        )

    async def get_account_balance(self) -> dict:
        """
        Get current account balances.

        In paper trading mode: returns simulated balances
        In live mode: Would fetch from IB Gateway

        Returns:
            {
                "equity": float,
                "cash": float,
                "buying_power": float,
                "margin_used": float,
                ...
            }
        """
        if not self.is_connected():
            return {}

        if self._settings.PAPER_TRADING:
            return {
                "equity": self._account_summary["equity"],
                "cash": self._account_summary["cash"],
                "buying_power": self._account_summary["buying_power"],
                "margin_used": 0.0,
                "account_type": "paper",
            }

        raise NotImplementedError(
            "IB Gateway live connection not yet implemented. "
            "Set PAPER_TRADING=True for paper trading mode."
        )

    async def get_account_summary(self) -> dict:
        """
        Get comprehensive account summary (alias for get_account_balance).

        Returns:
            Account balances and positions merged
        """
        balance = await self.get_account_balance()
        positions_list = await self.get_positions()
        positions_map = {p["symbol"]: p for p in positions_list}
        return {**balance, "positions": positions_map}

    async def get_options_greeks(self, symbol: str) -> dict:
        """
        Fetch real-time Greeks for an option.
        Relays to the underlying IBGatewayManager.
        """
        if not self.is_connected():
            return {"error": "Not connected"}

        # _gateway is never set on this connector (only _ib_client is). A bare
        # `if self._gateway:` therefore raised AttributeError on every call instead
        # of returning the intended "unavailable" error below. getattr restores the
        # author's clear fall-through intent.
        gateway = getattr(self, "_gateway", None)
        if gateway:
            return await gateway.get_options_greeks(symbol)

        return {"error": "Gateway unavailable"}

    # ── Market Data ───────────────────────────────────────────────────────────

    def attach_market_data(self, manager) -> None:
        """Wire a real-price source (``MarketDataManager``) for paper quotes.

        Without this, paper ``get_quote`` falls back to a static mock table and
        refuses to fabricate a price for unlisted symbols. With it, fills use the
        real ``get_tick_price`` waterfall (IBKR snapshot -> Schwab -> CSV cache),
        so paper P&L reflects actual market movement instead of frozen constants.
        """
        self._market_data_manager = manager

    async def _real_last_price(self, symbol: str) -> Optional[float]:
        """Best-effort real last price via the attached MarketDataManager.

        Returns a positive float, or None when no real price is available (no
        manager attached, feed down, or symbol unknown to every tier). Never
        raises and never fabricates -- a None result means 'no price basis'.
        """
        mgr = self._market_data_manager
        if mgr is None:
            return None
        try:
            is_fut = symbol.upper() in _FUTURES_ROOTS
            result = await mgr.get_tick_price(symbol, is_futures=is_fut)
            price = result.get("last_price") if isinstance(result, dict) else None
            if price is not None and float(price) > 0:
                return float(price)
        except Exception as exc:  # noqa: BLE001 — best-effort; degrade to None
            logger.debug(
                "IBGatewayConnector: real price lookup failed for %s (%s)", symbol, exc
            )
        return None

    async def get_quote(self, symbol: str) -> dict:
        """
        Get real-time quote for a symbol.

        In paper trading mode: returns realistic mock quote based on symbol
        In live mode: Would fetch from IB Gateway market data

        Args:
            symbol: Symbol to quote (e.g., "MES", "SPY", "AAPL")

        Returns:
            {
                "symbol": str,
                "bid": float,
                "ask": float,
                "last": float,
                "mid": float,
                "volume": int,
                "timestamp": str,  # ISO 8601
            }
        """
        if not self.is_connected():
            return {"error": "Not connected"}

        if self._settings.PAPER_TRADING:
            # Tier 1: a REAL price from the attached MarketDataManager waterfall.
            # This is what makes paper P&L reflect actual market movement.
            real = await self._real_last_price(symbol)
            if real is not None:
                tick = 0.25 if symbol.upper() in _FUTURES_ROOTS else 0.01
                return {
                    "symbol": symbol,
                    "bid": real - tick,
                    "ask": real + tick,
                    "last": real,
                    "mid": real,
                    "volume": 0,
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "source": "live",
                }

            # Tier 2: static mock table — TEST FIXTURES ONLY, behind an explicit
            # opt-in. These are frozen 2024-era constants, NOT real-time.
            #
            # The 2026-06-22 fix stopped fabricating a ~100.05 quote for UNLISTED
            # symbols but deliberately kept this table as an unconditional fallback
            # for listed ones ("backward-compat"). Because _real_last_price returns
            # None whenever no manager is attached OR the feed is blind — and never
            # raises — that made fabrication the DEFAULT: every MES paper fill
            # booked at 5300.10 against a market near 7490. Measured 2026-07-21:
            # 3,475 fills in paper_trades.json, every week from W19-W30 only 0-4%
            # sane, which drove the G2 readiness gate to a meaningless 2.3% win
            # rate (161 of 163 "losses" under $10, both legs off the same frozen
            # constant). A paper system that declines to trade while blind is
            # correct; one that invents a price manufactures a track record.
            if not getattr(self._settings, "ALLOW_MOCK_QUOTES", False):
                return {
                    "symbol": symbol,
                    "error": (
                        "no live price basis (real-price lookup returned None); "
                        "refusing to fabricate a quote. Set ALLOW_MOCK_QUOTES=True "
                        "only in test fixtures."
                    ),
                }

            mock_quotes = {
                "MES": {"bid": 5300.00, "ask": 5300.25, "last": 5300.10, "volume": 1000000},
                "MNQ": {"bid": 17500.00, "ask": 17500.50, "last": 17500.25, "volume": 500000},
                "MCL": {"bid": 82.50, "ask": 82.75, "last": 82.60, "volume": 100000},
                "SPY": {"bid": 450.00, "ask": 450.10, "last": 450.05, "volume": 100000000},
                "QQQ": {"bid": 350.00, "ask": 350.10, "last": 350.05, "volume": 50000000},
                "AAPL": {"bid": 180.00, "ask": 180.10, "last": 180.05, "volume": 80000000},
                "TSLA": {"bid": 240.00, "ask": 240.10, "last": 240.05, "volume": 120000000},
            }

            quote = mock_quotes.get(symbol)
            if quote is None:
                return {
                    "symbol": symbol,
                    "error": "no quote available (no live price, no mock entry)",
                }

            return {
                "symbol": symbol,
                "bid": quote["bid"],
                "ask": quote["ask"],
                "last": quote["last"],
                "mid": (quote["bid"] + quote["ask"]) / 2,
                "volume": quote["volume"],
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "source": "mock",
            }

        raise NotImplementedError(
            "IB Gateway live connection not yet implemented. "
            "Set PAPER_TRADING=True for paper trading mode."
        )

    # ── Kill Switch Support ───────────────────────────────────────────────────

    async def get_open_orders(self) -> list[dict]:
        """
        Return all open (non-filled, non-cancelled) orders.

        In paper trading mode: returns pending entries from ``_open_orders``.
        In live mode: Would query IB Gateway for open orders.

        Returns:
            List of order dicts; each has at minimum ``order_id``, ``symbol``,
            ``order_type``, and ``status`` keys.
        """
        if not self.is_connected():
            return []

        if self._settings.PAPER_TRADING:
            return list(self._open_orders.values())

        raise NotImplementedError(
            "IB Gateway live connection not yet implemented. "
            "Set PAPER_TRADING=True for paper trading mode."
        )

    async def cancel_all_orders(self) -> int:
        """
        Cancel all open orders.

        In paper trading mode: clears _open_orders dict
        In live mode: Would cancel all orders on IB Gateway

        Returns:
            Number of orders cancelled
        """
        if not self.is_connected():
            logger.warning("cancel_all_orders: IBGatewayConnector not connected")
            return 0

        if self._settings.PAPER_TRADING:
            count = len(self._open_orders)
            self._open_orders.clear()
            logger.info("IBGatewayConnector: Cancelled %d paper orders", count)
            return count

        raise NotImplementedError(
            "IB Gateway live connection not yet implemented. "
            "Set PAPER_TRADING=True for paper trading mode."
        )
