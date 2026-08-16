"""
Unit tests — /health data-leg round-trip verification.

`_get_ib_gateway_health()` used to trust `_ib_is_connected(data_ib)` (a shallow
local socket flag) for `data_connected` unconditionally. That flag stayed True
for hours during the 2026-08-15 wedge incident (Gateway socket open, API dead),
so `ibkr_data_connected` never flipped even though every real data request was
hanging. `data_ib.health_check()` now does a bounded round-trip probe
(`reqCurrentTimeAsync`, see data/market_data.py); this file verifies
`_get_ib_gateway_health()` actually consults it instead of the shallow flag
alone, and does so regardless of whether an execution connector is also present
(the pre-fix code only ever called `health_check()` on whichever connector
`ib_gw` resolved to, which prefers the execution connector when both exist).

Run with the engine venv:
    engine/.venv/Scripts/python.exe -m pytest engine/tests/test_health_data_leg_roundtrip.py -q
"""

from __future__ import annotations

import os
import pathlib
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("API_KEY", "test-key")

import routers.health_router as hr  # noqa: E402


class _FakeDataConnector:
    """Shallow-connected (`is_connected=True`) but whose health_check() may
    report the round-trip result differently -- models a wedged data leg."""

    def __init__(self, *, shallow_connected: bool, roundtrip_connected: bool):
        self.is_connected = shallow_connected
        self._roundtrip_connected = roundtrip_connected

    async def health_check(self) -> dict:
        return {
            "status": "connected" if self._roundtrip_connected else "wedged",
            "connected": self._roundtrip_connected,
        }


class _FakeExecutionConnector:
    """Genuinely healthy execution connector -- present to prove the data-leg
    override applies independent of which connector `ib_gw` resolves to."""

    def __init__(self):
        self.is_connected = True

    async def health_check(self) -> dict:
        return {"status": "connected", "connected": True, "execution_connected": True}


@pytest.fixture(autouse=True)
def _reset_globals():
    yield
    hr.data_manager = None
    hr.safety_layer = None


@pytest.mark.asyncio
async def test_data_connected_false_when_shallow_true_but_roundtrip_fails():
    hr.data_manager = SimpleNamespace(
        ibkr=_FakeDataConnector(shallow_connected=True, roundtrip_connected=False)
    )
    hr.safety_layer = None

    health = await hr._get_ib_gateway_health()

    assert health["data_connected"] is False


@pytest.mark.asyncio
async def test_data_connected_true_when_shallow_true_and_roundtrip_succeeds():
    hr.data_manager = SimpleNamespace(
        ibkr=_FakeDataConnector(shallow_connected=True, roundtrip_connected=True)
    )
    hr.safety_layer = None

    health = await hr._get_ib_gateway_health()

    assert health["data_connected"] is True


@pytest.mark.asyncio
async def test_data_leg_override_applies_even_when_execution_connector_present():
    """The pre-fix code only ever probed whichever connector `ib_gw` resolved
    to (execution_ib preferred when both exist), so a wedged data leg was
    invisible whenever an execution connector was also configured. This is
    the exact regression case."""
    hr.data_manager = SimpleNamespace(
        ibkr=_FakeDataConnector(shallow_connected=True, roundtrip_connected=False)
    )
    hr.safety_layer = SimpleNamespace(_ib_gateway=_FakeExecutionConnector())

    health = await hr._get_ib_gateway_health()

    assert health["execution_connected"] is True
    assert health["data_connected"] is False


@pytest.mark.asyncio
async def test_no_roundtrip_probe_when_shallow_already_false():
    """No wedge to detect if the shallow flag already says disconnected --
    the new gated data-leg probe should skip it entirely. An execution
    connector is present so `ib_gw` resolves to it, isolating this from the
    pre-existing (ungated) `ib_gw.health_check()` call, which is a separate
    code path this test isn't exercising."""
    probed = {"called": False}

    class _NeverProbed(_FakeDataConnector):
        async def health_check(self):
            probed["called"] = True
            return await super().health_check()

    hr.data_manager = SimpleNamespace(
        ibkr=_NeverProbed(shallow_connected=False, roundtrip_connected=True)
    )
    hr.safety_layer = SimpleNamespace(_ib_gateway=_FakeExecutionConnector())

    health = await hr._get_ib_gateway_health()

    assert health["data_connected"] is False
    assert probed["called"] is False
