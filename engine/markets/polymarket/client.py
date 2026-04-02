"""
PolymarketClient — thin wrapper over py-clob-client.
Gracefully handles missing dependencies (module disabled by default).

Install: pip install py-clob-client>=0.17.0 web3>=7.0.0 eth-account>=0.13.0
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("jarvis_trader.markets.polymarket.client")

# Lazy import to avoid crash when not installed
try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import ApiCreds
    CLOB_AVAILABLE = True
except ImportError:
    CLOB_AVAILABLE = False
    ClobClient = None
    ApiCreds = None


POLYMARKET_HOST = "https://clob.polymarket.com"
CHAIN_ID = 137  # Polygon mainnet


class PolymarketClient:
    """
    Wraps the Polymarket CLOB API for order placement and market data.
    All operations are paper/simulation when POLYMARKET_ENABLED=False.
    """

    def __init__(self, api_key: str = "", api_secret: str = "", private_key: str = ""):
        self._api_key = api_key
        self._api_secret = api_secret
        self._private_key = private_key
        self._client: Optional[object] = None
        self._connected = False

    def connect(self) -> bool:
        """Initialize CLOB client connection."""
        if not CLOB_AVAILABLE:
            logger.warning(
                "py-clob-client not installed. "
                "Install: pip install py-clob-client>=0.17.0 web3>=7.0.0 eth-account>=0.13.0"
            )
            return False

        if not self._api_key or not self._private_key:
            logger.warning("Polymarket credentials not configured (POLYMARKET_API_KEY, POLYMARKET_PRIVATE_KEY)")
            return False

        try:
            creds = ApiCreds(
                api_key=self._api_key,
                api_secret=self._api_secret,
                api_passphrase="",
            )
            self._client = ClobClient(
                host=POLYMARKET_HOST,
                chain_id=CHAIN_ID,
                key=self._private_key,
                creds=creds,
            )
            self._connected = True
            logger.info("Polymarket: CLOB client connected")
            return True
        except Exception as exc:
            logger.error(f"Polymarket connect error: {exc}")
            return False

    def is_connected(self) -> bool:
        return self._connected

    def get_markets(self, active_only: bool = True) -> list[dict]:
        """Fetch available prediction markets."""
        if not self._connected or not self._client:
            return []
        try:
            markets = self._client.get_markets()
            if active_only:
                markets = [m for m in markets if m.get("active", False)]
            return markets
        except Exception as exc:
            logger.error(f"get_markets error: {exc}")
            return []

    def get_orderbook(self, token_id: str) -> dict:
        """Get current order book for a market token."""
        if not self._connected or not self._client:
            return {}
        try:
            return self._client.get_order_book(token_id=token_id)
        except Exception as exc:
            logger.error(f"get_orderbook error: {exc}")
            return {}

    def place_limit_order(
        self,
        token_id: str,
        side: str,
        size: float,
        price: float,
    ) -> Optional[dict]:
        """Place a limit order (maker = 0% fee)."""
        if not self._connected or not self._client:
            return None
        try:
            from py_clob_client.clob_types import OrderArgs, OrderType
            order_args = OrderArgs(
                token_id=token_id,
                price=price,
                size=size,
                side=side,
                order_type=OrderType.GTC,
            )
            result = self._client.create_and_post_order(order_args)
            logger.info(f"Polymarket order placed: {side} {size} @ {price} on {token_id}")
            return result
        except Exception as exc:
            logger.error(f"place_limit_order error: {exc}")
            return None

    def get_balance(self) -> float:
        """Get USDC balance on Polygon."""
        if not self._connected or not self._client:
            return 0.0
        try:
            balance_info = self._client.get_balance_allowance()
            return float(balance_info.get("balance", 0))
        except Exception as exc:
            logger.error(f"get_balance error: {exc}")
            return 0.0
