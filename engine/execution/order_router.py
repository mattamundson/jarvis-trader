"""
Order Router — dispatches orders to the correct broker based on instrument type.

Routing rules:
  Futures (MES, MNQ, MCL, MGC, ES, NQ, GC, CL, etc.) -> IBKR
  Equities (SPY, QQQ, AAPL, etc.) -> Schwab
  Options -> Schwab (preferred), fallback IBKR
  Spot crypto (BTCUSD, ETHUSD, ...) -> CryptoMarketModule (Kraken or Freqtrade)

Note: CME micro crypto futures tickers `BTC` / `ETH` (→ MBT/MET contracts) stay
in FUTURES_SYMBOLS because they ARE futures. Only the USD-suffixed spot
symbols are routed to the crypto module.
"""

import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from execution.ib_gateway_connector import IBGatewayConnector
    from execution.schwab_connector import SchwabConnector
    from markets.crypto.module import CryptoMarketModule

logger = logging.getLogger(__name__)

# Spot crypto tickers routed to the crypto module rather than any broker.
# Kept in sync with utils.position_sizing.CRYPTO_SPOT_SYMBOLS (duplicated here
# to avoid a circular import at module load).
CRYPTO_SPOT_SYMBOLS = {
    "BTCUSD",
    "ETHUSD",
    "SOLUSD",
    "XBTUSD",  # Kraken alias for BTCUSD
}

# Futures symbols that must go to IBKR
FUTURES_SYMBOLS = {
    "MES",
    "ES",
    "MNQ",
    "NQ",
    "MCL",
    "CL",
    "MGC",
    "GC",
    "MYM",
    "YM",
    "M2K",
    "RTY",
    "MBT",
    "BTC",
    "MET",
    "ETH",
    "ZN",
    "ZB",
    "ZF",
    "ZT",
    "6E",
    "6B",
    "6J",
}

FUTURES_PREFIXES = ("M", "E", "C", "Z", "6")  # heuristic for unrecognized symbols


