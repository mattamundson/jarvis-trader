"""Regression tests for the autonomous preflight IB-data check.

safety_layer.get_status() carries no IB data keys, so the old check read
`ibkr_connected` / `data_ib_connected` from it and logged "IB data disconnected"
on every tick even with the data leg up -- and therefore could never flag a
real outage either. The check now consults the injected data_manager's IBKR
connector.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import scheduler.pipeline_autonomous as pa

_WARNING = "IB data disconnected"


@pytest.fixture
def _env(monkeypatch):
    monkeypatch.setattr(pa, "is_autonomous_enabled", lambda: True)
    monkeypatch.setattr(pa, "_get_live_trading_enabled", lambda: False)
    safety = MagicMock()
    # Shape of the real SafetyLayer.get_status(): no IB data keys at all.
    safety.get_status.return_value = {"kill_switch_active": False}
    monkeypatch.setattr(pa, "_safety_layer", safety)
    return monkeypatch


def _run(caplog) -> tuple[bool, str]:
    with caplog.at_level(logging.WARNING, logger=pa.logger.name):
        return pa._preflight_check()


def test_no_warning_when_data_manager_ibkr_connected(_env, caplog):
    _env.setattr(pa, "_data_manager", SimpleNamespace(ibkr=SimpleNamespace(is_connected=True)))

    assert _run(caplog) == (True, "ok")
    assert _WARNING not in caplog.text


def test_warns_when_data_manager_ibkr_disconnected(_env, caplog):
    _env.setattr(pa, "_data_manager", SimpleNamespace(ibkr=SimpleNamespace(is_connected=False)))

    assert _run(caplog) == (True, "ok")
    assert _WARNING in caplog.text


def test_warns_when_data_manager_has_no_ibkr(_env, caplog):
    _env.setattr(pa, "_data_manager", SimpleNamespace(ibkr=None))

    assert _run(caplog) == (True, "ok")
    assert _WARNING in caplog.text


def test_falls_back_to_status_keys_without_data_manager(_env, caplog):
    _env.setattr(pa, "_data_manager", None)
    pa._safety_layer.get_status.return_value = {
        "kill_switch_active": False,
        "ibkr_connected": True,
    }

    assert _run(caplog) == (True, "ok")
    assert _WARNING not in caplog.text


def test_kill_switch_still_refuses_before_data_check(_env, caplog):
    _env.setattr(pa, "_data_manager", SimpleNamespace(ibkr=SimpleNamespace(is_connected=True)))
    pa._safety_layer.get_status.return_value = {"kill_switch_active": True}

    ok, reason = _run(caplog)
    assert ok is False
    assert "kill switch" in reason
