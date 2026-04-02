"""
Order Router — dispatches orders to the correct broker based on instrument type.

Routing rules:
  Futures (MES, MNQ, MCL, MGC, ES, NQ, GC, CL, etc.) -> IBKR
  Equities (SPY, QQQ, AAPL, etc.) -> Schwab
  Options -> Schwab (preferred), fallback IBKR
"""
import logging
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from execution.ib_gateway_connector import IBGatewayConnector
    from execution.schwab_connector import SchwabConnector

logger = logging.getLogger(__name__)

# Futures symbols that must go to IBKR
FUTURES_SYMBOLS = {
    "MES", "ES", "MNQ", "NQ", "MCL", "CL", "MGC", "GC",
    "MYM", "YM", "M2K", "RTY", "MBT", "BTC", "MET", "ETH",
    "ZN", "ZB", "ZF", "ZT", "6E", "6B", "6J",
}

FUTURES_PREFIXES = ("M", "E", "C", "Z", "6")  # heuristic for unrecognized symbols


class OrderRouter:
    def __init__(
        self,
        ibkr: Optional["IBGatewayConnector"] = None,
        schwab: Optional["SchwabConnector"] = None,
    ):
        self.ibkr = ibkr
        self.schwab = schwab

    def attach_ibkr(self, connector: "IBGatewayConnector") -> None:
        self.ibkr = connector

    def attach_schwab(self, connector: "SchwabConnector") -> None:
        self.schwab = connector

    def is_futures(self, symbol: str) -> bool:
        return symbol.upper() in FUTURES_SYMBOLS

    def is_options(self, order: dict) -> bool:
        return order.get("asset_type", "").upper() in ("OPT", "OPTION", "OPTIONS")

    async def route_order(self, order: dict) -> dict:
        """
        Dispatch an order dict to the appropriate broker.

        Args:
            order: dict with at minimum {"symbol": str, ...}
                   Include "asset_type": "OPT" for options routing.

        Returns:
            Fill confirmation dict from the executing connector.

        Raises:
            RuntimeError if the required broker is not connected.
        """
        symbol = order.get("symbol", "").upper()

        if self.is_futures(symbol):
            if not self.ibkr or not self.ibkr.is_connected():
                raise RuntimeError(
                    f"IBKR not connected — cannot route futures order for {symbol}"
                )
            logger.info("Routing %s order to IBKR", symbol)
            return await self.ibkr.place_paper_order(order)

        elif self.is_options(order):
            if self.schwab and self.schwab.is_connected:
                logger.info("Routing %s options order to Schwab", symbol)
                return await self.schwab.submit_options_order(order)
            elif self.ibkr and self.ibkr.is_connected():
                logger.info(
                    "Routing %s options order to IBKR (Schwab unavailable)", symbol
                )
                return await self.ibkr.place_paper_order(order)
            else:
                raise RuntimeError("No broker connected for options order")

        else:
            # Equity
            if not self.schwab or not self.schwab.is_connected:
                raise RuntimeError(
                    f"Schwab not connected — cannot route equity order for {symbol}"
                )
            logger.info("Routing %s equity order to Schwab", symbol)
            return await self.schwab.place_paper_order(order)

    def status(self) -> dict:
        return {
            "ibkr_connected": bool(self.ibkr and self.ibkr.is_connected()),
            "schwab_connected": bool(self.schwab and self.schwab.is_connected),
            "futures_broker": (
                "ibkr" if self.ibkr and self.ibkr.is_connected() else "unavailable"
            ),
            "equity_broker": (
                "schwab" if self.schwab and self.schwab.is_connected else "unavailable"
            ),
        }


__all__ = ["OrderRouter", "FUTURES_SYMBOLS"]
