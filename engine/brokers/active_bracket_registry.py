"""
JARVIS TRADER — Active Bracket Order Registry
=============================================
In-memory tracker for all live IB bracket order IDs (entry + STP + TP)
across all symbols.  Provides the account-level order coordination layer
that sits above per-trade OCA groups:

  Per-trade OCA (IB-side)          : STP + TP within one trade cancel each other
  Account-level (this module)      : kill switch → cancel ALL pending entries
                                     so unfilled entry orders don't fill after
                                     trading is halted.

Design
------
- Pure in-memory dict, thread-safe via threading.Lock.
- No DB dependency — order lifecycle is ephemeral; filled positions are
  tracked in the portfolio tracker.
- cancel_all_entries(): cancels only PENDING entry orders (entry_filled=False).
  Leaves STP/TP children intact so already-filled positions stay protected.
- cancel_all(): cancels every tracked leg — emergency flatten path.
- Singleton via get_registry(); importable anywhere without circular risk.

Integration
-----------
- submit_bracket() registers on success (§6.7 wiring).
- safety_layer.activate_kill_switch() schedules cancel_all_entries() via
  _schedule_background_coro so pending entries cannot fill after halt.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("jarvis_trader.brokers.active_bracket_registry")


@dataclass
class BracketRecord:
    symbol: str
    entry_id: str
    stp_id: Optional[str]
    tp_id: Optional[str]
    oca_group: Optional[str] = None
    submitted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    entry_filled: bool = False


class ActiveBracketRegistry:
    """Thread-safe in-memory registry of active IB bracket orders."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: dict[str, BracketRecord] = {}  # keyed by entry_id

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def register(
        self,
        symbol: str,
        entry_id: str,
        stp_id: Optional[str],
        tp_id: Optional[str],
        oca_group: Optional[str] = None,
    ) -> None:
        with self._lock:
            self._records[entry_id] = BracketRecord(
                symbol=symbol,
                entry_id=entry_id,
                stp_id=stp_id,
                tp_id=tp_id,
                oca_group=oca_group,
            )
        logger.info(
            "ActiveBracketRegistry.register: symbol=%s entry=%s stp=%s tp=%s oca=%s",
            symbol,
            entry_id,
            stp_id,
            tp_id,
            oca_group,
        )

    def mark_entry_filled(self, entry_id: str) -> None:
        """Mark an entry order as filled so cancel_all_entries() skips it."""
        with self._lock:
            rec = self._records.get(entry_id)
            if rec:
                rec.entry_filled = True
                logger.debug(
                    "ActiveBracketRegistry.mark_entry_filled: entry=%s symbol=%s",
                    entry_id,
                    rec.symbol,
                )

    def unregister(self, entry_id: str) -> None:
        """Remove a bracket record when the position is fully closed."""
        with self._lock:
            removed = self._records.pop(entry_id, None)
        if removed:
            logger.info(
                "ActiveBracketRegistry.unregister: entry=%s symbol=%s",
                entry_id,
                removed.symbol,
            )

    def get_all(self) -> list[BracketRecord]:
        """Return a snapshot of all currently registered bracket records."""
        with self._lock:
            return list(self._records.values())

    def count(self) -> int:
        with self._lock:
            return len(self._records)

    # ── Cancel paths ───────────────────────────────────────────────────────────

    async def cancel_all_entries(self, ib_gateway) -> dict:
        """Cancel pending entry orders whose entries have not yet been filled.

        Leaves STP/TP children intact — they protect already-open positions.
        Called by the kill switch path to prevent a queued entry from filling
        while trading is halted.

        Parameters
        ----------
        ib_gateway:
            Must have a ``cancel_order(order_id: int)`` coroutine.
            Passing None or a gateway without cancel_order is a no-op.

        Returns
        -------
        dict:
            cancelled       : list of entry_id strings successfully cancelled
            errors          : list of {entry_id, symbol, error} dicts
            skipped_filled  : count of records skipped because entry was filled
        """
        if ib_gateway is None:
            return {"cancelled": [], "errors": [], "skipped_filled": 0}

        with self._lock:
            pending = [(r.entry_id, r.symbol) for r in self._records.values() if not r.entry_filled]
            skipped = sum(1 for r in self._records.values() if r.entry_filled)

        cancel_fn = getattr(ib_gateway, "cancel_order", None)
        if not callable(cancel_fn):
            # Report as errors, not a silent empty result: this is called from
            # the kill-switch path specifically to stop pending entries from
            # filling after a halt. A gateway missing cancel_order leaves
            # every one of `pending` still live and unprotected -- the same
            # defect class as the already-fixed get_cached_position gap
            # (2026-08-03 MES overage incident). Populating `errors` here
            # makes the existing caller-side `if result.get("errors"):
            # logger.error(...)` in safety_layer.activate_kill_switch() fire,
            # instead of this looking identical to "nothing was pending."
            if pending:
                logger.error(
                    "ActiveBracketRegistry.cancel_all_entries: gateway has no "
                    "cancel_order -- %d pending entries could NOT be cancelled "
                    "(kill switch entry-cancel defanged)",
                    len(pending),
                )
            else:
                logger.warning("ActiveBracketRegistry.cancel_all_entries: gateway has no cancel_order")
            errors = [
                {"entry_id": eid, "symbol": sym, "error": "gateway has no cancel_order method"}
                for eid, sym in pending
            ]
            return {"cancelled": [], "errors": errors, "skipped_filled": skipped}

        cancelled: list[str] = []
        errors: list[dict] = []
        for entry_id, symbol in pending:
            try:
                await cancel_fn(int(entry_id))
                cancelled.append(entry_id)
                logger.warning(
                    "ActiveBracketRegistry.cancel_all_entries: cancelled pending entry=%s "
                    "symbol=%s (kill switch triggered)",
                    entry_id,
                    symbol,
                )
            except Exception as exc:
                errors.append({"entry_id": entry_id, "symbol": symbol, "error": str(exc)})
                logger.error(
                    "ActiveBracketRegistry.cancel_all_entries: failed entry=%s symbol=%s: %s",
                    entry_id,
                    symbol,
                    exc,
                )

        return {"cancelled": cancelled, "errors": errors, "skipped_filled": skipped}

    async def cancel_all(self, ib_gateway) -> dict:
        """Cancel ALL tracked legs (entry + STP + TP).

        Emergency use only — called by the emergency flatten path.
        Unlike cancel_all_entries(), this cancels STP/TP children too, which
        removes price protection from open positions.  Only appropriate when
        positions are being closed via MKT orders simultaneously.

        Returns
        -------
        dict:
            cancelled : list of {order_id, symbol, leg} dicts
            errors    : list of {order_id, symbol, leg, error} dicts
        """
        if ib_gateway is None:
            return {"cancelled": [], "errors": []}

        with self._lock:
            all_legs: list[tuple[str, str, str]] = []
            for r in self._records.values():
                all_legs.append((r.entry_id, r.symbol, "entry"))
                if r.stp_id:
                    all_legs.append((r.stp_id, r.symbol, "stp"))
                if r.tp_id:
                    all_legs.append((r.tp_id, r.symbol, "tp"))

        cancel_fn = getattr(ib_gateway, "cancel_order", None)
        if not callable(cancel_fn):
            # See cancel_all_entries() above for why this reports as errors
            # rather than a silent empty result -- this is the emergency
            # flatten path, an even higher-stakes caller than kill switch.
            if all_legs:
                logger.error(
                    "ActiveBracketRegistry.cancel_all: gateway has no cancel_order "
                    "-- %d legs could NOT be cancelled",
                    len(all_legs),
                )
            else:
                logger.warning("ActiveBracketRegistry.cancel_all: gateway has no cancel_order")
            errors = [
                {
                    "order_id": order_id,
                    "symbol": symbol,
                    "leg": leg,
                    "error": "gateway has no cancel_order method",
                }
                for order_id, symbol, leg in all_legs
            ]
            return {"cancelled": [], "errors": errors}

        cancelled: list[dict] = []
        errors: list[dict] = []
        for order_id, symbol, leg in all_legs:
            try:
                await cancel_fn(int(order_id))
                cancelled.append({"order_id": order_id, "symbol": symbol, "leg": leg})
                logger.warning(
                    "ActiveBracketRegistry.cancel_all: cancelled %s=%s symbol=%s",
                    leg,
                    order_id,
                    symbol,
                )
            except Exception as exc:
                errors.append(
                    {"order_id": order_id, "symbol": symbol, "leg": leg, "error": str(exc)}
                )
                logger.error(
                    "ActiveBracketRegistry.cancel_all: failed %s=%s symbol=%s: %s",
                    leg,
                    order_id,
                    symbol,
                    exc,
                )

        return {"cancelled": cancelled, "errors": errors}


# ── Module-level singleton ────────────────────────────────────────────────────

_registry = ActiveBracketRegistry()


def get_registry() -> ActiveBracketRegistry:
    """Return the global ActiveBracketRegistry singleton."""
    return _registry
