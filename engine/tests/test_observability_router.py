"""
Tests for engine/routers/observability_router.py

Covered:
  - GET /obs/advisor/status
      * missing X-API-Key -> 401
      * wrong X-API-Key -> 401
      * valid key + llm constructed -> available True
      * valid key + llm None -> available False
      * valid key + AdvisorClient() raises -> 200 with available: False, error
  - GET /obs/ic-ensemble/describe
      * missing X-API-Key -> 401
      * valid key + describe() present -> its return value passed through
      * valid key + describe() absent -> agents/warning fallback shape
      * valid key + ICWeightedEnsemble() raises -> 200 with available: False, error
  - GET /obs/token-proxy/metrics
      * missing X-API-Key -> 401
      * valid key + dataclass metrics -> asdict() shape
      * valid key + as_dict()-only metrics -> as_dict() passthrough
      * valid key + plain-attribute metrics (no dataclass, no as_dict) -> dir()-based fallback
      * valid key + get_token_proxy() raises -> 200 with available: False, error

Design:
  - Minimal FastAPI app wrapping only observability_router.
  - _require_key reads JARVIS_API_KEY or API_KEY from os.environ at call time.
    conftest.py forces API_KEY to a real value (or "test-key" fallback), so
    auth is genuinely enforced here — mirroring production where the router
    is mounted behind this same dependency, not global middleware.
  - The router does lazy `from agents.advisor_client import AdvisorClient` /
    `from analytics.ic_ensemble import ICWeightedEnsemble` /
    `from utils.token_proxy import get_token_proxy` imports *inside* each
    endpoint function, so patching the source modules is effective per-call.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

import routers.observability_router as observability_router  # noqa: E402
from config import settings  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app_with_router():
    """FastAPI app mounting only the observability router."""
    app = FastAPI()
    app.include_router(observability_router.router)
    return app


@pytest.fixture
def client(app_with_router):
    return TestClient(app_with_router)


_VALID_HEADERS = {"X-API-Key": settings.API_KEY}
_BAD_HEADERS = {"X-API-Key": "definitely-wrong-key"}


# ---------------------------------------------------------------------------
# GET /obs/advisor/status
# ---------------------------------------------------------------------------


def test_advisor_status_missing_key_returns_401(client):
    resp = client.get("/obs/advisor/status")
    assert resp.status_code == 401


def test_advisor_status_wrong_key_returns_401(client):
    resp = client.get("/obs/advisor/status", headers=_BAD_HEADERS)
    assert resp.status_code == 401


def test_advisor_status_llm_constructed(client):
    fake_client = MagicMock()
    fake_client.llm = MagicMock()  # non-None -> available

    with patch("agents.advisor_client.AdvisorClient", return_value=fake_client):
        resp = client.get("/obs/advisor/status", headers=_VALID_HEADERS)

    assert resp.status_code == 200
    data = resp.json()
    assert data["available"] is True
    assert data["llm_constructed"] is True
    assert data["model"] == "claude-opus-4-7"
    assert data["tiebreak_tolerance"] == 0.05
    assert data["low_confidence_threshold"] == 0.5


def test_advisor_status_llm_not_constructed(client):
    fake_client = MagicMock()
    fake_client.llm = None

    with patch("agents.advisor_client.AdvisorClient", return_value=fake_client):
        resp = client.get("/obs/advisor/status", headers=_VALID_HEADERS)

    assert resp.status_code == 200
    data = resp.json()
    assert data["available"] is False
    assert data["llm_constructed"] is False


def test_advisor_status_construction_error_returns_200_with_error_payload(client):
    """AdvisorClient() raising must not 500 — the router catches and reports it."""
    with patch("agents.advisor_client.AdvisorClient", side_effect=RuntimeError("no API key configured")):
        resp = client.get("/obs/advisor/status", headers=_VALID_HEADERS)

    assert resp.status_code == 200
    data = resp.json()
    assert data["available"] is False
    assert "no API key configured" in data["error"]


# ---------------------------------------------------------------------------
# GET /obs/ic-ensemble/describe
# ---------------------------------------------------------------------------


def test_ic_ensemble_describe_missing_key_returns_401(client):
    resp = client.get("/obs/ic-ensemble/describe")
    assert resp.status_code == 401


def test_ic_ensemble_describe_success_passthrough(client):
    fake_ensemble = MagicMock()
    fake_ensemble.describe.return_value = {
        "weights": {"technical": 0.6, "fundamental": 0.4},
        "n_eff": 12,
    }

    with patch("analytics.ic_ensemble.ICWeightedEnsemble", return_value=fake_ensemble):
        resp = client.get("/obs/ic-ensemble/describe", headers=_VALID_HEADERS)

    assert resp.status_code == 200
    data = resp.json()
    assert data == {"weights": {"technical": 0.6, "fundamental": 0.4}, "n_eff": 12}


def test_ic_ensemble_describe_missing_method_falls_back(client):
    """No describe() method -> {agents, warning} fallback shape."""
    fake_ensemble = MagicMock(spec=["agents"])
    fake_ensemble.agents = ["technical", "fundamental", "news"]

    with patch("analytics.ic_ensemble.ICWeightedEnsemble", return_value=fake_ensemble):
        resp = client.get("/obs/ic-ensemble/describe", headers=_VALID_HEADERS)

    assert resp.status_code == 200
    data = resp.json()
    assert data["agents"] == ["technical", "fundamental", "news"]
    assert "not implemented" in data["warning"].lower()


def test_ic_ensemble_describe_construction_error_returns_200_with_error_payload(client):
    with patch("analytics.ic_ensemble.ICWeightedEnsemble", side_effect=RuntimeError("db locked")):
        resp = client.get("/obs/ic-ensemble/describe", headers=_VALID_HEADERS)

    assert resp.status_code == 200
    data = resp.json()
    assert data["available"] is False
    assert "db locked" in data["error"]


# ---------------------------------------------------------------------------
# GET /obs/token-proxy/metrics
# ---------------------------------------------------------------------------


@dataclass
class _FakeMetrics:
    compressions: int = 3
    cache_hits: int = 7
    cache_misses: int = 2


def test_token_proxy_metrics_missing_key_returns_401(client):
    resp = client.get("/obs/token-proxy/metrics")
    assert resp.status_code == 401


def test_token_proxy_metrics_dataclass_uses_asdict(client):
    fake_proxy = MagicMock()
    fake_proxy.metrics = _FakeMetrics()

    with patch("utils.token_proxy.get_token_proxy", return_value=fake_proxy):
        resp = client.get("/obs/token-proxy/metrics", headers=_VALID_HEADERS)

    assert resp.status_code == 200
    data = resp.json()
    assert data == {"compressions": 3, "cache_hits": 7, "cache_misses": 2}


def test_token_proxy_metrics_as_dict_method_used_when_not_dataclass(client):
    class _MetricsWithAsDict:
        def as_dict(self):
            return {"custom": "shape", "count": 42}

    fake_proxy = MagicMock()
    fake_proxy.metrics = _MetricsWithAsDict()

    with patch("utils.token_proxy.get_token_proxy", return_value=fake_proxy):
        resp = client.get("/obs/token-proxy/metrics", headers=_VALID_HEADERS)

    assert resp.status_code == 200
    data = resp.json()
    assert data == {"custom": "shape", "count": 42}


def test_token_proxy_metrics_plain_object_falls_back_to_dir_scan(client):
    class _PlainMetrics:
        def __init__(self):
            self.compressions = 5
            self.cache_hits = 9

        def _private_helper(self):
            return "should not appear"

    fake_proxy = MagicMock()
    fake_proxy.metrics = _PlainMetrics()

    with patch("utils.token_proxy.get_token_proxy", return_value=fake_proxy):
        resp = client.get("/obs/token-proxy/metrics", headers=_VALID_HEADERS)

    assert resp.status_code == 200
    data = resp.json()
    assert data["compressions"] == 5
    assert data["cache_hits"] == 9
    assert "_private_helper" not in data


def test_token_proxy_metrics_lookup_error_returns_200_with_error_payload(client):
    with patch("utils.token_proxy.get_token_proxy", side_effect=RuntimeError("proxy not initialized")):
        resp = client.get("/obs/token-proxy/metrics", headers=_VALID_HEADERS)

    assert resp.status_code == 200
    data = resp.json()
    assert data["available"] is False
    assert "proxy not initialized" in data["error"]
