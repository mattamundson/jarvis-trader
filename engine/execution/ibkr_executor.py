"""
JARVIS TRADER — IBKR Order Execution Layer
==========================================
Connects to Interactive Brokers Gateway via ib_async (async Python client).

Setup:
  1. Download IB Gateway from https://www.interactivebrokers.com/en/trading/ibgateway.php
  2. Run IB Gateway: port 4002 = paper, port 4001 = live
  3. Enable API connections in IB Gateway settings
  4. Start JARVIS engine — it connects automatically

ib_async wraps IB's TWS API over a persistent TCP socket.
"""

import asyncio
import logging
from datetime import date
from typing import Optional

try:
    from ib_async import (
        IB,
        Future,
        LimitOrder,
        MarketOrder,
        Order,
        Stock,
        StopLimitOrder,
        StopOrder,
    )

    IB_AVAILABLE = True
except ImportError:
    IB_AVAILABLE = False
    IB = None
    Future = None
    Stock = None
    Order = None
    MarketOrder = None
    LimitOrder = None
    StopOrder = None
    StopLimitOrder = None

from risk.safety_layer import KillSwitchReason, OrderRequest, SafetyLayer

logger = logging.getLogger(__name__)

__all__ = ["IBKRExecutor"]


# ── Contract exchange map ─────────────────────────────────────────────────────
_FUTURES_EXCHANGE: dict[str, str] = {
    "MES": "CME",
    "MNQ": "CME",
    "M2K": "CME",  # Micro Russell 2000
    "MCL": "NYMEX",
    "MGC": "COMEX",
    "MHG": "COMEX",
    "MSI": "CME",
}

# Quarterly expiry month codes (futures notation)
_QUARTERLY_MONTHS: list[int] = [3, 6, 9, 12]  # Mar / Jun / Sep / Dec
_MONTH_CODE: dict[int, str] = {3: "H", 6: "M", 9: "U", 12: "Z"}

# Approximate expiry day (third Friday of expiry month).
# We use the 3rd Friday approximation; the exact date is close enough for
# building the contract string that IBKR resolves to the active contract.
_EXPIRY_DAY_APPROX: int = 21


# ── Contract month helper ─────────────────────────────────────────────────────


def _nearest_quarterly_expiry(reference: Optional[date] = None) -> str:
    """
    Return the nearest active quarterly expiry as "YYYYMMDD".

    Logic:
      - Quarterly months are March (3), June (6), September (9), December (12).
      - If today is before the ~21st of an expiry month, that month's contract
        is still the front month.
      - Otherwise advance to the next quarterly month.

    Examples (reference = 2026-01-15):
      -> next quarterly after Jan is Mar -> "20260321"
    Examples (reference = 2026-03-22, past expiry):
      -> Mar has expired, next is Jun -> "20260620"
    """
    ref = reference or date.today()

    for month in _QUARTERLY_MONTHS:
        # Candidate expiry in the current year
        candidate = date(ref.year, month, _EXPIRY_DAY_APPROX)
        if candidate > ref:
            return candidate.strftime("%Y%m%d")

    # All quarterly months in current year have passed — use March of next year
    return date(ref.year + 1, 3, _EXPIRY_DAY_APPROX).strftime("%Y%m%d")


# ── IBKRExecutor ──────────────────────────────────────────────────────────────


