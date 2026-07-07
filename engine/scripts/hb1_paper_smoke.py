"""
HB-1 Paper Smoke Test — fires a small MES bracket through SafetyLayer and
verifies that the broker-side STP and TP children are linked to the entry
via parent_order_id at IBKR.

Prerequisites:
  1. IB Gateway or TWS running on 127.0.0.1:4002 (paper account, NOT live).
  2. Logged in with paper credentials; API connections enabled.
  3. MES futures market data permissions on the paper account.

Run (from jarvis-trader/engine/):
  .venv\\Scripts\\python.exe scripts\\hb1_paper_smoke.py

What it does:
  - Submits entry MKT + STP child + TP child for 1 MES contract (very small).
  - Reads back all working orders from IB and verifies parent linkage.
  - Cancels all 3 orders (leaves no open risk).
  - Prints PASS/FAIL summary.

Designed to be safe: 1 contract, wide stops, and auto-cancel at the end.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# Ensure engine/ is importable when running from project root.
ENGINE_DIR = Path(__file__).resolve().parent.parent
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

import os  # noqa: E402

os.environ.setdefault("ALLOW_PAPER_SIMULATED_ORDERS", "true")  # enable paper bracket path

from config import settings  # noqa: E402
from execution.ib_gateway import IBGatewayManager  # noqa: E402
from risk.safety_layer import SafetyLayer  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("hb1_smoke")

# Test parameters — tiny exposure.
SYMBOL = "MES"
ENTRY_ACTION = "BUY"           # long entry for the smoke
ENTRY_QTY = 1                  # smallest possible
REFERENCE_PRICE = 5700.0       # used for safety-gate sizing; MKT ignores
STOP_OFFSET_POINTS = 8         # 8 pts * $5/pt = $40 estimated risk (under $50 gate)
TARGET_OFFSET_POINTS = 10      # 10 pts * $5/pt = $50 target

async def main() -> int:
    logger.info("HB-1 paper smoke starting")

    from execution.ib_gateway import IBGatewayConfig
    # Use engine client_id + 1 so the smoke doesn't conflict with the live engine (client_id=1).
    smoke_client_id = getattr(settings, "IBKR_CLIENT_ID", 1) + 1
    ib = IBGatewayManager(
        config=IBGatewayConfig(
            host=getattr(settings, "IBKR_HOST", "127.0.0.1"),
            port=getattr(settings, "IBKR_PORT", 4002),
            client_id=smoke_client_id,
        )
    )

    try:
        await ib.connect()
    except Exception as exc:
        logger.error("IB connect FAILED: %s", exc)
        logger.error(
            "Make sure IB Gateway or TWS is running on 127.0.0.1:4002 with "
            "paper-trading credentials and API enabled (Global Configuration "
            "-> API -> Settings -> Enable ActiveX and Socket Clients)."
        )
        return 2

    if not getattr(ib, "is_connected", lambda: True)():
        logger.error("IB connect returned but is_connected=False")
        return 2
    logger.info("IB connected")

    from config import settings as _settings
    safety = SafetyLayer(config=_settings, ib_gateway=ib)
    stop_price = REFERENCE_PRICE - STOP_OFFSET_POINTS
    target_price = REFERENCE_PRICE + TARGET_OFFSET_POINTS

    logger.info(
        "Submitting entry %s %d %s, stop=%.2f, target=%.2f",
        ENTRY_ACTION, ENTRY_QTY, SYMBOL, stop_price, target_price,
    )

    result = await safety.submit_entry_with_stop(
        symbol=SYMBOL,
        action=ENTRY_ACTION,
        quantity=ENTRY_QTY,
        price=REFERENCE_PRICE,
        stop_price=stop_price,
        target_price=target_price,
    )

    logger.info("submit_entry_with_stop returned:")
    for k, v in result.items():
        logger.info("  %s = %r", k, v)

    # Read back working orders from IB to INDEPENDENTLY verify parent linkage.
    # SafetyLayer's stp_linked/tp_linked booleans only confirm that
    # place_paper_order returned an order_id — they do NOT verify that the
    # resulting IB order actually carries parentId==entry_id. We check that
    # here from the IB-reported state.
    working: list[dict] = []
    try:
        working = await ib.get_open_orders()
    except Exception as exc:
        logger.warning("get_open_orders raised: %s", exc)

    entry_id = result.get("entry_order_id")
    stp_id = result.get("stp_order_id")
    tp_id = result.get("tp_order_id")

    def _find(oid):
        if oid is None:
            return None
        try:
            oid_int = int(oid)
        except (TypeError, ValueError):
            oid_int = oid
        for row in working:
            if row.get("order_id") in (oid, oid_int):
                return row
        return None

    _entry_row = _find(entry_id)  # noqa: F841 — kept for parity/diagnostics
    stp_row = _find(stp_id)
    tp_row = _find(tp_id)

    if working:
        logger.info("IB open orders (%d):", len(working))
        for o in working:
            logger.info(
                "  id=%s parent=%s action=%s type=%s qty=%s aux=%s lmt=%s status=%s",
                o.get("order_id"),
                o.get("parent_id"),
                o.get("action"),
                o.get("order_type"),
                o.get("quantity"),
                o.get("aux_price"),
                o.get("limit_price"),
                o.get("status"),
            )

    # Independent parentId verification (truth vs. SafetyLayer's optimistic flag).
    def _parent_matches(row, expected_parent):
        if row is None or expected_parent is None:
            return False
        try:
            return int(row.get("parent_id") or 0) == int(expected_parent)
        except (TypeError, ValueError):
            return False

    stp_parent_at_ib = _parent_matches(stp_row, entry_id)
    tp_parent_at_ib = _parent_matches(tp_row, entry_id)

    # PASS criteria — use IB-reported truth, not SafetyLayer's return flag.
    approved = bool(result.get("approved"))
    routed = bool(result.get("routed_to_ib"))
    stp_linked = stp_parent_at_ib
    tp_linked = tp_parent_at_ib

    summary = {
        "entry_approved":                 approved,
        "entry_routed_to_ib":             routed,
        "stp_linked (SafetyLayer flag)":  bool(result.get("stp_linked")),
        "stp_linked (IB parentId truth)": stp_linked,
        "tp_linked (SafetyLayer flag)":   bool(result.get("tp_linked")),
        "tp_linked (IB parentId truth)":  tp_linked,
    }

    # Cancel any working orders to leave no open risk.
    for oid, label in ((entry_id, "entry"), (stp_id, "STP"), (tp_id, "TP")):
        if oid is None:
            continue
        try:
            if hasattr(ib, "cancel_order"):
                await ib.cancel_order(oid)
                logger.info("cancelled %s order_id=%s", label, oid)
        except Exception as exc:
            logger.warning("cancel %s order %s raised: %s", label, oid, exc)

    try:
        if hasattr(ib, "disconnect"):
            await ib.disconnect()
    except Exception:
        pass

    logger.info("=" * 60)
    logger.info("HB-1 PAPER SMOKE RESULT")
    for k, v in summary.items():
        logger.info("  %-22s %s", k, "PASS" if v else "FAIL")
    logger.info("=" * 60)

    all_pass = approved and routed and stp_linked and tp_linked

    # Write flag file only on clean 4/4 PASS — consumed by /system/mes-sprint-gate.
    if all_pass:
        import json as _json
        from datetime import datetime, timezone
        results = {
            "entry_approved": approved,
            "entry_routed_to_ib": routed,
            "stp_linked": stp_linked,
            "tp_linked": tp_linked,
        }
        flag_path = Path(__file__).resolve().parent.parent / "data" / "hb1_smoke_passed.json"
        flag_path.parent.mkdir(parents=True, exist_ok=True)
        flag_path.write_text(
            _json.dumps({
                "passed_at": datetime.now(timezone.utc).isoformat(),
                "results": results,
                "ibkr_port": 4002,
            }),
            encoding="utf-8",
        )
        logger.info("Flag file written: %s", flag_path)

    return 0 if all_pass else 1


if __name__ == "__main__":
    rc = asyncio.run(main())
    sys.exit(rc)
