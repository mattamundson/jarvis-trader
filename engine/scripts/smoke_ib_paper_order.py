#!/usr/bin/env python3
"""
IB Gateway Paper E2E Smoke Test.

Purpose: prove the full paper execution path works end-to-end — TCP connect
→ contract qualify → order place → fill event → round-trip close — against a
live IB Gateway running on port 4002. Unlike the offline connector tests
under engine/tests/test_ib_gateway_offline_extended.py, this script places
real paper orders and waits for real IB fill events.

Prereqs (user action):
    1. Launch IB Gateway in paper mode (account DUP662235).
    2. In Gateway → Configure → Settings → API → Settings:
       - Enable ActiveX and Socket Clients: checked
       - Socket port: 4002
       - Read-Only API: UNCHECKED (otherwise order placement is rejected)
       - Master API client ID: blank (or match IB_CLIENT_ID below)
    3. Wait ~10s for Gateway to finish login/auth.

Usage:
    python -m scripts.smoke_ib_paper_order                 # MCL, 1 contract, MKT round-trip
    python -m scripts.smoke_ib_paper_order --symbol MES    # use MES instead
    python -m scripts.smoke_ib_paper_order --dry-connect   # connect + qualify only, no order

Exit codes:
    0 = clean round-trip (fill + close fill)
    2 = Gateway unreachable on port 4002
    3 = connect/auth failed
    4 = contract qualification failed
    5 = order place failed
    6 = fill timeout
    7 = round-trip close failed
"""

from __future__ import annotations

import argparse
import asyncio
import logging
<<<<<<< HEAD
=======
import os
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
import socket
import sys
import time
from pathlib import Path

ENGINE_DIR = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ENGINE_DIR))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("ib_smoke")

# Client ID 7 chosen to avoid colliding with the engine's default client_id=1
# and any other long-running ib_async clients.
IB_CLIENT_ID = 7
IB_HOST = "127.0.0.1"
IB_PORT = 4002
FILL_TIMEOUT_SEC = 30


def _port_is_listening(host: str, port: int, timeout: float = 1.0) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        return sock.connect_ex((host, port)) == 0
    finally:
        sock.close()


async def _wait_for_fill(ib, order_id: int, label: str, timeout: float) -> bool:
    """Poll ib.trades() for the matching trade and wait for filled status."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        for trade in ib.trades():
            if trade.order.orderId == order_id:
                status = trade.orderStatus.status
                if status == "Filled":
                    fills = trade.fills
                    price = fills[-1].execution.price if fills else None
                    logger.info("%s FILLED | order_id=%d price=%s qty=%d",
                                label, order_id, price,
                                trade.orderStatus.filled)
                    return True
                if status in ("Cancelled", "ApiCancelled", "Inactive"):
                    logger.error("%s TERMINAL non-fill | order_id=%d status=%s",
                                 label, order_id, status)
                    return False
        await asyncio.sleep(0.5)
    logger.error("%s FILL TIMEOUT after %.1fs | order_id=%d", label, timeout, order_id)
    return False


async def _run(symbol: str, quantity: int, dry_connect: bool) -> int:
    # Pre-flight: is port 4002 listening at all?
    if not _port_is_listening(IB_HOST, IB_PORT):
        logger.error("IB Gateway not listening on %s:%d. Launch Gateway in paper mode.",
                     IB_HOST, IB_PORT)
        return 2

    from execution.ib_gateway import IBGatewayConfig, IBGatewayManager

    cfg = IBGatewayConfig(
        host=IB_HOST,
        port=IB_PORT,
        client_id=IB_CLIENT_ID,
        timeout=10.0,
        readonly=False,
<<<<<<< HEAD
        account="DUP662235",
=======
        account=os.environ.get("IB_ACCOUNT_ID", ""),
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
    )
    manager = IBGatewayManager(cfg)

    connected = await manager.connect()
    if not connected:
        logger.error("connect() returned False. Gateway rejected auth or API disabled?")
        return 3

    logger.info("Connected to IB Gateway %s:%d client_id=%d account=%s",
                IB_HOST, IB_PORT, IB_CLIENT_ID, cfg.account)

    try:
        contract = manager._resolve_contract(symbol)
        if contract is None:
            logger.error("_resolve_contract returned None for %s", symbol)
            return 4

        qualified = await manager._qualify_contract(contract)
        if qualified is None:
            logger.error("IB refused to qualify contract %s", contract)
            return 4
        logger.info("Qualified contract | %s (conId=%s, exchange=%s)",
                    symbol, getattr(qualified, "conId", "?"),
                    getattr(qualified, "exchange", "?"))

        if dry_connect:
            logger.info("--dry-connect: skipping order placement.")
            return 0

        # Leg 1: BUY
        buy_id = await manager.place_paper_order(
            symbol=symbol, action="BUY", quantity=quantity, order_type="MKT"
        )
        if buy_id is None:
            logger.error("BUY place_paper_order returned None")
            return 5
        buy_filled = await _wait_for_fill(manager._ib, buy_id, "BUY", FILL_TIMEOUT_SEC)
        if not buy_filled:
            return 6

        # Leg 2: SELL (round-trip close)
        sell_id = await manager.place_paper_order(
            symbol=symbol, action="SELL", quantity=quantity, order_type="MKT"
        )
        if sell_id is None:
            logger.error("SELL place_paper_order returned None")
            return 7
        sell_filled = await _wait_for_fill(manager._ib, sell_id, "SELL", FILL_TIMEOUT_SEC)
        if not sell_filled:
            return 7

        logger.info("SMOKE TEST PASSED | symbol=%s qty=%d buy_id=%d sell_id=%d",
                    symbol, quantity, buy_id, sell_id)
        return 0

    finally:
        try:
            await manager.disconnect()
            logger.info("Disconnected from IB Gateway cleanly.")
        except Exception as exc:
            logger.warning("Disconnect raised: %s", exc)


def main() -> int:
    parser = argparse.ArgumentParser(description="IB Gateway paper E2E smoke")
    parser.add_argument("--symbol", default="MCL",
                        help="Futures symbol to trade (default: MCL)")
    parser.add_argument("--quantity", type=int, default=1,
                        help="Contracts per leg (default: 1)")
    parser.add_argument("--dry-connect", action="store_true",
                        help="Connect + qualify only; do not place any order.")
    args = parser.parse_args()

    logger.info("=== IB paper smoke started | symbol=%s qty=%d dry_connect=%s ===",
                args.symbol, args.quantity, args.dry_connect)

    rc = asyncio.run(_run(args.symbol, args.quantity, args.dry_connect))

    logger.info("=== IB paper smoke done | rc=%d ===", rc)
    return rc


if __name__ == "__main__":
    sys.exit(main())
