"""
JARVIS TRADER — Unified Order Router
=====================================
Routes orders to the correct broker based on instrument type.
  - Futures        → IBKRExecutor
  - Equity Options → SchwabConnector
  - Equity         → SchwabConnector (IBKRExecutor as fallback if Schwab unavailable)

Design principle: the router is intentionally dumb. It reads instrument type
from the OrderRequest and dispatches — no strategy logic lives here.
"""
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.execution.ibkr_executor import IBKRExecutor
    from engine.execution.schwab_connector import SchwabConnector

logger = logging.getLogger(__name__)

# PostgreSQL logging (imported here to avoid circular dependency issues)
_repository = None

__all__ = ["OrderRouter"]


class OrderRouter:
    """
    Single entry-point for all order submission across brokers.

    Both broker handles are optional — the router degrades gracefully if one
    connector failed to initialize (e.g. IBKR Gateway not running).
    """

    def __init__(
        self,
        ibkr: "IBKRExecutor | None",
        schwab: "SchwabConnector | None",
        safety_layer,
    ):
        self._ibkr = ibkr
        self._schwab = schwab
        self._safety_layer = safety_layer

    # ── Routing ───────────────────────────────────────────────────────────────

    async def route_order(self, order, portfolio_equity: float) -> dict:
        """
        Route an order to the correct broker and return the execution result.

        `order` may be either an OrderRequest dataclass or a plain dict with an
        `is_futures` / `is_options` key so the router can make the dispatch
        decision without importing every agent's order format.

        Returns a result dict with at minimum:
          {"status": "placed" | "rejected" | "error", ...}
        """
        # Support both dataclass and dict
        is_futures = getattr(order, "is_futures", None) or (
            isinstance(order, dict) and order.get("is_futures", False)
        )
        is_options = getattr(order, "is_options", None) or (
            isinstance(order, dict) and order.get("is_options", False)
        )
        symbol = getattr(order, "symbol", None) or (
            isinstance(order, dict) and order.get("symbol", "UNKNOWN")
        )

        logger.info(
            "OrderRouter.route_order | symbol=%s is_futures=%s is_options=%s equity=$%.0f",
            symbol, is_futures, is_options, portfolio_equity,
        )

        # ── Futures → IBKR ────────────────────────────────────────────────────
        if is_futures:
            if self._ibkr is None or not self._ibkr.is_connected:
                logger.error("Futures order for %s — IBKR not connected", symbol)
                result = {
                    "status": "error",
                    "reason": "IBKR not connected — cannot execute futures order",
                    "symbol": symbol,
                }
                await self._log_order_result(order, result, is_futures, is_options)
                return result
            logger.info("Routing futures order for %s → IBKR", symbol)
            result = await self._ibkr.submit_futures_order(order, portfolio_equity)
            await self._log_order_result(order, result, is_futures, is_options)
            return result

        # ── Options → Schwab ──────────────────────────────────────────────────
        if is_options:
            if self._schwab is None or not self._schwab.is_connected:
                logger.error("Options order for %s — Schwab not connected", symbol)
                result = {
                    "status": "error",
                    "reason": "Schwab not connected — cannot execute options order",
                    "symbol": symbol,
                }
                await self._log_order_result(order, result, is_futures, is_options)
                return result
            logger.info("Routing options order for %s → Schwab", symbol)
            order_dict = order if isinstance(order, dict) else _order_request_to_dict(order)
            result = await self._schwab.submit_options_order(order_dict, portfolio_equity)
            await self._log_order_result(order, result, is_futures, is_options)
            return result

        # ── Equity → Schwab (fallback to IBKR) ───────────────────────────────
        if self._schwab and self._schwab.is_connected:
            logger.info("Routing equity order for %s → Schwab", symbol)
            order_dict = order if isinstance(order, dict) else _order_request_to_dict(order)
            result = await self._schwab.submit_options_order(order_dict, portfolio_equity)
            await self._log_order_result(order, result, is_futures, is_options)
            return result

        if self._ibkr and self._ibkr.is_connected:
            logger.warning(
                "Schwab unavailable — routing equity order for %s → IBKR (fallback)", symbol
            )
            result = await self._ibkr.submit_futures_order(order, portfolio_equity)
            await self._log_order_result(order, result, is_futures, is_options)
            return result

        logger.error("No broker available for equity order: %s", symbol)
        result = {
            "status": "error",
            "reason": "No broker connected for equity order",
            "symbol": symbol,
        }
        # Log rejected order to PostgreSQL
        await self._log_order_result(order, result, is_futures, is_options)
        return result

    async def _log_order_result(
        self, order: dict, result: dict, is_futures: bool, is_options: bool
    ) -> None:
        """
        Log order execution result to PostgreSQL for audit trail.

        Gracefully handles database unavailability — never blocks execution.

        Args:
            order: Original order dict
            result: Result from broker executor
            is_futures: Whether this is a futures order
            is_options: Whether this is an options order
        """
        try:
            global _repository
            if _repository is None:
                from database import repository
                _repository = repository

            symbol = order.get("symbol", "UNKNOWN") if isinstance(order, dict) else "UNKNOWN"
            quantity = order.get("quantity", 0) if isinstance(order, dict) else 0
            order_type = order.get("order_type", "market") if isinstance(order, dict) else "market"
            status = result.get("status", "unknown")
            broker = "ibkr" if is_futures else "schwab" if is_options else "ibkr"

            # Log to PostgreSQL
            order_id = await _repository.insert_order({
                "symbol": symbol,
                "quantity": quantity,
                "order_type": order_type,
                "limit_price": order.get("limit_price") if isinstance(order, dict) else None,
                "stop_price": order.get("stop_price") if isinstance(order, dict) else None,
                "is_futures": is_futures,
                "is_options": is_options,
                "status": status,
                "broker": broker,
                "broker_order_id": result.get("order_id") or result.get("broker_order_id"),
                "notes": result.get("reason") or result.get("error"),
            })
            logger.debug(f"[DB] Order {order_id} logged: {symbol} {quantity} {status}")

        except Exception as e:
            # Never block order execution due to logging errors
            logger.warning(f"[DB] Failed to log order to PostgreSQL: {e}")

    # ── Kill-Switch Support ───────────────────────────────────────────────────

    async def cancel_all_orders(self) -> dict:
        """
        Cancel ALL open orders on ALL connected brokers.
        Called by the kill switch — must be as fast and fault-tolerant as possible.

        Returns:
          {"ibkr_cancelled": N, "schwab_cancelled": M}
        """
        ibkr_cancelled = 0
        schwab_cancelled = 0
        errors = []

        if self._ibkr and self._ibkr.is_connected:
            try:
                ibkr_cancelled = await self._ibkr.cancel_all_orders()
                logger.info("Kill switch: IBKR cancelled %d orders", ibkr_cancelled)
            except Exception as exc:
                logger.error("Kill switch: IBKR cancel_all_orders failed: %s", exc, exc_info=True)
                errors.append(f"IBKR: {exc}")

        if self._schwab and self._schwab.is_connected:
            try:
                schwab_cancelled = await self._schwab.cancel_all_orders()
                logger.info("Kill switch: Schwab cancelled %d orders", schwab_cancelled)
            except Exception as exc:
                logger.error("Kill switch: Schwab cancel_all_orders failed: %s", exc, exc_info=True)
                errors.append(f"Schwab: {exc}")

        result = {
            "ibkr_cancelled": ibkr_cancelled,
            "schwab_cancelled": schwab_cancelled,
            "total_cancelled": ibkr_cancelled + schwab_cancelled,
        }
        if errors:
            result["errors"] = errors

        logger.warning("cancel_all_orders complete: %s", result)
        return result

    # ── Portfolio Aggregation ─────────────────────────────────────────────────

    async def get_combined_portfolio(self) -> dict:
        """
        Merge position data from both brokers into a single portfolio view.

        The safety layer holds the authoritative equity figure (synced from
        broker every 60 s). This method provides the position-level detail.
        """
        ibkr_summary: dict = {}
        schwab_summary: dict = {}

        if self._ibkr and self._ibkr.is_connected:
            try:
                ibkr_summary = await self._ibkr.get_account_summary()
            except Exception as exc:
                logger.error("get_combined_portfolio: IBKR summary failed: %s", exc)
                ibkr_summary = {"error": str(exc)}

        if self._schwab and self._schwab.is_connected:
            try:
                schwab_summary = await self._schwab.get_account_summary()
            except Exception as exc:
                logger.error("get_combined_portfolio: Schwab summary failed: %s", exc)
                schwab_summary = {"error": str(exc)}

        # Merge positions into a flat list, tagging each with broker
        combined_positions = []
        for pos in ibkr_summary.get("positions", []):
            combined_positions.append({**pos, "broker": "ibkr"})
        for pos in schwab_summary.get("positions", []):
            combined_positions.append({**pos, "broker": "schwab"})

        # Sum equity across brokers where available
        ibkr_equity = ibkr_summary.get("equity") or 0.0
        schwab_equity = schwab_summary.get("equity") or 0.0

        return {
            "total_equity": (ibkr_equity + schwab_equity) or None,
            "ibkr": ibkr_summary,
            "schwab": schwab_summary,
            "positions": combined_positions,
            "position_count": len(combined_positions),
            "safety_layer_status": self._safety_layer.get_status(),
        }

    # ── Broker Status ─────────────────────────────────────────────────────────

    def get_broker_status(self) -> dict:
        """Quick connectivity summary for health checks and dashboard."""
        return {
            "ibkr_connected": self._ibkr.is_connected if self._ibkr else False,
            "schwab_connected": self._schwab.is_connected if self._schwab else False,
            "kill_switch_active": self._safety_layer.is_killed,
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _order_request_to_dict(order) -> dict:
    """Convert an OrderRequest dataclass to the dict format expected by SchwabConnector."""
    return {
        "symbol": order.symbol,
        "action": "buy_to_open" if order.quantity > 0 else "sell_to_close",
        "option_symbol": getattr(order, "option_symbol", order.symbol),
        "quantity": abs(order.quantity),
        "order_type": order.order_type,
        "limit_price": order.limit_price,
        "is_options": order.is_options,
        "is_futures": order.is_futures,
    }
