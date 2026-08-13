"""
Tests for engine/routers/super_engine_router.py

Covered:
  - GET /super-engine/status
      * all components inactive (default registry) -> active: False for every key
      * mixed registry (some active, some None) -> per-component detail fields
      * model_drawer.current_model presence -> model_loaded flag
      * arb_scout.paired_assets -> pairs_count
      * regime_guard.last_regime / last_check (both set, and last_check=None)
  - GET /super-engine/polymarket/balance
      * connector not active -> 503
      * connector active -> 200 with stub balance payload

Design:
  - Minimal FastAPI app wrapping only super_engine_router (no auth middleware —
    this router has none of its own, matching production wiring in main.py).
  - registry is a module-level global mutated via inject_super_engine(); a
    fixture snapshots/restores it around every test so tests can't leak state
    into each other or into other test modules that import the same router.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

import routers.super_engine_router as super_engine_router  # noqa: E402
from routers.super_engine_router import inject_super_engine  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app_with_router():
    """FastAPI app mounting only the super-engine router (no auth middleware)."""
    app = FastAPI()
    app.include_router(super_engine_router.router)
    return app


@pytest.fixture
def client(app_with_router):
    return TestClient(app_with_router)


@pytest.fixture(autouse=True)
def clean_registry():
    """Snapshot the module-level registry before each test; restore after."""
    original = dict(super_engine_router.registry)
    yield
    super_engine_router.registry.clear()
    super_engine_router.registry.update(original)
    # inject_super_engine() only *updates* — make sure no test can leave a
    # stray key added to the registry.
    for key in list(super_engine_router.registry.keys()):
        if key not in original:
            del super_engine_router.registry[key]


# ---------------------------------------------------------------------------
# GET /super-engine/status
# ---------------------------------------------------------------------------


def test_status_all_inactive_by_default(client):
    """With no components injected, every registry key reports active: False."""
    resp = client.get("/super-engine/status")
    assert resp.status_code == 200
    data = resp.json()
    assert set(data.keys()) == {
        "polymarket",
        "openbb",
        "sentiment_bridge",
        "model_drawer",
        "arb_scout",
        "regime_guard",
    }
    for key, entry in data.items():
        assert entry == {"active": False}, f"{key} should be inactive by default"


def test_status_mixed_registry_reports_active_components(client):
    """Some components active, some None — status reflects each independently."""
    poly = MagicMock()
    inject_super_engine({"polymarket": poly, "openbb": None})

    resp = client.get("/super-engine/status")
    assert resp.status_code == 200
    data = resp.json()

    assert data["polymarket"]["active"] is True
    assert data["polymarket"]["type"] == type(poly).__name__
    assert "last_check" in data["polymarket"]

    assert data["openbb"] == {"active": False}


def test_status_model_drawer_reports_model_loaded_flag(client):
    """model_drawer.current_model presence surfaces as model_loaded."""
    drawer = SimpleNamespace(current_model="ppo_v3")
    inject_super_engine({"model_drawer": drawer})

    resp = client.get("/super-engine/status")
    data = resp.json()
    assert data["model_drawer"]["active"] is True
    assert data["model_drawer"]["model_loaded"] is True


def test_status_model_drawer_no_model_loaded(client):
    """model_drawer.current_model=None -> model_loaded False."""
    drawer = SimpleNamespace(current_model=None)
    inject_super_engine({"model_drawer": drawer})

    resp = client.get("/super-engine/status")
    data = resp.json()
    assert data["model_drawer"]["model_loaded"] is False


def test_status_arb_scout_reports_pairs_count(client):
    """arb_scout.paired_assets length surfaces as pairs_count."""
    scout = SimpleNamespace(paired_assets=["ES-NQ", "GC-SI", "CL-RB"])
    inject_super_engine({"arb_scout": scout})

    resp = client.get("/super-engine/status")
    data = resp.json()
    assert data["arb_scout"]["pairs_count"] == 3


def test_status_regime_guard_reports_regime_and_last_check(client):
    """regime_guard.last_regime + last_check (datetime) surface distinctly."""
    from datetime import datetime

    check_time = datetime(2026, 7, 1, 12, 0, 0)
    guard = SimpleNamespace(last_regime="RISK_ON", last_check=check_time)
    inject_super_engine({"regime_guard": guard})

    resp = client.get("/super-engine/status")
    data = resp.json()
    assert data["regime_guard"]["current_regime"] == "RISK_ON"
    assert data["regime_guard"]["last_check"] == check_time.isoformat()


def test_status_regime_guard_last_check_none(client):
    """regime_guard.last_check=None -> last_check surfaces as null, not an error."""
    guard = SimpleNamespace(last_regime="NEUTRAL", last_check=None)
    inject_super_engine({"regime_guard": guard})

    resp = client.get("/super-engine/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["regime_guard"]["current_regime"] == "NEUTRAL"
    assert data["regime_guard"]["last_check"] is None


# ---------------------------------------------------------------------------
# GET /super-engine/polymarket/balance
# ---------------------------------------------------------------------------


def test_polymarket_balance_not_active_returns_503(client):
    """No polymarket connector injected -> 503, not a crash."""
    inject_super_engine({"polymarket": None})

    resp = client.get("/super-engine/polymarket/balance")
    assert resp.status_code == 503
    assert "not active" in resp.json()["detail"].lower()


def test_polymarket_balance_active_returns_stub_payload(client):
    """Connector present -> 200 with the documented stub balance shape."""
    inject_super_engine({"polymarket": MagicMock()})

    resp = client.get("/super-engine/polymarket/balance")
    assert resp.status_code == 200
    data = resp.json()
    assert data == {"balance": 1000.0, "currency": "USDC", "chain": "Polygon"}
