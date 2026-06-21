"""
Unit tests -- /health IB sub-check time budget (_ib_health_bounded).

Proves that a stalled IB gateway health_check() cannot block /health past
IB_HEALTH_TIMEOUT_S: the bounded helper cancels the slow check and returns a
degraded 'timeout' leg, while a fast check passes through unchanged.

Mutation proof: replace `_ib_health_bounded` body with a bare
`await _get_ib_gateway_health()` (no wait_for) and test_times_out_on_stall
hangs ~5s and fails the budget assertion -- so the wait_for is load-bearing.

Run with the engine venv:
    engine/.venv/Scripts/python.exe -m pytest engine/tests/test_health_ib_timebox.py -q
"""

import asyncio
import os
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("API_KEY", "test-key")

import routers.health_router as hr  # noqa: E402


def test_times_out_on_stall(monkeypatch=None):
    """A health_check that never returns in time -> bounded 'timeout' leg, fast."""
    async def _slow():
        await asyncio.sleep(5.0)
        return {"status": "connected"}

    orig_timeout = hr.IB_HEALTH_TIMEOUT_S
    orig_fn = hr._get_ib_gateway_health
    hr.IB_HEALTH_TIMEOUT_S = 0.2
    hr._get_ib_gateway_health = _slow
    try:
        t0 = time.monotonic()
        result = asyncio.run(hr._ib_health_bounded())
        elapsed = time.monotonic() - t0
        assert result["status"] == "timeout", result
        assert result["execution_connected"] is False
        assert result["data_connected"] is False
        assert "degraded_reason" in result
        # Must return on the budget, not after the 5s stall.
        assert elapsed < 1.0, f"took {elapsed:.2f}s -- wait_for not bounding the call"
    finally:
        hr.IB_HEALTH_TIMEOUT_S = orig_timeout
        hr._get_ib_gateway_health = orig_fn


def test_fast_path_passes_through():
    """When the IB check resolves in time, its real dict is returned unchanged."""
    async def _fast():
        return {"status": "connected", "execution_connected": True, "data_connected": True}

    orig_fn = hr._get_ib_gateway_health
    hr._get_ib_gateway_health = _fast
    try:
        result = asyncio.run(hr._ib_health_bounded())
        assert result["status"] == "connected"
        assert result["execution_connected"] is True
        assert "degraded_reason" not in result
    finally:
        hr._get_ib_gateway_health = orig_fn


if __name__ == "__main__":
    import traceback

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        try:
            fn()
            passed += 1
            print(f"PASS {fn.__name__}")
        except Exception:  # noqa: BLE001
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{passed}/{len(fns)} passed")
    sys.exit(0 if passed == len(fns) else 1)
