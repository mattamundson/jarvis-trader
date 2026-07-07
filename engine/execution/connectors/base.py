"""
Base Connector Abstraction
==========================
Standard interface for all market connectors (CEX, DEX, Prediction Markets).
Inspired by Hummingbot's Connector architecture.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional


class ConnectorBase(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """The identifier for this connector."""
        pass

    @abstractmethod
    async def connect(self) -> bool:
        """Initialize connection to the exchange."""
        pass

    @abstractmethod
    async def get_balance(self, asset: str) -> float:
        """Get balance for a specific asset."""
        pass

    @abstractmethod
    async def get_price(self, symbol: str) -> float:
        """Get current market price for a symbol."""
        pass

    @abstractmethod
    async def place_order(self, symbol: str, price: float, quantity: float, side: str, order_type: str) -> Dict:
        """Place an order on the exchange."""
        pass

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order."""
        pass

    @abstractmethod
    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict]:
        """Retrieve open orders."""
        pass

    @abstractmethod
    async def get_order_book(self, symbol: str) -> Dict:
        """Retrieve L2/L3 order book data."""
        pass

    def log_trade(self, trade_data: Dict):  # noqa: B027 — intentional default no-op (subclasses opt in)
        """Standardized trade logging across all connectors.

        Default no-op; subclasses can override to add trade-event logging.
        """
        return None
