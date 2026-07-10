"""
JARVIS TRADER — IB Order Manager
===================================
Bridge between SafetyLayer and IBGatewayManager for paper-order submission
and position reconciliation.

Responsibilities
----------------
1. submit_order()           — validate via SafetyLayer then route to IBGatewayManager
2. sync_positions_from_ib() — fetch live IB positions, update PortfolioTracker
3. reconcile()              — compare IB positions vs PortfolioTracker, log discrepancies

Architecture contract
---------------------
- PAPER TRADING ONLY.  IBGatewayManager enforces port 4002 at construction time.
- ALL orders MUST flow through SafetyLayer.submit_paper_order() — bypassing it
  is not possible from this class; submit_order() always goes through the layer.
- No LLM reasoning in this module — pure plumbing and logging.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from engine.execution.ib_gateway import IBGatewayManager
    from engine.portfolio.tracker import PortfolioTracker
    from engine.risk.safety_layer import SafetyLayer

logger = logging.getLogger(__name__)

__all__ = ["IBOrderManager"]


class IBOrderManager:
    """
    Bridges SafetyLayer + IBGatewayManager for paper-order submission and
    position reconciliation.

    Parameters
    ----------
    safety_layer : SafetyLayer
        The singleton SafetyLayer instance.  Every order passes through it.
    ib_gateway : IBGatewayManager
        The IBGatewayManager connected to port 4002 (paper).
    portfolio_tracker : PortfolioTracker | None
        Optional tracker to keep in sync with IB positions.
        If None, sync_positions_from_ib() and reconcile() are no-ops
        with respect to tracker mutations.
    """

    def __init__(
        self,
        safety_layer: "SafetyLayer",
        ib_gateway: "IBGatewayManager",
        portfolio_tracker: Optional["PortfolioTracker"] = None,
    ) -> None:
        self._safety = safety_layer
        self._gateway = ib_gateway
        self._tracker = portfolio_tracker

        gateway_status = (
            self._gateway.is_connected() if self._gateway is not None else "not_connected"
        )
        logger.info(
            "IBOrderManager initialised | gateway_connected=%s tracker=%s",
            gateway_status,
            "attached" if portfolio_tracker is not None else "none",
        )

    # ── Order Submission ──────────────────────────────────────────────────────

    async def submit_order(
        self,
        symbol: str,
        action: str,
        quantity: int,
        price: float,
        order_type: str = "MKT",
        limit_price: Optional[float] = None,
    ) -> dict:
        """
        Validate via SafetyLayer, then route to IB Gateway (paper mode).

        The SafetyLayer holds the ib_gateway reference and calls
        place_paper_order() itself after every risk check passes.
        This method is the public entry-point that strategies / agents should
        use — it never bypasses the safety checks.

        Parameters
        ----------
        symbol      : Ticker or futures root (e.g. "MES", "AAPL").
        action      : "BUY" or "SELL".
        quantity    : Positive integer lot size.
        price       : Estimated execution price for value / position size checks.
        order_type  : "MKT" (default) or "LMT".
        limit_price : Required for LMT orders.

        Returns
        -------
        dict
            Same dict returned by SafetyLayer.submit_paper_order():
              approved (bool), reason (str), order_id (str|None),
              routed_to_ib (bool).
        """
        logger.info(
            "IBOrderManager.submit_order | symbol=%s action=%s qty=%d price=%.4f type=%s limit=%s",
            symbol,
            action.upper(),
            quantity,
            price,
            order_type,
            limit_price,
        )

        if self._safety.is_killed:
            logger.warning(
                "IBOrderManager.submit_order: kill switch is active — "
                "order for %s will be rejected by SafetyLayer immediately.",
                symbol,
            )

        result = await self._safety.submit_paper_order(
            symbol=symbol,
            action=action,
            quantity=quantity,
            price=price,
            order_type=order_type,
            limit_price=limit_price,
        )

        log_level = logging.INFO if result.get("approved") else logging.WARNING
        logger.log(
            log_level,
            "IBOrderManager.submit_order result | symbol=%s approved=%s "
            "routed=%s order_id=%s reason=%s",
            symbol,
            result.get("approved"),
            result.get("routed_to_ib"),
            result.get("order_id"),
            result.get("reason"),
        )
        return result

    async def submit_bracket_order(
        self,
        symbol: str,
        action: str,
        quantity: int,
        price: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        order_type: str = "MKT",
        limit_price: Optional[float] = None,
    ) -> dict:
        """
        Place an atomic bracket order via SafetyLayer.
        """
        logger.info(
            "IBOrderManager.submit_bracket_order | symbol=%s action=%s qty=%d "
            "price=%.2f SL=%.2f TP=%.2f",
            symbol, action.upper(), quantity, price, stop_loss or 0, take_profit or 0
        )

        if self._safety.is_killed:
            return {"approved": False, "reason": "Kill switch active"}

        result = await self._safety.submit_paper_bracket_order(
            symbol=symbol,
            action=action,
            quantity=quantity,
            price=price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            order_type=order_type,
            limit_price=limit_price,
        )

        return result

    # ── Position Sync ─────────────────────────────────────────────────────────

    async def sync_positions_from_ib(self) -> list[dict]:
        """
        Fetch current positions from IB Gateway and update PortfolioTracker.

        For each IB position that does not yet exist in the tracker's open
        trades, an open_trade() entry is created so the tracker stays in sync
        with the broker's ground truth.

        Returns
        -------
        list[dict]
            The raw position list returned by IBGatewayManager.get_positions().
            Each item: symbol, sec_type, quantity, avg_cost, market_value,
                       is_futures, contract_month, exchange, currency.
        """
        if not self._gateway.is_connected():
            logger.warning("sync_positions_from_ib: IB Gateway not connected — skipping sync")
            return []

        logger.info("sync_positions_from_ib: fetching positions from IB Gateway...")

        try:
            ib_positions: list[dict] = await self._gateway.get_positions()
        except Exception as exc:
            logger.error(
                "sync_positions_from_ib: get_positions() failed: %s",
                exc,
                exc_info=True,
            )
            return []

        logger.info("sync_positions_from_ib: received %d positions from IB", len(ib_positions))

        if self._tracker is None:
            logger.debug(
                "sync_positions_from_ib: no PortfolioTracker attached — "
                "returning raw IB positions without syncing"
            )
            return ib_positions

        # Build set of symbols already tracked in open trades
        tracker_open_symbols = {t.symbol for t in self._tracker._open.values()}

        # Best-effort symbol -> resting stop price map, so a newly-synced
        # position prefers IB's own real resting STP/STP LMT order (if one
        # exists) over a synthesized fallback -- see docs/incident-notes/
        # 2026-04-09-mcl-inverted-stop.md and PR #331. A lookup failure must
        # never block the sync.
        stop_by_symbol: dict[str, float] = {}
        try:
            open_orders = await self._gateway.get_open_orders()
        except Exception as exc:
            logger.debug("sync_positions_from_ib: get_open_orders() failed: %s", exc)
            open_orders = []

        for order in open_orders:
            order_type = str(order.get("order_type", "")).upper()
            if order_type not in ("STP", "STP LMT", "STP_LMT", "STPLMT"):
                continue
            aux_price = order.get("aux_price")
            order_sym = order.get("symbol")
            if order_sym and aux_price:
                stop_by_symbol[order_sym] = float(aux_price)

        for pos in ib_positions:
            sym = pos.get("symbol", "")
            qty = pos.get("position", 0)
            avg_cost = pos.get("avg_cost", 0.0)

            if qty == 0:
                continue  # Skip flat positions

            if sym not in tracker_open_symbols:
                action = "buy" if qty > 0 else "sell"
                # #287 fix: a reconcile backfill has no pipeline stop in scope
                # (IB's raw position list carries no stop info). Prefer IB's own
                # real resting stop order (found above) when one exists -- it's
                # the actual broker-side stop, more accurate than a guess. Only
                # fall back to synthesizing a defensive stop from the same
                # dollar-risk budget as PaperStopMonitor's catastrophe cap when
                # IB holds no resting stop for this position. See
                # services.paper_stop_monitor for the single source of truth
                # the fallback reuses.
                resolved_stop = stop_by_symbol.get(sym)
                stop_source = "ib_resting_order" if resolved_stop is not None else None
                if resolved_stop is None:
                    try:
                        from services.paper_stop_monitor import synthesize_fallback_stop

                        resolved_stop = synthesize_fallback_stop(sym, action, avg_cost, abs(qty))
                        if resolved_stop is not None:
                            stop_source = "synthesized_fallback"
                    except Exception as _stop_err:  # pragma: no cover - defensive
                        logger.debug(
                            "sync_positions_from_ib: stop synthesis failed for %s (non-fatal): %s",
                            sym,
                            _stop_err,
                        )
                trade_id = self._tracker.open_trade(
                    symbol=sym,
                    action=action,
                    quantity=abs(qty),
                    price=avg_cost,
                    notes=(
                        f"synced from IB Gateway | "
                        f"sec_type={pos.get('sec_type')} "
                        f"exchange={pos.get('exchange')}"
                    ),
                    stop_loss=resolved_stop,
                    stop_source=stop_source,
                )
                logger.info(
                    "sync_positions_from_ib: opened tracker entry for IB position "
                    "symbol=%s qty=%d avg_cost=%.4f trade_id=%s",
                    sym,
                    qty,
                    avg_cost,
                    trade_id,
                )
            else:
                logger.debug(
                    "sync_positions_from_ib: symbol=%s already in tracker — skipping",
                    sym,
                )

        return ib_positions

    # ── Reconciliation ────────────────────────────────────────────────────────

    def _build_tracker_map(self, tracker: "PortfolioTracker") -> dict[str, float]:
        """Build symbol → signed quantity map from tracker."""
        tracker_map: dict[str, float] = {}
        for trade in tracker._open.values():
            sym = trade.symbol
            signed = (
                trade.quantity
                if trade.action.lower() in ("buy", "buy_to_open")
                else -trade.quantity
            )
            tracker_map[sym] = tracker_map.get(sym, 0.0) + signed
        return tracker_map

    def _compare_positions(
        self,
        result: dict,
        ib_map: dict[str, float],
        tracker_map: dict[str, float],
    ) -> None:
        """Compare IB vs tracker positions and populate result lists."""
        all_symbols = set(ib_map) | set(tracker_map)

        for sym in sorted(all_symbols):
            ib_qty = ib_map.get(sym, 0.0)
            tr_qty = tracker_map.get(sym, 0.0)

            if sym in ib_map and sym not in tracker_map:
                result["missing_in_tracker"].append(sym)
                logger.warning(
                    "reconcile DISCREPANCY: %s is in IB (qty=%.0f) but NOT in PortfolioTracker",
                    sym,
                    ib_qty,
                )
            elif sym in tracker_map and sym not in ib_map:
                result["missing_in_ib"].append(sym)
                logger.warning(
                    "reconcile DISCREPANCY: %s is in PortfolioTracker (qty=%.0f) but NOT in IB",
                    sym,
                    tr_qty,
                )
            elif abs(ib_qty - tr_qty) > 0.01:
                result["qty_mismatches"].append(
                    {
                        "symbol": sym,
                        "ib_qty": ib_qty,
                        "tracker_qty": tr_qty,
                        "delta": ib_qty - tr_qty,
                    }
                )
                logger.warning(
                    "reconcile QTY MISMATCH: %s — IB=%.0f tracker=%.0f delta=%+.0f",
                    sym,
                    ib_qty,
                    tr_qty,
                    ib_qty - tr_qty,
                )
            else:
                logger.debug("reconcile: %s in sync (qty=%.0f)", sym, ib_qty)

    async def reconcile(
        self,
        portfolio_tracker: Optional["PortfolioTracker"] = None,
        ib_gateway: Optional["IBGatewayManager"] = None,
    ) -> dict:
        """
        Compare IB positions vs PortfolioTracker and log any discrepancies.

        Callers can pass override arguments to reconcile against a different
        tracker or gateway than the ones used at construction time (useful in
        tests and audit scripts).

        Parameters
        ----------
        portfolio_tracker : PortfolioTracker | None
            Override the tracker used at __init__.  Falls back to self._tracker.
        ib_gateway : IBGatewayManager | None
            Override the gateway used at __init__.  Falls back to self._gateway.

        Returns
        -------
        dict
            {
                "ib_positions":       list[dict],
                "tracker_positions":  list[dict],
                "missing_in_tracker": list[str],
                "missing_in_ib":      list[str],
                "qty_mismatches":     list[dict],
                "in_sync":            bool,
            }
        """
        tracker = portfolio_tracker or self._tracker
        gateway = ib_gateway or self._gateway

        result: dict = {
            "ib_positions": [],
            "tracker_positions": [],
            "missing_in_tracker": [],
            "missing_in_ib": [],
            "qty_mismatches": [],
            "in_sync": False,
        }

        if gateway is None or not gateway.is_connected():
            logger.warning("reconcile: IB Gateway not connected — cannot reconcile")
            return result

        try:
            ib_positions: list[dict] = await gateway.get_positions()
        except Exception as exc:
            logger.error("reconcile: get_positions() raised: %s", exc, exc_info=True)
            return result

        result["ib_positions"] = ib_positions

        # Build IB symbol → signed quantity map
        ib_map: dict[str, float] = {}
        for pos in ib_positions:
            sym = pos.get("symbol", "")
            qty = pos.get("position", 0)
            if sym and qty != 0:
                ib_map[sym] = qty

        # Build tracker positions
        tracker_map: dict[str, float] = {}
        if tracker is not None:
            tracker_map = self._build_tracker_map(tracker)
            result["tracker_positions"] = [
                {"symbol": s, "quantity": q} for s, q in tracker_map.items()
            ]
        else:
            logger.warning(
                "reconcile: no PortfolioTracker provided — IB positions cannot "
                "be compared to tracker state"
            )

        # Compare positions
        self._compare_positions(result, ib_map, tracker_map)

        discrepancies = (
            len(result["missing_in_tracker"])
            + len(result["missing_in_ib"])
            + len(result["qty_mismatches"])
        )
        result["in_sync"] = discrepancies == 0

        if result["in_sync"]:
            logger.info(
                "reconcile: ALL %d symbols in sync between IB and PortfolioTracker",
                len(set(ib_map) | set(tracker_map)),
            )
        else:
            logger.warning(
                "reconcile: %d discrepancy/ies found — "
                "missing_in_tracker=%d  missing_in_ib=%d  qty_mismatches=%d",
                discrepancies,
                len(result["missing_in_tracker"]),
                len(result["missing_in_ib"]),
                len(result["qty_mismatches"]),
            )

        return result

    # ── Status ────────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        """Return a quick summary dict suitable for health checks and dashboards."""
        return {
            "ib_gateway_connected": self._gateway.is_connected(),
            "kill_switch_active": self._safety.is_killed,
            "safety_layer_status": self._safety.get_status(),
            "tracker_attached": self._tracker is not None,
        }
