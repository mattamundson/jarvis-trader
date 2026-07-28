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


# ---------------------------------------------------------------------------
# GT-14 regression: live FeatureFlags singleton (mirrors real engine boot)
# ---------------------------------------------------------------------------
#
# The tests above (and every pre-existing test in this file) never register a
# FeatureFlags singleton, so config_router.config_overview()'s inner
# `get_flags()` call raises RuntimeError and the code takes the "singleton not
# initialised" fallback branch (static FLAG_DEFINITIONS defaults). That branch
# happens to build its dict correctly, so those tests passed even while the
# *live* branch was broken.
#
# At real engine boot (engine/main.py ~line 621) the singleton IS registered,
# so config_overview() takes the other branch: it called
# `flags_registry.list_flags().items()` — but list_flags() returns a
# List[Dict], which has no .items(). That raised AttributeError, was
# swallowed by the router's broad `except Exception: flag_data = {}`, and the
# /config Feature Flags card rendered as an empty list ([]) despite ~9 live
# ENABLE_* flags being initialised at boot. These tests register a real
# FeatureFlags singleton (backed by the same in-memory DB double used in
# tests/test_feature_flags.py) to exercise that exact code path.


class _GT14MockRow(dict):
    """Behaves like sqlite3.Row (subscript access by column name)."""

    def __getitem__(self, key):
        return super().__getitem__(key)


class _GT14MockConfig:
    """Minimal TradingConfig stub with feature flag defaults (mirrors real settings)."""

    ENABLE_KAIROS = False
    ENABLE_SPECULATION = False
    ENABLE_TILT_DETECTION = True
    ENABLE_DREAM_CONSOLIDATION = False
    ENABLE_CONTEXT_COMPACTION = True
    ENABLE_CRYPTO = False
    ENABLE_POLYMARKET = False
    ENABLE_RL_TRADING = False
    ENABLE_SIGNAL_SANITIZATION = False


class _GT14MockDB:
    """Minimal DatabaseManager stub — in-memory feature_flags table."""

    def __init__(self):
        import threading

        self._lock = threading.Lock()
        self._flags_store = {}

    def _connect(self):
        from unittest.mock import MagicMock

        conn = MagicMock()

        def _execute(sql, params=()):
            sql_norm = " ".join(sql.split()).upper()
            if "SELECT ENABLED" in sql_norm and "WHERE NAME" in sql_norm:
                name = params[0]
                if name in self._flags_store:
                    row = _GT14MockRow({"enabled": self._flags_store[name]})
                    conn.execute.return_value.fetchone.return_value = row
                else:
                    conn.execute.return_value.fetchone.return_value = None
            elif "SELECT NAME, ENABLED" in sql_norm:
                rows = [
                    _GT14MockRow({"name": k, "enabled": v})
                    for k, v in self._flags_store.items()
                ]
                conn.execute.return_value.fetchall.return_value = rows
            elif "INSERT INTO FEATURE_FLAGS" in sql_norm:
                self._flags_store[params[0]] = params[1]
            elif "DELETE FROM FEATURE_FLAGS" in sql_norm:
                self._flags_store.pop(params[0], None)
            return conn.execute.return_value

        conn.execute.side_effect = _execute
        conn.commit = MagicMock()
        conn.close = MagicMock()
        return conn


@pytest.fixture()
def live_flags_singleton():
    """Register a real FeatureFlags instance as the module-level singleton.

    Mirrors engine/main.py's boot sequence (set_flags_instance) so the
    router's `get_flags()` call takes the live-registry branch instead of
    the RuntimeError fallback. Restores the prior singleton on teardown so
    this test can't leak state into other test modules.
    """
    from flags import registry as flags_registry_module
    from flags.registry import FeatureFlags, set_flags_instance

    original = flags_registry_module._instance
    instance = FeatureFlags(config=_GT14MockConfig(), db=_GT14MockDB())
    set_flags_instance(instance)
    try:
        yield instance
    finally:
        flags_registry_module._instance = original


def test_overview_feature_flags_nonempty_with_live_singleton(client, live_flags_singleton):
    """GT-14: with a real FeatureFlags singleton registered (real-boot path),
    the feature_flags category must be non-empty and contain the live
    ENABLE_* flags — not silently drop to []."""
    data = client.get("/config/overview").json()
    flag_items = data["categories"].get("feature_flags", [])
    enable_items = [i for i in flag_items if i["key"].startswith("ENABLE_")]

    assert len(enable_items) > 0, (
        "feature_flags category has zero ENABLE_* entries with a live FeatureFlags "
        "singleton registered — GT-14 regression (list_flags().items() bug)"
    )

    from flags.registry import FLAG_DEFINITIONS

    expected_names = {f["name"] for f in FLAG_DEFINITIONS}
    found_names = {i["key"] for i in enable_items}
    assert found_names == expected_names, (
        f"feature_flags category names {found_names} do not match the live "
        f"registry's FLAG_DEFINITIONS {expected_names}"
    )


