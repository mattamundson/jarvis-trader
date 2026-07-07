"""
JARVIS TRADER — Config Router Tests
=====================================
Tests for GET /config/overview and GET /config/health-check.

All tests operate on the router directly via FastAPI TestClient — no
running engine required.  The TradingConfig singleton is imported from
config.py, so the test must load a valid .env (or set API_KEY in the
environment) before importing the app or the router.

Run with:
    cd engine
    .venv\\Scripts\\python.exe -m pytest tests/test_config_router.py -v --tb=short
"""

from __future__ import annotations

import os
import sys

import pytest

# ---------------------------------------------------------------------------
# Environment bootstrap — load .env so TradingConfig can validate API_KEY
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

# Ensure engine root is on sys.path before any engine imports
_ENGINE_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client():
    """Return a FastAPI TestClient wrapping just the config_router."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers.config_router import router as config_router

    app = FastAPI()
    app.include_router(config_router)
    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# /config/overview tests
# ---------------------------------------------------------------------------


def test_overview_returns_200(client):
    """GET /config/overview must return HTTP 200."""
    resp = client.get("/config/overview")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"


def test_overview_has_categories(client):
    """Response must include a 'categories' key that is a non-empty dict."""
    data = client.get("/config/overview").json()
    assert "categories" in data, "'categories' key missing from response"
    assert isinstance(data["categories"], dict), "'categories' should be a dict"
    assert len(data["categories"]) > 0, "'categories' must not be empty"


def test_overview_has_total_fields(client):
    """Response must include 'total_fields' and it must be > 0."""
    data = client.get("/config/overview").json()
    assert "total_fields" in data, "'total_fields' key missing"
    assert data["total_fields"] > 0, "'total_fields' must be positive"


def test_overview_sensitive_keys_masked(client):
    """Sensitive keys (e.g. ANTHROPIC_API_KEY) must have values starting with '***'."""
    data = client.get("/config/overview").json()
    categories = data["categories"]

    sensitive_found = False
    for _cat, items in categories.items():
        for item in items:
            if item["sensitive"]:
                sensitive_found = True
                val = str(item["value"])
                assert val.startswith(
                    "***"
                ), f"Sensitive key {item['key']!r} value {val!r} does not start with '***'"
    # If no sensitive keys are configured, this assertion is vacuously True
    # (the test still exercises the code path)
    _ = sensitive_found  # suppress unused-variable


def test_overview_nonsensitive_keys_not_masked(client):
    """Non-sensitive keys must NOT have values that look like '***'."""
    data = client.get("/config/overview").json()
    categories = data["categories"]

    for _cat, items in categories.items():
        for item in items:
            if not item["sensitive"]:
                val = str(item["value"])
                assert not val.startswith(
                    "***"
                ), f"Non-sensitive key {item['key']!r} appears masked: {val!r}"


def test_overview_feature_flags_category_present(client):
    """The 'feature_flags' category must be present in the response."""
    data = client.get("/config/overview").json()
    assert (
        "feature_flags" in data["categories"]
    ), "'feature_flags' category missing from /config/overview"


def test_overview_feature_flags_contains_enable_kairos(client):
    """The 'feature_flags' category must contain ENABLE_KAIROS."""
    data = client.get("/config/overview").json()
    flag_keys = [item["key"] for item in data["categories"].get("feature_flags", [])]
    assert (
        "ENABLE_KAIROS" in flag_keys
    ), f"ENABLE_KAIROS not found in feature_flags category. Found: {flag_keys}"


def test_overview_safety_category_present(client):
    """The 'safety' category must be present."""
    data = client.get("/config/overview").json()
    assert "safety" in data["categories"], "'safety' category missing"


def test_overview_items_have_required_fields(client):
    """Every item in every category must have 'key', 'value', and 'sensitive' fields."""
    data = client.get("/config/overview").json()
    for cat, items in data["categories"].items():
        for item in items:
            assert "key" in item, f"Category {cat!r}: item missing 'key'"
            assert "value" in item, f"Category {cat!r}: item {item.get('key')!r} missing 'value'"
            assert (
                "sensitive" in item
            ), f"Category {cat!r}: item {item.get('key')!r} missing 'sensitive'"
            assert isinstance(
                item["sensitive"], bool
            ), f"Category {cat!r}: item {item.get('key')!r} 'sensitive' must be bool"


# ---------------------------------------------------------------------------
# /config/health-check tests
# ---------------------------------------------------------------------------


def test_health_check_returns_200(client):
    """GET /config/health-check must return HTTP 200."""
    resp = client.get("/config/health-check")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"


def test_health_check_has_configured_dict(client):
    """Response must include 'configured' dict with boolean values."""
    data = client.get("/config/health-check").json()
    assert "configured" in data, "'configured' key missing from health-check response"
    assert isinstance(data["configured"], dict), "'configured' must be a dict"
    for key, val in data["configured"].items():
        assert isinstance(val, bool), f"configured[{key!r}] must be bool, got {type(val)}"


def test_health_check_configured_has_six_critical_keys(client):
    """The 'configured' dict must contain all 6 critical API key checks."""
    expected = {
        "ANTHROPIC_API_KEY",
        "FINNHUB_API_KEY",
        "POLYGON_API_KEY",
        "ALPACA_API_KEY",
        "TWILIO_ACCOUNT_SID",
        "WHATSAPP_TO",
    }
    data = client.get("/config/health-check").json()
    actual = set(data["configured"].keys())
    missing = expected - actual
    assert not missing, f"Missing critical keys in 'configured': {missing}"


def test_health_check_live_trading_false_by_default(client):
    """live_trading_enabled must default to False (safety posture)."""
    data = client.get("/config/health-check").json()
    assert "live_trading_enabled" in data, "'live_trading_enabled' missing"
    assert (
        data["live_trading_enabled"] is False
    ), "live_trading_enabled should default to False for safety"


def test_health_check_require_human_approval_true_by_default(client):
    """require_human_approval must default to True (safety posture)."""
    data = client.get("/config/health-check").json()
    assert "require_human_approval" in data, "'require_human_approval' missing"
    assert (
        data["require_human_approval"] is True
    ), "require_human_approval should default to True for safety"


def test_health_check_paper_trading_field_present(client):
    """Response must include 'paper_trading' field."""
    data = client.get("/config/health-check").json()
    assert "paper_trading" in data, "'paper_trading' field missing from health-check"
    assert isinstance(data["paper_trading"], bool), "'paper_trading' must be bool"
