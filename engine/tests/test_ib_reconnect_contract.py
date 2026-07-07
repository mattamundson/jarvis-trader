"""RISK-004: IB connector exposes reconnect API (no live Gateway required)."""

from __future__ import annotations

from types import SimpleNamespace

from execution.ib_gateway_connector import IBGatewayConnector


def test_ib_gateway_connector_defines_reconnect_and_retry_cap() -> None:
    cfg = SimpleNamespace(PAPER_TRADING=True)
    conn = IBGatewayConnector(cfg, safety_layer=None)
    assert callable(conn._reconnect)
    assert int(conn._max_reconnect_attempts) >= 1
