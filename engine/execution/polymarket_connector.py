"""
Polymarket CLOB Connector
==========================
Implementation of Polymarket Central Limit Order Book (CLOB) connectivity.
Enables event-driven prediction market trading.
"""

import logging
from typing import Dict, List, Optional

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import MarketOrderArgs, OrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY

from config import settings

logger = logging.getLogger("jarvis_trader.execution.polymarket")

class PolymarketConnector:
    def __init__(self):
        self.host = getattr(settings, "POLYMARKET_HOST", "https://clob.polymarket.com")
        self.chain_id = getattr(settings, "POLYMARKET_CHAIN_ID", 137) # Polygon
        self.private_key = getattr(settings, "POLYMARKET_PRIVATE_KEY", None)
        self.funder = getattr(settings, "POLYMARKET_FUNDER_ADDRESS", None)

        self.client: Optional[ClobClient] = None
        self.authenticated = False

    async def connect(self) -> bool:
        """Initialize connection to Polymarket CLOB."""
        try:
            if not self.private_key:
                logger.warning("Polymarket: No private key provided. Running in read-only mode.")
                self.client = ClobClient(self.host)
                return True

            self.client = ClobClient(
                self.host,
                key=self.private_key,
                chain_id=self.chain_id,
                signature_type=getattr(settings, "POLYMARKET_SIGNATURE_TYPE", 1), # Default to email/Magic
                funder=self.funder
            )

            # Authenticate
            creds = self.client.create_or_derive_api_creds()
            self.client.set_api_creds(creds)
            self.authenticated = True
            logger.info("✅ Polymarket: Connected and authenticated")
            return True
        except Exception as e:
            logger.error(f"❌ Polymarket: Connection failed: {e}")
            return False

    def get_order_book(self, token_id: str):
        """Retrieve order book for a specific token."""
        if not self.client:
            return None
        return self.client.get_order_book(token_id)

    async def place_order(
        self,
        token_id: str,
        price: float,
        size: float,
        side: str = BUY,
        order_type: OrderType = OrderType.GTC
    ) -> Dict:
        """Place a limit order."""
        if not self.authenticated or not self.client:
            raise RuntimeError("Polymarket: Not authenticated for trading")

        order_args = OrderArgs(
            token_id=token_id,
            price=price,
            size=size,
            side=side
        )
        signed_order = self.client.create_order(order_args)
        resp = self.client.post_order(signed_order, order_type)
        logger.info(f"Polymarket Order Placed: {resp}")
        return resp

    async def place_market_order(
        self,
        token_id: str,
        amount: float,
        side: str = BUY
    ) -> Dict:
        """Place a market order (buy by $ amount)."""
        if not self.authenticated or not self.client:
            raise RuntimeError("Polymarket: Not authenticated for trading")

        mo_args = MarketOrderArgs(
            token_id=token_id,
            amount=amount,
            side=side,
            order_type=OrderType.FOK
        )
        signed_order = self.client.create_market_order(mo_args)
        resp = self.client.post_order(signed_order, OrderType.FOK)
        logger.info(f"Polymarket Market Order Placed: {resp}")
        return resp

    def get_open_orders(self) -> List[Dict]:
        """Get all open orders."""
        if not self.authenticated or not self.client:
            return []
        from py_clob_client.clob_types import OpenOrderParams
        return self.client.get_orders(OpenOrderParams())

    def cancel_order(self, order_id: str):
        """Cancel a specific order."""
        if not self.authenticated or not self.client:
            return
        return self.client.cancel(order_id)

    def cancel_all(self):
        """Cancel all open orders."""
        if not self.authenticated or not self.client:
            return
        return self.client.cancel_all()
