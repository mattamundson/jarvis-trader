"""
Unit tests -- /health IB Gateway sub-check must be time-boxed (2026-08-03).

_get_ib_gateway_health() awaited ib_gw.health_check() with no timeout of its own.
With IB Gateway down (wrong port, not logged in, dead process) that blocks on the
connector's internal connect timeout, so /health, /health/full, and
/ib/connection-test all stall indefinitely -- observed 30s+ hang 2026-08-03 while
IB Gateway sat on the live port (4001) instead of paper (4002). Wrapped the
health_check() call in asyncio.wait_for(3.0); on timeout it returns a degraded
status="timeout" leg instead of hanging the whole endpoint.

Run with the engine venv:
    engine/.venv/Scripts/python.exe -m pytest engine/tests/test_health_ib_timebox.py -q
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("API_KEY", "test-key")

import pytest  # noqa: E402

import routers.health_router as hr  # noqa: E402


class _StalledIBGateway:
    """A connector whose health_check() never returns within any reasonable
    test budget -- simulates IB Gateway down / wrong port / dead connect."""

    is_connected = False

    async def health_check(self) -> dict:
        await asyncio.sleep(30)
        return {"status": "connected"}  # pragma: no cover - never reached


class _FastIBGateway:
    """A healthy connector whose health_check() returns immediately."""

    is_connected = True

    async def health_check(self) -> dict:
        return {"status": "connected"}


class _FakeSafetyLayer:
    def __init__(self, ib_gateway) -> None:
        self._ib_gateway = ib_gateway


@pytest.mark.asyncio
async def test_stalled_ib_health_check_times_out_bounded():
    hr.safety_layer = _FakeSafetyLayer(_StalledIBGateway())
    hr.data_manager = None
    try:
        started = time.monotonic()
        health = await asyncio.wait_for(hr._get_ib_gateway_health(), timeout=10.0)
        elapsed = time.monotonic() - started
    finally:
        hr.safety_layer = None

    assert elapsed < 5.0, f"_get_ib_gateway_health() took {elapsed:.1f}s, should be bounded ~3s"
    assert health["status"] == "timeout"


@pytest.mark.asyncio
async def test_fast_ib_health_check_passes_through_unchanged():
    hr.safety_layer = _FakeSafetyLayer(_FastIBGateway())
    hr.data_manager = None
    try:
        health = await hr._get_ib_gateway_health()
    finally:
        hr.safety_layer = None

    assert health["status"] == "connected"
    assert health["execution_connected"] is True


if __name__ == "__main__":
    asyncio.run(test_stalled_ib_health_check_times_out_bounded())
    asyncio.run(test_fast_ib_health_check_passes_through_unchanged())
    print("2/2 passed")