def test_overview_feature_flags_matches_live_registry_state(client, live_flags_singleton):
    """GT-14: values served by /config/overview must reflect the live
    registry's resolved state, including runtime overrides — proving the
    endpoint reads the real singleton rather than static fallback defaults."""
    # ENABLE_KAIROS defaults to False; flip it via a runtime override and
    # confirm /config/overview reflects the override, not the static default.
    live_flags_singleton.set_flag("ENABLE_KAIROS", True, updated_by="test")

    data = client.get("/config/overview").json()
    flag_items = {i["key"]: i["value"] for i in data["categories"].get("feature_flags", [])}

    assert flag_items.get("ENABLE_KAIROS") is True, (
        f"/config/overview reported ENABLE_KAIROS={flag_items.get('ENABLE_KAIROS')!r} "
        "after a runtime override to True — endpoint is not reading the live registry"
    )
    # Untouched flag should still reflect its live (registered) default.
    assert flag_items.get("ENABLE_TILT_DETECTION") is True


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


# ---------------------------------------------------------------------------
# GT-02: redact-by-default regression tests
# ---------------------------------------------------------------------------
#
# These test the redaction decision (_redact) directly against fixture key
# NAMES that are not part of the real TradingConfig schema, so a brand-new
# secret-shaped env var the engine has never seen before is proven to
# redact by default -- without ever touching a real secret value.


@pytest.mark.parametrize(
    "fixture_key",
    [
        "NEVER_BEFORE_SEEN_API_KEY",
        "SOME_NEW_SERVICE_SECRET",
        "BRAND_NEW_OAUTH_TOKEN",
        "FRESH_DATABASE_URL",
        "RANDOM_UNLISTED_PASSWORD",
    ],
)
def test_unknown_secret_shaped_key_redacted_by_default(fixture_key):
    """A never-before-seen _KEY/_SECRET/_TOKEN/_URL-shaped key must redact by
    default (allowlist-not-denylist design) -- proving the fix doesn't
    require remembering to add new secrets to a denylist."""
    from routers.config_router import SAFE_TO_DISPLAY_KEYS, _redact

    assert fixture_key not in SAFE_TO_DISPLAY_KEYS, (
        f"fixture key {fixture_key!r} unexpectedly pre-listed as safe; "
        "pick a different fixture name for this test"
    )

    displayed, sensitive = _redact(fixture_key, "fixture-placeholder-value-not-a-real-secret")
    assert sensitive is True, f"unknown key {fixture_key!r} must be treated as sensitive by default"
    assert str(displayed).startswith("***"), (
        f"unknown key {fixture_key!r} must be masked, got {displayed!r}"
    )


def test_known_safe_key_not_redacted():
    """A reviewed, explicitly allowlisted key (e.g. ENGINE_INTERNAL_URL) must
    NOT be redacted, even though its name ends in _URL like many secret
    connection strings do -- the allowlist, not the suffix, decides."""
    from routers.config_router import SAFE_TO_DISPLAY_KEYS, _redact

    assert "ENGINE_INTERNAL_URL" in SAFE_TO_DISPLAY_KEYS

    fixture_value = "http://127.0.0.1:8010"  # placeholder, not a secret
    displayed, sensitive = _redact("ENGINE_INTERNAL_URL", fixture_value)
    assert sensitive is False
    assert displayed == fixture_value, (
        f"known-safe key ENGINE_INTERNAL_URL should pass through unmasked, got {displayed!r}"
    )


def test_overview_uncategorized_secret_shaped_field_is_redacted(monkeypatch, client):
    """End-to-end: a fixture secret-shaped key injected into the settings
    dump (simulating a newly-added env var nobody remembered to denylist)
    must come back redacted from the live /config/overview response, not
    echoed in plaintext through the 'other' (uncategorized) section."""
    import routers.config_router as config_router_module

    fixture_key = "NEVER_BEFORE_SEEN_DB_URL"
    fixture_value = "placeholder://not-a-real-secret-value"

    real_settings = config_router_module.settings

    class _FixtureSettingsWrapper:
        def model_dump(self):
            base = real_settings.model_dump() if hasattr(real_settings, "model_dump") else real_settings.dict()
            base = dict(base)
            base[fixture_key] = fixture_value
            return base

    monkeypatch.setattr(config_router_module, "settings", _FixtureSettingsWrapper())

    resp = client.get("/config/overview")
    assert resp.status_code == 200
    data = resp.json()

    other_items = data["categories"].get("other", [])
    match = [item for item in other_items if item["key"] == fixture_key]
    assert match, f"fixture key {fixture_key!r} not found in 'other' category: {other_items}"

    item = match[0]
    assert item["sensitive"] is True, f"fixture key {fixture_key!r} must be flagged sensitive"
    assert str(item["value"]).startswith(
        "***"
    ), f"fixture key {fixture_key!r} leaked in plaintext: {item['value']!r}"
