"""P0 acceptance: verify IBGatewayManager.place_bracket_order against LIVE IB paper.

Isolates the new native bracket method — constructs its OWN IBGatewayManager on
port 4002 and talks to IB Gateway paper directly, so it does NOT require the
engine to be running or IB_PAPER_BROKER_ENABLED to be flipped. Use a client_id
distinct from the engine's (default 77) so both can connect at once.

SAFETY:
  - Port 4002 (paper) only. IBGatewayConfig rejects 4001/7496 at construction.
  - Default action is READ-ONLY (--list): connect + print account + open orders.
  - --place actually routes a bracket to the IB PAPER account (Tier-3 action).
    Use a BUY limit BELOW market (won't fill) so the bracket rests without
    taking a position: the STP/TP children sit held at IB, which is exactly the
    "stop rests at the broker" property to observe. Then re-run --list AFTER an
    engine/Gateway restart to confirm the stop SURVIVES the bounce (the thing
    the in-process simulator can never do). --cancel-all cleans up.

Examples:
  # 1. read-only connection + open-order snapshot (safe)
  .venv/Scripts/python.exe scripts/verify_bracket_live.py --list

  # 2. place a non-filling resting bracket (MES buy-limit far below market)
  .venv/Scripts/python.exe scripts/verify_bracket_live.py --place \
      --symbol MES --side BUY --entry LMT --limit 5000 --stop 4950 --target 5200

  # 3. after restarting the engine / Gateway, confirm the stop still rests
  .venv/Scripts/python.exe scripts/verify_bracket_live.py --list

  # 4. clean up
  .venv/Scripts/python.exe scripts/verify_bracket_live.py --cancel-all
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

_ENGINE_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Verify place_bracket_order against live IB paper (4002).")
    p.add_argument("--list", action="store_true", help="Read-only: print connection + open orders (default).")
    p.add_argument("--place", action="store_true", help="Route a bracket to IB paper (Tier-3).")
    p.add_argument("--cancel-all", action="store_true", help="Cancel every open order (cleanup).")
    p.add_argument("--symbol", default="MES")
    p.add_argument("--side", default="BUY", choices=["BUY", "SELL"])
    p.add_argument("--qty", type=int, default=1)
    p.add_argument("--entry", default="LMT", choices=["LMT", "MKT"])
    p.add_argument("--limit", type=float, default=None, help="Entry limit price (LMT only).")
    p.add_argument("--stop", type=float, default=None, help="Stop-loss price.")
    p.add_argument("--target", type=float, default=None, help="Take-profit price.")
    p.add_argument("--client-id", type=int, default=77, help="Distinct from the engine's IBKR_CLIENT_ID.")
    return p.parse_args()


def _print_open_orders(orders: list[dict]) -> None:
    if not orders:
        print("  (no open orders at IB)")
        return
    for o in orders:
        print(
            f"  id={o.get('order_id')} parent={o.get('parent_id')} "
            f"{o.get('action')} {o.get('quantity')} {o.get('symbol')} "
            f"{o.get('order_type')} lmt={o.get('limit_price')} aux={o.get('aux_price')} "
            f"status={o.get('status')}"
        )


async def _run() -> int:
    args = _parse_args()

    from config import settings
    from execution.ib_gateway import IBGatewayConfig, IBGatewayManager

    cfg = IBGatewayConfig(
        host=getattr(settings, "IBKR_HOST", "127.0.0.1"),
        port=int(getattr(settings, "IBKR_PORT", 4002)),  # 4001/7496 rejected in __post_init__
        client_id=args.client_id,
        account=getattr(settings, "IB_ACCOUNT_ID", "") or "",
        timeout=float(getattr(settings, "IBKR_CONNECT_TIMEOUT_SECONDS", 10.0)),
    )
    mgr = IBGatewayManager(cfg)

    print(f"Connecting to IB paper {cfg.host}:{cfg.port} client_id={cfg.client_id} account={cfg.account or '(auto)'} ...")
    if not await mgr.connect():
        print(f"FAILED to connect (last_error={getattr(mgr, '_last_error', None)}). Is IB Gateway paper running on {cfg.port}?")
        return 2
    print("Connected.")

    try:
        summary = await mgr.get_account_summary()
        if summary:
            print(f"Account: NetLiq={summary.get('NetLiquidation')} Cash={summary.get('TotalCashValue')}")

        if args.cancel_all:
            orders = await mgr.get_open_orders()
            print(f"Cancelling {len(orders)} open order(s)...")
            for o in orders:
                ok = await mgr.cancel_order(o.get("order_id"))
                print(f"  cancel id={o.get('order_id')} -> {ok}")
            return 0

        if args.place:
            if args.entry == "LMT" and args.limit is None:
                print("ERROR: --limit is required for an LMT entry.")
                return 1
            print(
                f"PLACING bracket: {args.side} {args.qty} {args.symbol} {args.entry} "
                f"limit={args.limit} stop={args.stop} target={args.target}"
            )
            result = await mgr.place_bracket_order(
                symbol=args.symbol,
                action=args.side,
                quantity=args.qty,
                entry_type=args.entry,
                limit_price=args.limit,
                stop_loss=args.stop,
                take_profit=args.target,
            )
            print(f"place_bracket_order -> {result}")
            if result.get("status") != "placed":
                print("Bracket was NOT placed. See error above.")
                return 1
            # Read the legs back FROM IB to prove they rest at the broker.
            await asyncio.sleep(1.0)
            print("Open orders AT IB after placement (expect entry + STP/TP children with parent linkage):")
            _print_open_orders(await mgr.get_open_orders())
            # Confirm broker-side parent linkage the safety layer relies on.
            for leg_key in ("sl_id", "tp_id"):
                leg_id = result.get(leg_key)
                if leg_id is not None:
                    status = await mgr.get_order_status(str(leg_id))
                    print(f"  {leg_key}={leg_id} parent_order_id at IB = {status.get('parent_order_id')} (expect {result.get('entry_id')})")
            return 0

        # Default: read-only snapshot (also the post-restart survival check).
        print("Open orders AT IB (a resting STP here after a restart = the stop survived):")
        _print_open_orders(await mgr.get_open_orders())
        return 0

    finally:
        try:
            await mgr.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
