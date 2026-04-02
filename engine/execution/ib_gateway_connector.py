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
  - is_connected property
  - submit_order(), cancel_order(), get_order_status()
  - get_positions(), get_account_balance()
  - get_quote() (mock in paper mode)
  All methods are async.
"""

import logging
import random
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)

__all__ = ["IBGatewayConnector"]


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

    def __init__(self, settings, safety_layer, portfolio_tracker=None):
        """
        Initialize the IB Gateway connector.

        Args:
            settings: TradingConfig with PAPER_TRADING, IBKR_HOST, IBKR_PORT, etc.
            safety_layer: RiskSafetyLayer for pre-trade validation
            portfolio_tracker: Optional ``PortfolioTracker`` — when set, paper fills
                can mirror to the engine API book via ``PaperTradeLogger`` (see execution README).
        """
        self._settings = settings
        self._safety_layer = safety_layer
        self._portfolio_tracker = portfolio_tracker
        self._connected = False
        self._ib_client = None  # Will hold ib_insync.IB() when live trading is implemented
        self._paper_trade_logger = None  # Lazy-loaded on first use
        self._account_summary = {
            "equity": 10000.0,
            "cash": 10000.0,
            "buying_power": 40000.0,
        }
        self._positions = {}
        self._open_orders = {}

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def connect(self) -> bool:
        """
        Connect to IB Gateway.

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
            )
            self._connected = True
            return True

        # Live mode: not yet implemented
        logger.error(
            "IBGatewayConnector: Live connection to IB Gateway not yet implemented. "
            "Set PAPER_TRADING=True for now."
        )
        self._connected = False
        return False

    async def disconnect(self) -> bool:
        """
        Disconnect from IB Gateway.

        In paper trading mode: just clears local state.
        In live mode: Would disconnect from IB Gateway.

        Returns:
            True if successfully disconnected
        """
        if self._ib_client:
            try:
                # TODO: When live trading implemented, call self._ib_client.disconnect()
                pass
            except Exception as exc:
                logger.error("Error disconnecting from IB Gateway: %s", exc)

        self._connected = False
        logger.info("IBGatewayConnector: Disconnected")
        return True

    @property
    def is_connected(self) -> bool:
        """Return True if connected to IB Gateway (or in paper trading mode)."""
        return self._connected

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
        if not self.is_connected:
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

        # Get market quote (mock for paper trading)
        quote = await self.get_quote(symbol)
        if not quote or "error" in quote:
            logger.warning("IBGatewayConnector: Could not get quote for %s", symbol)
            mid_price = limit_price or 100.0
        else:
            mid_price = quote.get("mid", limit_price or 100.0)

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
        if not self.is_connected:
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
        if not self.is_connected:
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

    async def get_positions(self) -> dict[str, dict]:
        """
        Get current positions across all symbols.

        In paper trading mode: returns simulated positions from _positions dict
        In live mode: Would fetch from IB Gateway

        Returns:
            {
                "symbol": {
                    "quantity": int,
                    "avg_price": float,
                    "market_value": float,
                    "unrealized_pnl": float,
                },
                ...
            }
        """
        if not self.is_connected:
            return {}

        if self._settings.PAPER_TRADING:
            positions = {}
            for symbol, quantity in self._positions.items():
                if quantity == 0:
                    continue
                quote = await self.get_quote(symbol)
                current_price = quote.get("last", 100.0) if quote else 100.0
                positions[symbol] = {
                    "symbol": symbol,
                    "quantity": quantity,
                    "current_price": current_price,
                    "market_value": quantity * current_price,
                }
            return positions

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
        if not self.is_connected:
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
        positions = await self.get_positions()
        return {
            **balance,
            "positions": positions,
            "position_count": len(positions),
        }

    # ── Market Data ───────────────────────────────────────────────────────────

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
        if not self.is_connected:
            return {"error": "Not connected"}

        if self._settings.PAPER_TRADING:
            # Return realistic mock quotes based on symbol
            # These are NOT real-time — just for paper trading simulation
            mock_quotes = {
                "MES": {"bid": 5300.00, "ask": 5300.25, "last": 5300.10, "volume": 1000000},
                "MNQ": {"bid": 17500.00, "ask": 17500.50, "last": 17500.25, "volume": 500000},
                "MCL": {"bid": 82.50, "ask": 82.75, "last": 82.60, "volume": 100000},
                "SPY": {"bid": 450.00, "ask": 450.10, "last": 450.05, "volume": 100000000},
                "QQQ": {"bid": 350.00, "ask": 350.10, "last": 350.05, "volume": 50000000},
                "AAPL": {"bid": 180.00, "ask": 180.10, "last": 180.05, "volume": 80000000},
                "TSLA": {"bid": 240.00, "ask": 240.10, "last": 240.05, "volume": 120000000},
            }

            quote = mock_quotes.get(
                symbol,
                {"bid": 100.00, "ask": 100.10, "last": 100.05, "volume": 1000000},
            )

            return {
                "symbol": symbol,
                "bid": quote["bid"],
                "ask": quote["ask"],
                "last": quote["last"],
                "mid": (quote["bid"] + quote["ask"]) / 2,
                "volume": quote["volume"],
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }

        raise NotImplementedError(
            "IB Gateway live connection not yet implemented. "
            "Set PAPER_TRADING=True for paper trading mode."
        )

    # ── Kill Switch Support ───────────────────────────────────────────────────

    async def cancel_all_orders(self) -> int:
        """
        Cancel all open orders.

        In paper trading mode: clears _open_orders dict
        In live mode: Would cancel all orders on IB Gateway

        Returns:
            Number of orders cancelled
        """
        if not self.is_connected:
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