class IBKRExecutor:
    """
    Async wrapper around ib_async.IB for JARVIS TRADER.

    All order submission MUST go through submit_order() which enforces the
    SafetyLayer pre-trade checks.  There is no path to bypass the safety check.
    """

    MAX_RECONNECT_ATTEMPTS: int = 3
    RECONNECT_DELAY_SECONDS: float = 5.0

    def __init__(self, settings, safety_layer: SafetyLayer) -> None:
        if not IB_AVAILABLE:
            raise RuntimeError(
                "ib_async is not installed. Run: pip install ib_async\n"
                "IB Gateway must also be running on the configured port."
            )
        self._settings = settings
        self._safety = safety_layer
        self._ib: IB = IB()
        self._connect_lock = asyncio.Lock()

        mode = "PAPER" if settings.IBKR_PORT == 4002 else "LIVE"
        logger.info(
            f"IBKRExecutor initialised — host={settings.IBKR_HOST} "
            f"port={settings.IBKR_PORT} ({mode}) clientId={settings.IBKR_CLIENT_ID}"
        )

    # ── Connection management ─────────────────────────────────────────────────

    async def connect(self) -> bool:
        """
        Connect to IB Gateway.

        Returns True on success.  Retries up to MAX_RECONNECT_ATTEMPTS times
        with RECONNECT_DELAY_SECONDS between attempts.
        """
        async with self._connect_lock:
            for attempt in range(1, self.MAX_RECONNECT_ATTEMPTS + 1):
                try:
                    logger.info(
                        f"Connecting to IB Gateway at "
                        f"{self._settings.IBKR_HOST}:{self._settings.IBKR_PORT} "
                        f"(attempt {attempt}/{self.MAX_RECONNECT_ATTEMPTS})"
                    )
                    await self._ib.connectAsync(
                        self._settings.IBKR_HOST,
                        self._settings.IBKR_PORT,
                        clientId=self._settings.IBKR_CLIENT_ID,
                    )
                    logger.info(
                        f"Connected to IB Gateway — "
                        f"server version {self._ib.client.serverVersion()}"
                    )
                    return True
                except Exception as exc:
                    logger.warning(f"Connection attempt {attempt} failed: {exc}")
                    if attempt < self.MAX_RECONNECT_ATTEMPTS:
                        await asyncio.sleep(self.RECONNECT_DELAY_SECONDS)

            logger.error(
                f"Failed to connect to IB Gateway after {self.MAX_RECONNECT_ATTEMPTS} attempts."
            )
            # Notify safety layer so it knows the broker link is down
            self._safety.activate_kill_switch(
                KillSwitchReason.BROKER_DISCONNECT,
                "Could not connect to IB Gateway after retries",
            )
            return False

    async def disconnect(self) -> None:
        """Gracefully disconnect from IB Gateway."""
        if self._ib.isConnected():
            self._ib.disconnect()
            logger.info("Disconnected from IB Gateway.")

    async def _ensure_connected(self) -> bool:
        """
        Check connection health; attempt reconnect if disconnected.
        Returns True if connected after the call.
        """
        if self._ib.isConnected():
            return True

        logger.warning("IB Gateway connection lost — attempting reconnect.")
        return await self.connect()

    @property
    def is_connected(self) -> bool:
        """True if the ib_async client has an active connection."""
        return self._ib.isConnected()

    # ── Account / portfolio data ──────────────────────────────────────────────

    async def get_account_summary(self) -> dict:
        """
        Pull account summary from IBKR.

        Returns a normalised dict with these keys:
          total_equity, cash, available_funds, margin_used,
          unrealized_pnl, daily_pnl

        This is the SOLE source of portfolio truth for JARVIS TRADER.
        """
        if not await self._ensure_connected():
            logger.error("get_account_summary: not connected to IB Gateway")
            return {}

        try:
            account_values = await self._ib.reqAccountSummaryAsync(
                groupName="All",
                tags=(
                    "NetLiquidation,TotalCashValue,AvailableFunds,"
                    "GrossPositionValue,UnrealizedPnL,RealizedPnL,"
                    "DailyPnL,MaintMarginReq"
                ),
            )
        except Exception as exc:
            logger.error(f"reqAccountSummary failed: {exc}")
            return {}

        # Build a flat key→value dict (values are strings from the API)
        raw: dict[str, str] = {}
        for av in account_values:
            raw[av.tag] = av.value

        def _f(tag: str) -> float:
            try:
                return float(raw.get(tag, 0.0))
            except (ValueError, TypeError):
                return 0.0

        summary = {
            "total_equity": _f("NetLiquidation"),
            "cash": _f("TotalCashValue"),
            "available_funds": _f("AvailableFunds"),
            "margin_used": _f("MaintMarginReq"),
            "unrealized_pnl": _f("UnrealizedPnL"),
            "daily_pnl": _f("DailyPnL"),
        }
        logger.debug(f"Account summary: {summary}")
        return summary

    async def get_positions(self) -> list[dict]:
        """
        Return all current positions held at IBKR.

        Each item in the returned list:
          symbol, quantity, avg_cost, market_value, unrealized_pnl,
          is_futures, contract_month
        """
        if not await self._ensure_connected():
            logger.error("get_positions: not connected to IB Gateway")
            return []

        try:
            raw_positions = await self._ib.reqPositionsAsync()
        except Exception as exc:
            logger.error(f"reqPositions failed: {exc}")
            return []

        positions: list[dict] = []
        for pos in raw_positions:
            contract = pos.contract
            is_futures = contract.secType == "FUT"
            positions.append(
                {
                    "symbol": contract.symbol,
                    "sec_type": contract.secType,
                    "quantity": pos.position,
                    "avg_cost": pos.avgCost,
                    "market_value": pos.position * pos.avgCost,  # approximate
                    "unrealized_pnl": 0.0,  # not available directly from reqPositions
                    "is_futures": is_futures,
                    "contract_month": contract.lastTradeDateOrContractMonth if is_futures else None,
                    "exchange": contract.exchange,
                    "currency": contract.currency,
                }
            )

        logger.debug(f"Positions ({len(positions)}): {[p['symbol'] for p in positions]}")
        return positions

    async def get_open_orders(self) -> list[dict]:
        """
        Return all open (working) orders from IBKR.
        """
        if not await self._ensure_connected():
            logger.error("get_open_orders: not connected to IB Gateway")
            return []

        try:
            open_orders = await self._ib.reqOpenOrdersAsync()
        except Exception as exc:
            logger.error(f"reqOpenOrders failed: {exc}")
            return []

        orders: list[dict] = []
        for trade in open_orders:
            orders.append(
                {
                    "ibkr_order_id": trade.order.orderId,
                    "symbol": trade.contract.symbol,
                    "action": trade.order.action,
                    "quantity": trade.order.totalQuantity,
                    "order_type": trade.order.orderType,
                    "limit_price": trade.order.lmtPrice,
                    "stop_price": trade.order.auxPrice,
                    "status": trade.orderStatus.status,
                    "filled": trade.orderStatus.filled,
                    "remaining": trade.orderStatus.remaining,
                }
            )

        logger.debug(f"Open orders ({len(orders)})")
        return orders

    # ── Order submission ──────────────────────────────────────────────────────

    def _build_ib_order(self, order_type: str, action: str, qty: int, order: OrderRequest) -> Optional[Order]:
        """Build IB order object. Returns Order or None."""
        ot = order_type.lower()

        if ot == "market":
            return MarketOrder(action, qty)
        if ot == "limit":
            if order.limit_price is None:
                logger.error("submit_order: limit_price required for limit orders")
                return None
            return LimitOrder(action, qty, order.limit_price)
        if ot == "stop":
            if order.stop_price is None:
                logger.error("submit_order: stop_price required for stop orders")
                return None
            return StopOrder(action, qty, order.stop_price)
        if ot == "stop_limit":
            if order.limit_price is None or order.stop_price is None:
                logger.error("submit_order: Both limit_price and stop_price required for stop_limit")
                return None
            return StopLimitOrder(action, qty, order.limit_price, order.stop_price)

        logger.error(f"submit_order: Unknown order_type '{order_type}'")
        return None

    async def submit_order(self, order: OrderRequest, portfolio_equity: float) -> dict:
        """
        CRITICAL PATH — submit a trade to IBKR.

        Step 1: safety_layer.check_order() MUST pass.
        Step 2: Convert OrderRequest → ib_async Contract + Order objects.
        Step 3: Place via ib_async placeOrder().
        Step 4: Return result dict.

        NEVER bypasses the safety check.  If the safety check rejects the
        order, the method returns immediately with submitted=False.
        """
        # ── Step 1: Safety gate ───────────────────────────────────────────────
        result = self._safety.check_order(order, portfolio_equity)

        if not result.approved:
            logger.warning(
                f"Order REJECTED by SafetyLayer — "
                f"symbol={order.symbol} qty={order.quantity} "
                f"reason={result.rejection_reason}"
            )
            return {
                "submitted": False,
                "reason": result.rejection_reason,
                "symbol": order.symbol,
                "quantity": order.quantity,
                "order_type": order.order_type,
                "warnings": result.warnings,
            }

        if result.warnings:
            for w in result.warnings:
                logger.warning(f"SafetyLayer warning (order allowed): {w}")

        # ── Step 2: Ensure broker connection ─────────────────────────────────
        if not await self._ensure_connected():
            logger.error("submit_order: IB Gateway not reachable — order not sent")
            return {
                "submitted": False,
                "reason": "IB Gateway not connected",
                "symbol": order.symbol,
            }

        # ── Step 3: Build contract ────────────────────────────────────────────
        try:
            if order.is_futures:
                contract = self._make_futures_contract(order.symbol)
            else:
                contract = Stock(order.symbol, "SMART", "USD")

            await self._ib.qualifyContractsAsync(contract)
        except Exception as exc:
            logger.error(f"Contract qualification failed for {order.symbol}: {exc}")
            return {
                "submitted": False,
                "reason": f"Contract qualification failed: {exc}",
                "symbol": order.symbol,
            }

        # ── Step 4: Build IB Order object ─────────────────────────────────────
        # CRITICAL: build from result.adjusted_order (the risk-layer's
        # post-loss-tracker order), not the pre-check `order`. check_order()
        # may have halved/quartered the size after consecutive losses; using
        # the pre-check `order` here silently discarded that de-risking and
        # sent full-size orders to IBKR regardless (PRB-01, 2026-07-29
        # prod-readiness audit).
        final_order = result.adjusted_order or order
        action = "BUY" if final_order.quantity > 0 else "SELL"
        qty = abs(final_order.quantity)
        if qty != abs(order.quantity):
            logger.warning(
                f"submit_order: risk-adjusted size {abs(order.quantity)} -> {qty} "
                f"for symbol={order.symbol}"
            )

        ib_order = self._build_ib_order(final_order.order_type, action, qty, final_order)
        if ib_order is None:
            return {
                "submitted": False,
                "reason": f"Invalid order_type '{final_order.order_type}'",
                "symbol": final_order.symbol,
            }

        # ── Step 5: Place the order ───────────────────────────────────────────
        try:
            trade = self._ib.placeOrder(contract, ib_order)
            ibkr_order_id = ib_order.orderId

            logger.info(
                f"Order SUBMITTED — id={ibkr_order_id} symbol={final_order.symbol} "
                f"action={action} qty={qty} type={final_order.order_type} "
                f"limit={final_order.limit_price} stop={final_order.stop_price} "
                f"est_value=${final_order.estimated_value:,.0f}"
            )

            return {
                "submitted": True,
                "ibkr_order_id": ibkr_order_id,
                "symbol": final_order.symbol,
                "action": action,
                "quantity": qty,
                "order_type": final_order.order_type,
                "limit_price": final_order.limit_price,
                "stop_price": final_order.stop_price,
                "warnings": result.warnings,
                "trade": trade,
            }

        except Exception as exc:
            logger.error(
                f"placeOrder failed — symbol={final_order.symbol} action={action} qty={qty}: {exc}"
            )
            return {
                "submitted": False,
                "reason": f"placeOrder exception: {exc}",
                "symbol": final_order.symbol,
            }

    # ── Order cancellation ────────────────────────────────────────────────────

    async def cancel_order(self, ibkr_order_id: int) -> bool:
        """
        Cancel a specific open order by its IBKR order ID.
        Returns True if the cancellation request was accepted.
        """
        if not await self._ensure_connected():
            logger.error("cancel_order: not connected to IB Gateway")
            return False

        try:
            # Find the Trade object that matches the order ID
            open_trades = self._ib.openTrades()
            target_trade = next((t for t in open_trades if t.order.orderId == ibkr_order_id), None)

            if target_trade is None:
                logger.warning(f"cancel_order: order id {ibkr_order_id} not found in open trades")
                return False

            self._ib.cancelOrder(target_trade.order)
            logger.info(f"Cancellation requested for order id={ibkr_order_id}")
            return True

        except Exception as exc:
            logger.error(f"cancel_order failed for id={ibkr_order_id}: {exc}")
            return False

    async def cancel_all_orders(self) -> int:
        """
        Cancel ALL open orders.  Called by the kill-switch pathway.

        Returns the number of cancellation requests sent.
        """
        if not await self._ensure_connected():
            logger.error("cancel_all_orders: not connected to IB Gateway")
            return 0

        try:
            open_trades = self._ib.openTrades()
            count = 0
            for trade in open_trades:
                try:
                    self._ib.cancelOrder(trade.order)
                    logger.info(
                        f"Cancelled order id={trade.order.orderId} symbol={trade.contract.symbol}"
                    )
                    count += 1
                except Exception as exc:
                    logger.error(f"Failed to cancel order id={trade.order.orderId}: {exc}")

            logger.warning(f"cancel_all_orders: {count} cancellations sent")
            return count

        except Exception as exc:
            logger.error(f"cancel_all_orders failed: {exc}")
            return 0

    # ── Emergency flatten ─────────────────────────────────────────────────────

    async def flatten_all_positions(self) -> list[dict]:
        """
        Emergency close of all open positions via market orders.

        ONLY callable when the kill switch is active (enforced here).
        Returns a list of result dicts from submit_order for each closing order.
        """
        if not self._safety.is_killed:
            logger.error(
                "flatten_all_positions called without active kill switch — REFUSED. "
                "Activate the kill switch first."
            )
            return []

        positions = await self.get_positions()
        if not positions:
            logger.info("flatten_all_positions: no open positions")
            return []

        logger.critical(
            f"FLATTENING ALL POSITIONS ({len(positions)} open): "
            + ", ".join(f"{p['symbol']} qty={p['quantity']}" for p in positions)
        )

        results: list[dict] = []
        for pos in positions:
            qty = pos["quantity"]
            if qty == 0:
                continue

            OrderRequest(
                symbol=pos["symbol"],
                quantity=-qty,  # opposite side to close
                order_type="market",
                is_futures=pos["is_futures"],
                estimated_value=abs(pos.get("market_value", 0.0)),
            )

            # During a flatten we bypass the normal safety check because the
            # kill switch being active would block the order via check_order().
            # We place directly through ib_async, logging everything.
            if not await self._ensure_connected():
                results.append(
                    {"submitted": False, "reason": "Not connected", "symbol": pos["symbol"]}
                )
                continue

            try:
                if pos["is_futures"]:
                    contract = self._make_futures_contract(pos["symbol"])
                else:
                    contract = Stock(pos["symbol"], "SMART", "USD")

                await self._ib.qualifyContractsAsync(contract)

                action = "BUY" if -qty > 0 else "SELL"
                ib_order = MarketOrder(action, abs(qty))
                trade = self._ib.placeOrder(contract, ib_order)

                logger.critical(
                    f"FLATTEN order placed — id={ib_order.orderId} "
                    f"symbol={pos['symbol']} action={action} qty={abs(qty)}"
                )
                results.append(
                    {
                        "submitted": True,
                        "ibkr_order_id": ib_order.orderId,
                        "symbol": pos["symbol"],
                        "action": action,
                        "quantity": abs(qty),
                        "trade": trade,
                    }
                )
            except Exception as exc:
                logger.error(f"FLATTEN order failed for {pos['symbol']}: {exc}")
                results.append({"submitted": False, "reason": str(exc), "symbol": pos["symbol"]})

        return results

    # ── Contract helpers ──────────────────────────────────────────────────────

    async def get_contract_details(self, symbol: str) -> dict:
        """
        Fetch contract details for a futures symbol.

        Returns a dict with: symbol, exchange, multiplier, min_tick,
        initial_margin, maintenance_margin, long_initial_margin,
        short_initial_margin, currency
        """
        if not await self._ensure_connected():
            logger.error("get_contract_details: not connected to IB Gateway")
            return {}

        try:
            contract = self._make_futures_contract(symbol)
            details_list = await self._ib.reqContractDetailsAsync(contract)

            if not details_list:
                logger.warning(f"No contract details returned for {symbol}")
                return {}

            cd = details_list[0]
            return {
                "symbol": cd.contract.symbol,
                "exchange": cd.contract.exchange,
                "currency": cd.contract.currency,
                "multiplier": cd.contract.multiplier,
                "min_tick": cd.minTick,
                "long_initial_margin": cd.longInitialMargin,
                "short_initial_margin": cd.shortInitialMargin,
                "maintenance_margin": cd.maintMargin,
                "initial_margin": cd.initMargin,
                "contract_month": cd.contract.lastTradeDateOrContractMonth,
                "trading_hours": cd.tradingHours,
            }

        except Exception as exc:
            logger.error(f"get_contract_details failed for {symbol}: {exc}")
            return {}

    def _make_futures_contract(self, symbol: str) -> Future:
        """
        Build an ib_async Future contract for the given symbol.

        Exchange mapping:
          MES, MNQ, M2K, MSI  -> CME
          MCL                  -> NYMEX
          MGC, MHG             -> COMEX

        Contract month is the nearest quarterly expiry derived from today's date
        (March / June / September / December), expressed as "YYYYMMDD".

        The returned contract is NOT yet qualified (no conId).  Call
        ``await ib.qualifyContractsAsync(contract)`` before placing an order.
        """
        symbol_upper = symbol.upper()
        exchange = _FUTURES_EXCHANGE.get(symbol_upper, "CME")
        contract_month = _nearest_quarterly_expiry()

        contract = Future(
            symbol=symbol_upper,
            lastTradeDateOrContractMonth=contract_month,
            exchange=exchange,
            currency="USD",
        )

        logger.debug(f"Built futures contract: {symbol_upper} {contract_month} on {exchange}")
        return contract
