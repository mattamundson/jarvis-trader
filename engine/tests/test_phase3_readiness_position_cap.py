"""
Phase 3 readiness — position_limits_verified gate accepts intentional
$100k MAX_SINGLE_ORDER_VALUE raise.

Background:  handoff-2026-04-09-2354 raised the cap from $5k to $100k so
futures orders (MES notional ~$35k/contract) stop being rejected.  The
readiness gate used to hardcode ``== 5000.0`` and flag any other value as
failure.  We now accept any positive value up to $100k (stricter is fine,
unbounded or zero fails).

Run with:
    cd engine
    .venv\\Scripts\\python.exe -m pytest tests/test_phase3_readiness_position_cap.py -v
"""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

import pytest

_TEST_ENV = {
    "API_KEY": "test-key",
    "POSTGRES_URL": "postgresql://test:test@localhost/test",
    "REDIS_URL": "redis://localhost",
    "POLYGON_API_KEY": "test-key",
    "ANTHROPIC_API_KEY": "test-key",
    "SCHWAB_APP_KEY": "test",
    "SCHWAB_APP_SECRET": "test",
    "FINNHUB_API_KEY": "test",
    "ALPACA_API_KEY": "test",
    "ALPACA_SECRET_KEY": "test",
    "TWILIO_ACCOUNT_SID": "test",
    "TWILIO_AUTH_TOKEN": "test",
    "TWILIO_WHATSAPP_FROM": "+1234567890",
    "WHATSAPP_TO": "+0987654321",
    "TRADINGVIEW_WEBHOOK_SECRET": "jarvis_test_secret_12345",
}
for _k, _v in _TEST_ENV.items():
    os.environ.setdefault(_k, _v)

_ENGINE_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)


@pytest.fixture
def mock_safety_layer():
    layer = MagicMock()
    layer.check_circuit_breakers.return_value = {
        "daily_limit_breached": False,
        "drawdown_breached": False,
        "kill_switch_active": False,
    }
    layer.get_status.return_value = {"kill_switch_active": False}
    return layer


@pytest.mark.asyncio
@pytest.mark.parametrize("cap_value,expected_pass", [
    (5_000.0,   True),   # strict legacy cap still accepted
    (35_000.0,  True),   # typical single-MES-contract notional
    (100_000.0, True),   # documented post-handoff maximum
    (0.0,       False),  # unbounded-effectively / zero disallowed
    (-1.0,      False),  # negative invalid
    (150_000.0, False),  # above documented ceiling
])
async def test_phase3_gate_position_cap_boundaries(
    mock_safety_layer, cap_value, expected_pass
) -> None:
    """position_limits_verified passes for 0 < cap <= $100k, else fails."""
    from config import settings
    from routers import phase3_readiness_router as r

    r.inject_dependencies(mock_safety_layer)

    # Force gate-relevant settings; other gates can fail — we only assert this one.
    with (
        _patch_setting(settings, "MAX_CONTRACTS_PER_INSTRUMENT", 2),
        _patch_setting(settings, "MAX_OVERNIGHT_CONTRACTS", 1),
        _patch_setting(settings, "MAX_POSITION_SIZE_PCT", 0.05),
        _patch_setting(settings, "MAX_SINGLE_ORDER_VALUE", cap_value),
        _patch_setting(settings, "MAX_MARGIN_UTILIZATION", 0.40),
    ):
        payload = await r.get_phase3_readiness()

    gate = payload["gates"]["position_limits_verified"]
    assert gate["passed"] is expected_pass, (
        f"cap={cap_value} expected passed={expected_pass} got {gate['passed']} "
        f"(details: {gate.get('details')})"
    )


class _patch_setting:
    """Tiny context manager for attribute swaps on a Pydantic settings object."""
    def __init__(self, target, name: str, value):
        self.target = target
        self.name = name
        self.value = value
        self._prev = None
        self._had = False

    def __enter__(self):
        self._had = hasattr(self.target, self.name)
        if self._had:
            self._prev = getattr(self.target, self.name)
        object.__setattr__(self.target, self.name, self.value)
        return self

    def __exit__(self, *exc):
        if self._had:
            object.__setattr__(self.target, self.name, self._prev)
        else:
            try:
                object.__delattr__(self.target, self.name)
            except AttributeError:
                pass
