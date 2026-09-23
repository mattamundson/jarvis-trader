"""
ROBINHOOD CONNECTOR — Agentic Trading via MCP (equities only, beta)
=====================================================================
Scaffold only. Robinhood's Agentic Trading connects through an MCP server
(OAuth-authenticated, no client_id/secret) rather than a REST SDK like
schwab-py. The exact MCP endpoint URL, tool schema, and OAuth flow have
NOT been confirmed against Robinhood's live docs from inside this
environment (fetches to robinhood.com returned 403; everything below is
sourced from search-result summaries of Robinhood's own announcement and
press coverage, not verified first-hand). Every network-touching method
below raises NotImplementedError until that verification happens — do
not fill them in from assumptions.

KEY FACTS (UNVERIFIED — confirm against Robinhood's official docs before
relying on any of this):
  - Agentic Trading is equities-only in beta: no options, futures, or
    crypto support. It can never accept any of jarvis-trader's futures
    instruments (MES, MCL, MNQ, M2K, MGC) — see _UNSUPPORTED_FUTURES_SYMBOLS.
  - Orders execute in a separate, ring-fenced "Agentic account" funded
    independently of the main brokerage account. That funding cap is
    Robinhood's own safety net — it is NOT a substitute for SafetyLayer.
  - Auth is OAuth through Robinhood login, not an API key/secret pair.

ROBINHOOD_READY gate is read from config.settings at runtime — never a
module-level hardcode, same pattern as SCHWAB_READY. Do not set
ROBINHOOD_READY=True in .env until:
  1. The real MCP endpoint URL and tool schema are confirmed against
     Robinhood's official documentation (not third-party blog posts).
  2. The NotImplementedError methods below are implemented and
     integration-tested against Robinhood's actual agentic surface.
  3. Tier 3 sign-off, per .claude/rules/safety.md.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)

__all__ = ["RobinhoodConnector", "ConnectionState"]

# Instruments Robinhood Agentic Trading can never accept — equities-only beta.
_UNSUPPORTED_FUTURES_SYMBOLS = frozenset(
    {"MES", "ES", "MCL", "CL", "MNQ", "NQ", "M2K", "RTY", "MGC", "GC"}
)
_EQUITY_SIDES = frozenset({"BUY", "SELL"})


class ConnectionState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


class RobinhoodConnector:
    """
    Scaffold for Robinhood Agentic Trading (MCP-based, equities only).

    Safety contract, matching SchwabConnector: every order path calls
    self._safety_layer.check_order() before touching the broker. The MCP
    transport itself is not implemented (see module docstring) — this
    class exists so config gating, safety-check wiring, and order-router
    dispatch can be built and tested independently of that work.
    """

    def __init__(self, settings, safety_layer=None, portfolio_tracker=None):
        """
        Args:
            settings: TradingConfig — reads ROBINHOOD_MCP_URL,
                ROBINHOOD_AGENTIC_ACCOUNT_ID, ROBINHOOD_READY.
            safety_layer: SafetyLayer — check_order() called before every order.
            portfolio_tracker: PortfolioTracker — for future paper-fill mirroring.
        """
        self._settings = settings
        self._safety_layer = safety_layer
        self._portfolio_tracker = portfolio_tracker
        self._mcp_session = None
        self._state = ConnectionState.DISCONNECTED

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def initialize(self) -> bool:
        """Runs the ROBINHOOD_READY gate and then delegates to connect()."""
        self._assert_robinhood_ready()
        return await self.connect()

    async def connect(self) -> bool:
        """Open an MCP session against ROBINHOOD_MCP_URL. NOT IMPLEMENTED."""
        self._assert_robinhood_ready()
        raise NotImplementedError(
            "RobinhoodConnector.connect: MCP transport not implemented. Confirm the "
            "MCP endpoint URL, OAuth flow, and tool schema against Robinhood's "
            "official agentic-trading docs before implementing this method."
        )

    async def disconnect(self) -> bool:
        """Clean shutdown — release the MCP session."""
        self._mcp_session = None
        self._state = ConnectionState.DISCONNECTED
        logger.info("RobinhoodConnector: disconnected")
        return True

    @property
    def state(self) -> ConnectionState:
        """Public read-only view of connection state."""
        return self._state

    @property
    def is_connected(self) -> bool:
        return self._state == ConnectionState.CONNECTED and self._mcp_session is not None

    # ── Internal Guards ───────────────────────────────────────────────────────

    def _assert_robinhood_ready(self) -> None:
        """Raise RuntimeError if ROBINHOOD_READY is not set True in config."""
        if not getattr(self._settings, "ROBINHOOD_READY", False):
            raise RuntimeError(
                "Robinhood integration incomplete — ROBINHOOD_READY gate not enabled. "
                "Set ROBINHOOD_READY=True in .env only after the MCP transport is "
                "implemented and verified AND after Tier 3 approval — see module docstring."
            )

    def _run_safety_check(
        self, symbol, quantity, order_type, limit_price, portfolio_equity
    ):
        """Run safety layer check. Returns (approved, rejection_reason, warnings)."""
        if self._safety_layer is None:
            return True, None, []
        from risk.safety_layer import OrderRequest  # noqa: PLC0415

        req = OrderRequest(
            symbol=symbol,
            quantity=quantity,
            order_type=order_type,
            limit_price=limit_price,
            is_futures=False,
            is_options=False,
        )
        result = self._safety_layer.check_order(req, portfolio_equity)
        return result.approved, getattr(result, "rejection_reason", ""), result.warnings

    # ── Account ───────────────────────────────────────────────────────────────

    async def get_account_summary(self) -> dict:
        """Agentic-account balances and positions. NOT IMPLEMENTED."""
        if not self.is_connected:
            return {"error": "Robinhood not connected"}
        raise NotImplementedError("RobinhoodConnector.get_account_summary: MCP call not implemented")

    async def get_positions(self) -> list[dict]:
        """Current positions. Returns [] when not connected."""
        if not self.is_connected:
            logger.warning("RobinhoodConnector.get_positions: not connected — returning []")
            return []
        raise NotImplementedError("RobinhoodConnector.get_positions: MCP call not implemented")

    # ── Order Execution ───────────────────────────────────────────────────────

    async def submit_equity_order(
        self,
        symbol: str,
        quantity: int,
        side: str,
        order_type: str = "MARKET",
        limit_price: Optional[float] = None,
    ) -> dict:
        """
        Submit an equity order via MCP. side="BUY"|"SELL". NOT IMPLEMENTED
        beyond validation — returns an error dict for invalid input or when
        not connected, raises NotImplementedError only once a real session exists.
        """
        symbol_upper = symbol.upper()
        if symbol_upper in _UNSUPPORTED_FUTURES_SYMBOLS:
            return {
                "status": "error",
                "reason": f"{symbol_upper} is a futures instrument — Robinhood Agentic "
                "Trading is equities-only (beta)",
            }
        side_upper = side.upper()
        if side_upper not in _EQUITY_SIDES:
            return {"status": "error", "reason": f"Invalid side: {side!r}"}
        if not self.is_connected:
            return {"status": "error", "reason": "Robinhood not connected"}
        raise NotImplementedError("RobinhoodConnector.submit_equity_order: MCP call not implemented")

    async def place_paper_order(self, order: dict) -> dict:
        """
        Safety-integrated entry point — primary method for the order router.

        order keys: symbol, side, quantity, order_type, limit_price, portfolio_equity.
        Returns {"status": "placed"|"rejected"|"error", ...}.
        """
        symbol = order.get("symbol", "UNKNOWN")
        portfolio_equity = float(order.get("portfolio_equity", 0.0))

        if symbol.upper() in _UNSUPPORTED_FUTURES_SYMBOLS:
            return {
                "status": "error",
                "reason": f"{symbol.upper()} is a futures instrument — Robinhood Agentic "
                "Trading is equities-only (beta)",
            }

        if self._safety_layer is not None:
            quantity = int(order.get("quantity", 0))
            approved, reason, warnings = self._run_safety_check(
                symbol=symbol,
                quantity=quantity,
                order_type=order.get("order_type", "market").lower(),
                limit_price=order.get("limit_price"),
                portfolio_equity=portfolio_equity,
            )
            if not approved:
                logger.warning("RobinhoodConnector: REJECTED | %s reason=%s", symbol, reason)
                return {"status": "rejected", "reason": reason, "warnings": warnings}
            for w in warnings:
                logger.warning("RobinhoodConnector: warning | %s", w)

        return await self.submit_equity_order(
            symbol=symbol,
            quantity=int(order.get("quantity", 0)),
            side=order.get("side", "BUY"),
            order_type=order.get("order_type", "MARKET"),
            limit_price=order.get("limit_price"),
        )

    # ── Order Management ──────────────────────────────────────────────────────

    async def get_open_orders(self) -> list[dict]:
        """Open/working orders. Returns [] when not connected."""
        if not self.is_connected:
            return []
        raise NotImplementedError("RobinhoodConnector.get_open_orders: MCP call not implemented")

    async def cancel_all_orders(self) -> int:
        """Cancel all open orders (called by kill switch). Returns count cancelled."""
        if not self.is_connected:
            logger.warning("RobinhoodConnector.cancel_all_orders: not connected")
            return 0
        raise NotImplementedError("RobinhoodConnector.cancel_all_orders: MCP call not implemented")

    async def cancel_order(self, order_id: str) -> dict:
        """Cancel a specific order by ID. Returns an error dict when not connected."""
        if not self.is_connected:
            return {"status": "error", "reason": "Not connected"}
        raise NotImplementedError("RobinhoodConnector.cancel_order: MCP call not implemented")

    async def modify_order(self, order_id: str, new_price: float) -> dict:
        """Modify (replace) an existing order. Returns an error dict when not connected."""
        if not self.is_connected:
            return {"status": "error", "reason": "Not connected"}
        raise NotImplementedError("RobinhoodConnector.modify_order: MCP call not implemented")
