"""
JARVIS TRADER — Settings Router: POST /strategy/params/reset (GT-39)
======================================================================
GT-39 (dashboard-integrity audit, 2026-07-28): dashboard/components/
StrategyParamsPanel.tsx's "Reset to Defaults" button called
POST /strategy/params/reset, a route the engine never registered (only
GET and PUT /strategy/params existed). The button silently 404'd.

This test pins the new POST /strategy/params/reset route: it must restore
every StrategyParams field to its pydantic default regardless of prior
mutation via PUT /strategy/params, and must return the same
status/old_params/new_params response shape as PUT.

Run with:
    cd engine
    .venv\\Scripts\\python.exe -m pytest tests/test_settings_router_strategy_params_reset.py -v --tb=short
"""

from __future__ import annotations

import os
import sys

import pytest

# ---------------------------------------------------------------------------
# Environment bootstrap — mirrors tests/test_settings_router_max_contracts.py
# ---------------------------------------------------------------------------


def _load_env() -> None:
    """Load .env into os.environ (mirrors conftest pattern used in other tests)."""
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(env_path):
        with open(env_path) as fh:
            for line in fh:
                line = line.strip()
                if line and "=" in line and not line.startswith("#"):
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key, value)


_load_env()

_ENGINE_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    """FastAPI TestClient wrapping just settings_router."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers.settings_router import inject_dependencies
    from routers.settings_router import router as settings_router

    inject_dependencies(None, None, None)

    app = FastAPI()
    app.include_router(settings_router)
    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# POST /strategy/params/reset tests
# ---------------------------------------------------------------------------


def test_reset_route_exists(client):
    """
    GT-39 regression: the route the dashboard's Reset button calls must
    exist and return 200, not 404.
    """
    resp = client.post("/strategy/params/reset", json={})
    assert resp.status_code == 200, (
        f"POST /strategy/params/reset returned {resp.status_code} — "
        f"the dashboard Reset button 404 has regressed: {resp.text}"
    )


def test_reset_restores_defaults_after_mutation(client):
    """
    Mutate every field away from its default via PUT, then reset — every
    field must come back to the pydantic default, not just some subset.
    """
    mutated = {
        "ema_short": 5,
        "ema_long": 40,
        "ema_smoother": 90,
        "atr_length": 21,
        "atr_mult_stop": 2.0,
        "atr_mult_target": 4.0,
        "min_volume_sma": 50,
        "rsi_length": 21,
        "rsi_oversold": 20,
        "rsi_overbought": 80,
        "adaptive_regime": False,
        "volume_filter": True,
        "mtf_filter": True,
    }
    put_resp = client.put("/strategy/params", json=mutated)
    assert put_resp.status_code == 200, put_resp.text
    assert put_resp.json()["new_params"] == mutated

    reset_resp = client.post("/strategy/params/reset", json={})
    assert reset_resp.status_code == 200, reset_resp.text
    body = reset_resp.json()

    assert body["status"] == "reset"
    assert body["old_params"] == mutated, "reset must report the pre-reset (mutated) state as old_params"

    expected_defaults = {
        "ema_short": 8,
        "ema_long": 21,
        "ema_smoother": 34,
        "atr_length": 14,
        "atr_mult_stop": 1.5,
        "atr_mult_target": 3.0,
        "min_volume_sma": 20,
        "rsi_length": 14,
        "rsi_oversold": 30,
        "rsi_overbought": 70,
        "adaptive_regime": True,
        "volume_filter": False,
        "mtf_filter": False,
    }
    assert body["new_params"] == expected_defaults, (
        f"reset did not restore all pydantic defaults: {body['new_params']!r}"
    )

    # A subsequent GET must reflect the reset state, not the mutated state.
    get_resp = client.get("/strategy/params")
    assert get_resp.status_code == 200
    assert get_resp.json() == expected_defaults


def test_reset_is_idempotent(client):
    """Resetting twice in a row must both succeed and land on the same defaults."""
    first = client.post("/strategy/params/reset", json={})
    second = client.post("/strategy/params/reset", json={})
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["new_params"] == second.json()["new_params"]
