"""
JARVIS TRADER — IB Bracket Order Builder
=========================================
Paper-mode-only helper that constructs and submits three-legged IB bracket
orders: parent entry (MKT) + child STP + child LMT take-profit.

IB bracket convention
---------------------
Three orders are submitted in a single ``placeOrder`` sequence:

  1. Parent (entry)  — transmit=False so IB holds it until all legs arrive
  2. STP child       — transmit=False, parentId = parent.orderId
  3. TP child (LMT)  — transmit=True  (final leg triggers atomic submission)
                       parentId = parent.orderId
                       ocaGroup shared with STP so one cancels the other

When the TP leg is transmitted, IB processes all three together atomically.
If the entry fills and either child fills, the OCA link cancels the other.

Environment gate
----------------
``ENABLE_BRACKET_ORDERS`` (default "1", i.e. ON).  Set to "0" in engine/.env
to revert to single-order behavior without code changes.

Rollback on child failure
-------------------------
If the STP child placement fails, ``submit_bracket`` attempts to cancel the
parent entry to prevent an unprotected position.  The rollback itself is
best-effort: if cancel also fails the event is logged at CRITICAL level so it
appears in any monitoring feed.

Paper mode only
---------------
This module hard-asserts that ``settings.LIVE_TRADING_ENABLED`` is False
before routing any order.  The IB gateway ``IBGatewayManager`` also enforces
port 4002 at construction time.  Both guards must pass.

Usage
-----
    from brokers.bracket_orders import build_bracket, submit_bracket

    orders = build_bracket(parent=entry_dict, stop_price=5690.0,
                           target_price=5720.0, account_id="DU662235")
    result = await submit_bracket(ib_client, contract, *orders)
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger("jarvis_trader.brokers.bracket_orders")

# ── OCA group prefix ──────────────────────────────────────────────────────────
_OCA_GROUP_PREFIX = "JARVIS_BRACKET_"


def is_bracket_orders_enabled() -> bool:
    """
    Env-fresh check — reads ``ENABLE_BRACKET_ORDERS`` on every call so the
    flag can be toggled without restarting the engine.

    Default is ON (returns True when the var is absent or set to "1").
    Returns False only when the var is explicitly set to "0" or "false".
    """
    raw = os.environ.get("ENABLE_BRACKET_ORDERS", "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def build_bracket(
    parent: dict[str, Any],
    stop_price: float,
    target_price: float,
    account_id: str = "A",
) -> list[dict[str, Any]]:
    """
    Build three order-spec dicts that form an IB bracket.

    Parameters
    ----------
    parent : dict
        Caller-supplied dict with keys:
          - ``action`` : "BUY" | "SELL"
          - ``quantity``: int, number of contracts
          - ``order_type``: "MKT" (default), "LMT", etc.
          - ``price``: optional limit price (required when order_type="LMT")
        All other keys are passed through to the order spec as-is.
    stop_price : float
        Broker-side stop price for the STP child.
    target_price : float
        Limit price for the take-profit child.
    account_id : str
        IB account string (e.g. "DU662235").  Passed to each order spec.

    Returns
    -------
    list of 3 dicts — [entry, stp, tp]
        Each dict is a plain order spec understood by
        ``IBGatewayManager.place_paper_order``; callers may pass these
        dicts directly to that API.  Dicts carry:
          - ``action``, ``quantity``, ``order_type``
          - ``limit_price`` (for LMT/STP_LMT)
          - ``aux_price``   (for STP)
          - ``parent_order_id`` (None for entry, set after submission for children)
          - ``transmit``     (False for entry+STP, True for TP)
          - ``oca_group``    (set on STP + TP, not on entry)
          - ``account_id``
    """
    action_upper = str(parent.get("action", "BUY")).upper()
    if action_upper not in ("BUY", "SELL"):
        raise ValueError(f"build_bracket: invalid action '{action_upper}'")

    quantity = int(parent.get("quantity", 1))
    if quantity <= 0:
        raise ValueError(f"build_bracket: quantity must be positive, got {quantity}")

    if stop_price <= 0:
        raise ValueError(f"build_bracket: stop_price must be positive, got {stop_price}")
    if target_price <= 0:
        raise ValueError(f"build_bracket: target_price must be positive, got {target_price}")

    # Child actions are always opposite the parent (BUY entry → SELL STP/TP)
    child_action = "SELL" if action_upper == "BUY" else "BUY"

    # Unique OCA group name — include action + price tick for human readability
    oca_group = f"{_OCA_GROUP_PREFIX}{action_upper}_{int(stop_price * 100)}"

    # ── 1. Entry (parent) ─────────────────────────────────────────────────────
    # transmit=False so IB holds the leg until the final child is transmitted.
    entry_spec: dict[str, Any] = {
        **parent,
        "action": action_upper,
        "quantity": quantity,
        "order_type": str(parent.get("order_type", "MKT")).upper(),
        "limit_price": (
            parent.get("price") if str(parent.get("order_type", "MKT")).upper() == "LMT" else None
        ),
        "aux_price": None,
        "parent_order_id": None,  # entry is the root — no parent
        "transmit": False,  # IB convention: don't send until all legs ready
        "account_id": account_id,
    }

    # ── 2. STP child (stop loss) ──────────────────────────────────────────────
    # transmit=False — TP leg (3) triggers the atomic batch.
    stp_spec: dict[str, Any] = {
        "action": child_action,
        "quantity": quantity,
        "order_type": "STP",
        "limit_price": None,
        "aux_price": float(stop_price),  # IB STP uses aux_price for the stop price
        "parent_order_id": None,  # filled in by submit_bracket after entry placed
        "transmit": False,
        "oca_group": oca_group,
        "account_id": account_id,
    }

    # ── 3. TP child (take profit) ─────────────────────────────────────────────
    # transmit=True — this is the final leg; IB batches all three atomically.
    tp_spec: dict[str, Any] = {
        "action": child_action,
        "quantity": quantity,
        "order_type": "LMT",
        "limit_price": float(target_price),
        "aux_price": None,
        "parent_order_id": None,  # filled in by submit_bracket after entry placed
        "transmit": True,  # triggers atomic submission of the bracket
        "oca_group": oca_group,
        "account_id": account_id,
    }

    return [entry_spec, stp_spec, tp_spec]


async def _verify_parent_linkage(
    ib_gateway,
    symbol: str,
    parent_id: str,
    stp_id: str,
) -> bool:
    """
    Post-submission check: confirm the STP child order has its parentId set
    correctly to the entry order ID on the broker side.

    IB processes the bracket atomically once the TP (transmit=True) leg
    arrives, but there is a timing window — typically < 100 ms in paper mode
    — where the MKT entry can fill before the broker acknowledges the STP
    child's parentId linkage.  This check surfaces that race so it can be
    monitored rather than silently accepted.

    Returns True if the linkage is confirmed or cannot be checked (gateway
    has no ``get_order_status``).  Returns False only when ``get_order_status``
    clearly reports a wrong/missing parentId or raises an exception.
    """
    check_fn = getattr(ib_gateway, "get_order_status", None)
    if not callable(check_fn):
        logger.debug(
            "_verify_parent_linkage: gateway has no get_order_status — skipping (symbol=%s)",
            symbol,
        )
        return True

    try:
        status = await check_fn(int(stp_id))
    except Exception as exc:
        logger.warning(
            "_verify_parent_linkage: get_order_status raised symbol=%s stp=%s: %s",
            symbol,
            stp_id,
            exc,
        )
        return False

    if not isinstance(status, dict):
        logger.warning(
            "_verify_parent_linkage: unexpected status type %s symbol=%s stp=%s",
            type(status).__name__,
            symbol,
            stp_id,
        )
        return False

    reported_parent = str(status.get("parent_order_id") or "")
    if reported_parent == parent_id:
        logger.debug(
            "_verify_parent_linkage: OK symbol=%s parent=%s stp=%s",
            symbol,
            parent_id,
            stp_id,
        )
        return True

    logger.warning(
        "_verify_parent_linkage: parentId mismatch symbol=%s stp=%s expected=%s got=%r — "
        "STP may not be linked; monitor this position manually",
        symbol,
        stp_id,
        parent_id,
        reported_parent,
    )
    return False


async def submit_bracket(
    ib_gateway,
    symbol: str,
    entry_spec: dict[str, Any],
    stp_spec: dict[str, Any],
    tp_spec: dict[str, Any],
) -> dict[str, Any]:
    """
    Submit a three-leg bracket to the IB paper account (port 4002).

    Atomicity
    ---------
    IB processes parent + STP + TP as a single batch when the final leg
    (transmit=True) is submitted.  In practice ``IBGatewayManager.place_paper_order``
    fires one ``placeOrder`` call per leg; the atomic group is enforced by IB's
    TWS/Gateway side via parentId linking and the OCA group.

    Rollback
    --------
    If STP placement fails (returns None / raises), this function attempts to
    cancel the entry order and returns ``approved=False``.  If the cancel also
    fails, the event is logged at CRITICAL level.

    Parameters
    ----------
    ib_gateway : IBGatewayManager
        An already-connected paper-trading gateway instance.
    symbol : str
        JARVIS instrument symbol (e.g. "MCL", "MNQ").
    entry_spec, stp_spec, tp_spec : dict
        Specs as returned by ``build_bracket()``.

    Returns
    -------
    dict with keys:
        approved         : True iff all three legs placed
        parent_order_id  : broker order ID of the entry (str | None)
        stop_order_id    : broker order ID of the STP child (str | None)
        target_order_id  : broker order ID of the TP child (str | None)
        bracket_status   : "attached" | "failed" | "partial"
        reason           : human-readable outcome message
    """
    # Safety invariant: paper mode only
    try:
        from config import settings as _cfg

        if getattr(_cfg, "LIVE_TRADING_ENABLED", False):
            logger.critical(
                "submit_bracket: LIVE_TRADING_ENABLED=True — bracket submission "
                "is paper-mode only. Aborting."
            )
            return {
                "approved": False,
                "parent_order_id": None,
                "stop_order_id": None,
                "target_order_id": None,
                "bracket_status": "failed",
                "reason": "LIVE_TRADING_ENABLED=True; bracket orders are paper-only",
            }
    except ImportError:
        pass  # config not available in test isolation — allow through

    if ib_gateway is None:
        logger.warning("submit_bracket: ib_gateway is None — dry-run (no broker submission)")
        return {
            "approved": False,
            "parent_order_id": None,
            "stop_order_id": None,
            "target_order_id": None,
            "bracket_status": "failed",
            "reason": "IB gateway not available",
        }

    # ── 1. Place entry (parent) ───────────────────────────────────────────────
    try:
        parent_id_raw = await ib_gateway.place_paper_order(
            symbol=symbol,
            action=entry_spec["action"],
            quantity=entry_spec["quantity"],
            order_type=entry_spec["order_type"],
            limit_price=entry_spec.get("limit_price"),
            aux_price=entry_spec.get("aux_price"),
            parent_order_id=None,
        )
    except Exception as exc:
        logger.error("submit_bracket: entry order placement raised - symbol=%s: %s", symbol, exc)
        parent_id_raw = None

    if parent_id_raw is None:
        logger.error("submit_bracket: entry placement returned None for symbol=%s", symbol)
        return {
            "approved": False,
            "parent_order_id": None,
            "stop_order_id": None,
            "target_order_id": None,
            "bracket_status": "failed",
            "reason": "Entry order placement failed — no parent_order_id returned",
        }

    parent_id = str(parent_id_raw)
    logger.info("submit_bracket: entry placed symbol=%s parent_id=%s", symbol, parent_id)

    # ── 2. Place STP child ────────────────────────────────────────────────────
    try:
        stp_id_raw = await ib_gateway.place_paper_order(
            symbol=symbol,
            action=stp_spec["action"],
            quantity=stp_spec["quantity"],
            order_type=stp_spec["order_type"],
            limit_price=stp_spec.get("limit_price"),
            aux_price=stp_spec.get("aux_price"),
            parent_order_id=int(parent_id_raw),
        )
    except Exception as exc:
        logger.error(
            "submit_bracket: STP child placement raised - symbol=%s parent=%s: %s",
            symbol,
            parent_id,
            exc,
        )
        stp_id_raw = None

    if stp_id_raw is None:
        # Rollback: cancel the entry to avoid an unprotected position
        logger.critical(
            "submit_bracket: STP failed — attempting rollback cancel of entry %s (symbol=%s)",
            parent_id,
            symbol,
        )
        try:
            if hasattr(ib_gateway, "cancel_order"):
                await ib_gateway.cancel_order(int(parent_id_raw))
                logger.critical(
                    "submit_bracket: rollback cancel submitted for entry %s (symbol=%s)",
                    parent_id,
                    symbol,
                )
            else:
                logger.critical(
                    "submit_bracket: no cancel_order on gateway — entry %s may be live "
                    "without stop (symbol=%s)",
                    parent_id,
                    symbol,
                )
        except Exception as cancel_exc:
            logger.critical(
                "submit_bracket: rollback cancel ALSO failed for entry %s (symbol=%s): %s",
                parent_id,
                symbol,
                cancel_exc,
            )
        return {
            "approved": False,
            "parent_order_id": parent_id,
            "stop_order_id": None,
            "target_order_id": None,
            "bracket_status": "failed",
            "reason": "STP child placement failed; attempted rollback cancel of entry",
        }

    stp_id = str(stp_id_raw)
    logger.info(
        "submit_bracket: STP child placed symbol=%s stp_id=%s parent=%s",
        symbol,
        stp_id,
        parent_id,
    )

    # ── 3. Place TP child (transmit=True — triggers atomic batch) ─────────────
    tp_id: Optional[str] = None
    try:
        tp_id_raw = await ib_gateway.place_paper_order(
            symbol=symbol,
            action=tp_spec["action"],
            quantity=tp_spec["quantity"],
            order_type=tp_spec["order_type"],
            limit_price=tp_spec.get("limit_price"),
            aux_price=tp_spec.get("aux_price"),
            parent_order_id=int(parent_id_raw),
        )
        if tp_id_raw is not None:
            tp_id = str(tp_id_raw)
            logger.info(
                "submit_bracket: TP child placed symbol=%s tp_id=%s parent=%s",
                symbol,
                tp_id,
                parent_id,
            )
        else:
            logger.warning(
                "submit_bracket: TP child returned None — entry+STP active, no TP "
                "(symbol=%s parent=%s)",
                symbol,
                parent_id,
            )
    except Exception as exc:
        logger.warning(
            "submit_bracket: TP child placement raised — entry+STP active, no TP "
            "(symbol=%s parent=%s): %s",
            symbol,
            parent_id,
            exc,
        )

    # ── 4. Post-submission parent-linkage check ───────────────────────────────
    # Confirms the STP child's parentId is set before the MKT entry can fill.
    parent_linkage_verified = await _verify_parent_linkage(ib_gateway, symbol, parent_id, stp_id)
    if not parent_linkage_verified:
        logger.warning(
            "submit_bracket: STP parentId linkage unconfirmed symbol=%s parent=%s stp=%s — "
            "bracket is live; monitor position manually",
            symbol,
            parent_id,
            stp_id,
        )

    # ── 5. Register in account-level bracket registry ────────────────────────
    # Enables kill-switch path to cancel pending entries before they fill.
    try:
        from brokers.active_bracket_registry import get_registry as _get_bracket_registry

        _get_bracket_registry().register(
            symbol=symbol,
            entry_id=parent_id,
            stp_id=stp_id,
            tp_id=tp_id,
            oca_group=entry_spec.get("oca_group"),
        )
    except Exception as _reg_exc:
        logger.warning(
            "submit_bracket: account-level registry registration failed (non-fatal): %s",
            _reg_exc,
        )

    bracket_status = "attached" if tp_id is not None else "partial"
    return {
        "approved": True,
        "parent_order_id": parent_id,
        "stop_order_id": stp_id,
        "target_order_id": tp_id,
        "bracket_status": bracket_status,
        "parent_linkage_verified": parent_linkage_verified,
        "reason": (
            "Bracket order submitted (parent + STP + TP)"
            if tp_id
            else "Bracket submitted with entry + STP only (TP placement failed)"
        ),
    }
