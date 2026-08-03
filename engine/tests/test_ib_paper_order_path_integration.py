"""P0-2 broker-observed proof — REAL IB Gateway on 127.0.0.1:4002 required.

Marked ``integration_ib``; auto-skips when no Gateway socket is reachable, so it
is inert in CI and on any box without the paper Gateway running. Run manually
with the flag armed to prove the real order path end-to-end:

    engine/.venv/Scripts/python.exe -m pytest tests/test_ib_paper_order_path_integration.py -m integration_ib -q

What it proves (the ONLY proof that counts — not pytest-green, not routed_to_ib):
  1. build_order_gateway() with the flag on attaches the REAL IBGatewayManager.
  2. It opens a genuine socket to IB paper (connect() → is_connected()).
  3. A parent entry + child STP submitted via place_paper_order(parent_order_id=)
     are BOTH visible in IB's own open-order state, with the STP's parent_id
     equal to the entry's order id — i.e. the bracket is linked AT the broker,
     not just in a Python dict.

The restart-survival leg of the proof (pm2 stop → STP still rests at IB 60s
later) is inherently a manual runbook step and lives in
docs/ROADMAP_P0-2_SCOPE_2026-07-21.md §6, not in this pytest.

Uses a far-from-market LMT entry that never fills, so nothing actually trades
and no resting market risk is created; both working orders are cancelled in a
finally block regardless of outcome.
"""

from __future__ import annotations

import socket

import pytest

pytestmark = pytest.mark.integration_ib

_IB_HOST = "127.0.0.1"
_IB_PORT = 4002


def _gateway_reachable(host: str = _IB_HOST, port: int = _IB_PORT, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class _ProofSettings:
    """Flag armed, pointed at the paper Gateway on 4002."""

    PAPER_TRADING = True
    IB_PAPER_BROKER_ENABLED = True
    IBKR_HOST = _IB_HOST
    IBKR_PORT = _IB_PORT
    IBKR_CLIENT_ID = 244
    IB_ACCOUNT_ID = ""  # discovered from the session; not asserted here
    IBKR_CONNECT_TIMEOUT_SECONDS = 10.0


@pytest.mark.skipif(
    not _gateway_reachable(), reason="IB Gateway paper (127.0.0.1:4002) not reachable"
)
async def test_real_gateway_bracket_is_parent_linked_at_ib():
    from execution.ib_gateway import IBGatewayManager
    from execution.order_gateway_factory import build_order_gateway

    gw = build_order_gateway(_ProofSettings(), safety_layer=object())
    assert isinstance(gw, IBGatewayManager), "flag-on must attach the REAL gateway"

    connected = await gw.connect()
    assert connected, "real IBGatewayManager failed to connect on 4002"

    entry_id = None
    stp_id = None
    try:
        # Far-below-market LMT BUY — rests as a working order, never fills.
        entry_id = await gw.place_paper_order(
            symbol="MES",
            action="BUY",
            quantity=1,
            order_type="LMT",
            limit_price=1000.0,
        )
        assert entry_id is not None, "entry order was not accepted by IB"

        # Child STP linked to the (unfilled) parent. It stays inactive at IB
        # until the parent fills, but IB still reports the parentId linkage.
        stp_id = await gw.place_paper_order(
            symbol="MES",
            action="SELL",
            quantity=1,
            order_type="STP",
            aux_price=990.0,
            parent_order_id=entry_id,
        )
        assert stp_id is not None, "STP child order was not accepted by IB"

        # Verify from IB's OWN state — not from our return values.
        open_orders = await gw.get_open_orders()
        by_id = {int(o.get("order_id", -1)): o for o in open_orders}
        assert int(entry_id) in by_id, "parent entry not visible in IB open orders"
        assert int(stp_id) in by_id, "STP child not visible in IB open orders"
        assert int(by_id[int(stp_id)].get("parent_id", -1)) == int(entry_id), (
            "STP is not parent-linked at IB — bracket only exists in-process"
        )
    finally:
        # Leave no resting orders behind, whatever happened above.
        try:
            for oid in (stp_id, entry_id):
                if oid is not None:
                    await gw.cancel_order(int(oid))
        finally:
            await gw.disconnect()
