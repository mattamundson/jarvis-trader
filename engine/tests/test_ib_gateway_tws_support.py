"""
Validates TWS paper-trading support added to IBGatewayManager.

Background
----------
Originally IBGatewayConfig hardcoded port 4002 (IB Gateway paper) and rejected
4001 (Gateway live). TWS paper (7497) and TWS live (7496) were not supported.

This module asserts:
- TWS paper port 7497 is accepted
- TWS live port 7496 is rejected with the same SAFETY VIOLATION semantics as
  Gateway live 4001
- The backward-compat singletons LIVE_TRADING_PORT / PAPER_TRADING_PORT still
  resolve to the historical Gateway values, so external importers don't break.
- _broker_label() returns "Gateway" / "TWS" / "IB" for log messages.
"""

from __future__ import annotations

import pytest

from execution.ib_gateway import (
    LIVE_TRADING_PORT,
    LIVE_TRADING_PORTS,
    PAPER_TRADING_PORT,
    PAPER_TRADING_PORTS,
    IBGatewayConfig,
    IBGatewayManager,
    _broker_label,
)

# ── Constants -----------------------------------------------------------------


def test_live_trading_ports_set_contains_both_live_endpoints():
    assert LIVE_TRADING_PORTS == frozenset({4001, 7496})


def test_paper_trading_ports_set_contains_both_paper_endpoints():
    assert PAPER_TRADING_PORTS == frozenset({4002, 7497})


def test_backward_compat_singletons_unchanged():
    assert LIVE_TRADING_PORT == 4001
    assert PAPER_TRADING_PORT == 4002


# ── _broker_label -------------------------------------------------------------


@pytest.mark.parametrize(
    "port, label",
    [
        (4001, "Gateway"),
        (4002, "Gateway"),
        (7496, "TWS"),
        (7497, "TWS"),
        (9999, "IB"),
    ],
)
def test_broker_label(port: int, label: str):
    assert _broker_label(port) == label


# ── IBGatewayConfig validation -----------------------------------------------


def test_default_config_uses_gateway_paper():
    cfg = IBGatewayConfig()
    assert cfg.port == 4002


def test_tws_paper_port_accepted():
    cfg = IBGatewayConfig(port=7497, account="DU1234567")
    assert cfg.port == 7497


def test_gateway_live_port_rejected_at_construction():
    with pytest.raises(ValueError, match="SAFETY VIOLATION"):
        IBGatewayConfig(port=4001, account="DU1234567")


def test_tws_live_port_rejected_at_construction():
    with pytest.raises(ValueError, match="SAFETY VIOLATION"):
        IBGatewayConfig(port=7496, account="DU1234567")


def test_nonstandard_port_warns_but_does_not_raise(caplog):
    import logging

    caplog.set_level(logging.WARNING)
    cfg = IBGatewayConfig(port=9999, account="DU1234567")
    assert cfg.port == 9999
    assert any("Non-standard IB API port" in r.message for r in caplog.records)


# ── IBGatewayManager construction --------------------------------------------


def test_manager_constructs_with_tws_paper_config():
    cfg = IBGatewayConfig(port=7497, account="DU1234567")
    mgr = IBGatewayManager(cfg)
    assert mgr is not None


def test_manager_rejects_gateway_live_at_construction():
    # __init__ has its own LIVE_TRADING_PORTS check independent of __post_init__,
    # in case a caller bypasses the dataclass somehow. Verify it still raises.
    cfg = IBGatewayConfig()  # default 4002
    object.__setattr__(cfg, "port", 4001)  # bypass __post_init__
    with pytest.raises(ValueError, match="SAFETY VIOLATION"):
        IBGatewayManager(cfg)


def test_manager_rejects_tws_live_at_construction():
    cfg = IBGatewayConfig()
    object.__setattr__(cfg, "port", 7496)
    with pytest.raises(ValueError, match="SAFETY VIOLATION"):
        IBGatewayManager(cfg)