class OrderRouter:
    def __init__(
        self,
        ibkr: Optional["IBGatewayConnector"] = None,
        schwab: Optional["SchwabConnector"] = None,
        crypto_module: Optional["CryptoMarketModule"] = None,
    ):
        self.ibkr = ibkr
        self.schwab = schwab
        self.crypto_module = crypto_module

    def attach_ibkr(self, connector: "IBGatewayConnector") -> None:
        self.ibkr = connector

    def attach_schwab(self, connector: "SchwabConnector") -> None:
        self.schwab = connector

    def attach_crypto(self, module: "CryptoMarketModule") -> None:
        self.crypto_module = module

    def is_futures(self, symbol: str) -> bool:
        return symbol.upper() in FUTURES_SYMBOLS

    def is_crypto_spot(self, symbol: str) -> bool:
        return symbol.upper() in CRYPTO_SPOT_SYMBOLS

    def is_options(self, order: dict) -> bool:
        return order.get("asset_type", "").upper() in ("OPT", "OPTION", "OPTIONS")

    async def route_order(self, order: dict) -> dict:
        """
        Dispatch an order dict to the appropriate broker.

        Args:
            order: dict with at minimum:
                {"symbol": str, "action": str, "quantity": int}
                Optional: "order_type" (default "MKT"), "limit_price", "asset_type"

        Returns:
            Fill confirmation dict from the executing connector.

        Raises:
            RuntimeError if the required broker is not connected.
        """
        symbol = order.get("symbol", "").upper()

        if self.is_crypto_spot(symbol):
            if self.crypto_module is None:
                raise RuntimeError(
                    f"Crypto module not attached — cannot route spot order for {symbol}. "
                    "Set CRYPTO_ENABLED=True and attach CryptoMarketModule to the router."
                )
            from markets.base import TradeSignal  # lazy import to avoid cycles
            signal = TradeSignal(
                symbol=symbol,
                action=order.get("action", "buy").lower(),
                quantity=float(order.get("quantity", 0)),
                confidence=float(order.get("confidence", 1.0)),
                strategy=order.get("strategy", "manual"),
                market="crypto",
                reason=order.get("reason", ""),
                params={
                    "order_type": order.get("order_type"),
                    "limit_price": order.get("limit_price"),
                },
            )
            logger.info("Routing %s order to CryptoMarketModule", symbol)
            result = await self.crypto_module.execute_signal(signal)
            return {
                "status": "placed" if result.executed else "error",
                "fill_id": result.order_id,
                "symbol": symbol,
                "action": signal.action,
                "quantity": signal.quantity,
                "broker": "crypto",
                "error": result.error,
            }

        if self.is_futures(symbol):
            if not self.ibkr or not self.ibkr.is_connected():
                raise RuntimeError(f"IBKR not connected — cannot route futures order for {symbol}")
            logger.info("Routing %s order to IBKR", symbol)
            fill_id = await self.ibkr.place_paper_order(
                symbol=symbol,
                action=order.get("action", "BUY"),
                quantity=int(order.get("quantity", 1)),
                order_type=order.get("order_type", "MKT"),
                limit_price=order.get("limit_price"),
            )
            return {
                "status": "placed" if fill_id else "error",
                "fill_id": fill_id,
                "symbol": symbol,
                "action": order.get("action", "BUY"),
                "quantity": int(order.get("quantity", 1)),
                "broker": "ibkr",
            }

        elif self.is_options(order):
            equity = order.get("portfolio_equity", 10000.0) # Default
            if self.schwab and self.schwab.is_connected:
                logger.info("Routing %s options order to Schwab", symbol)
                if order.get("is_spread"):
                    return await self.schwab.submit_options_spread_order(order, portfolio_equity=equity)
                return await self.schwab.submit_options_order(order, portfolio_equity=equity)
            elif self.ibkr and self.ibkr.is_connected():
                logger.info("Routing %s options order to IBKR (Schwab unavailable)", symbol)
                return await self.ibkr.place_paper_order(order)
            else:
                raise RuntimeError("No broker connected for options order")

        else:
            # Equity
            if not self.schwab or not self.schwab.is_connected:
                raise RuntimeError(f"Schwab not connected — cannot route equity order for {symbol}")
            logger.info("Routing %s equity order to Schwab", symbol)
            return await self.schwab.place_paper_order(order)

    async def route_bracket_order(
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
        Route a bracket order (Entry + SL + TP) to the correct broker.
        """
        sym_upper = symbol.upper()

        if self.is_futures(sym_upper):
            if not self.ibkr or not self.ibkr.is_connected():
                raise RuntimeError(f"IBKR not connected — cannot route futures bracket for {symbol}")

            logger.info("Routing %s bracket order to IBKR", symbol)
            return await self.ibkr.place_bracket_order(
                symbol=symbol,
                action=action,
                quantity=quantity,
                entry_type=entry_type,
                limit_price=limit_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
            )

        raise NotImplementedError(f"Bracket orders not yet supported for non-futures: {symbol}")

    async def cancel_order(self, order_id: str) -> dict:
        """
        Cancel an order by ID. Dispatches to the appropriate broker.
        """
        # For now, IDs are UUIDs (IBKR paper) or numeric (IBKR live / Schwab)
        # We'll try IBKR first as it's the primary broker for active trades.
        if self.ibkr and self.ibkr.is_connected():
            return await self.ibkr.cancel_order(order_id)

        if self.schwab and self.schwab.is_connected:
            return await self.schwab.cancel_order(order_id)

        return {"status": "error", "reason": "No connected broker found to cancel order"}

    async def modify_order(self, order_id: str, new_price: float) -> dict:
        """
        Modify an existing order's price.
        """
        if self.ibkr and self.ibkr.is_connected():
            return await self.ibkr.modify_order(order_id, new_price)

        if self.schwab and self.schwab.is_connected:
            return await self.schwab.modify_order(order_id, new_price)

        return {"status": "error", "reason": "No connected broker found to modify order"}

    def status(self) -> dict:
        return {
            "ibkr_connected": bool(self.ibkr and self.ibkr.is_connected()),
            "schwab_connected": bool(self.schwab and self.schwab.is_connected),
            "futures_broker": ("ibkr" if self.ibkr and self.ibkr.is_connected() else "unavailable"),
            "equity_broker": (
                "schwab" if self.schwab and self.schwab.is_connected else "unavailable"
            ),
        }


__all__ = ["OrderRouter", "FUTURES_SYMBOLS"]
