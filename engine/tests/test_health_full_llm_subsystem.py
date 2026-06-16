"""US-004 tests — LLM provider + fallback state in GET /health/full.

/health/full -> subsystems.llm exposes the current `provider` and a
`fallback_active` boolean (plus context), derived from the existing
llm.client snapshot helpers. No new LLM logic. Defensive: a helper failure
yields subsystems.llm.status == "unknown", never a 5xx.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import health_router


@pytest.fixture
def health_client():
    app = FastAPI()
    app.include_router(health_router.router)
    health_router.inject_dependencies(
        start_time=datetime.now(timezone.utc),
        dm=None, sl=None, dbm=None, pt=None, pm=None, tp=None, schwab=None,
    )
    return TestClient(app)


def _summary(active, primary, configured=None, single_leg=False):
    configured = configured or ["anthropic", "gemini"]
    return {
        "active_provider": active,
        "primary_provider": primary,
        "providers_configured": configured,
        "providers_available": len(configured),
        "primary_healthy": active is None or active == primary,
        "single_leg_warning": single_leg,
    }


def _llm(client):
    return client.get("/health/full").json()["subsystems"]["llm"]


def test_llm_ok_when_primary_serving(health_client):
    state = {"healthy": True, "google_fallback_count": 0, "vertex_failover_count": 0}
    with patch("llm.client.get_llm_path_state", return_value=state), \
         patch("llm.client.get_llm_provider_summary",
               return_value=_summary("anthropic", "anthropic")):
        llm = _llm(health_client)
    assert llm["status"] == "ok"
    assert llm["provider"] == "anthropic"
    assert llm["fallback_active"] is False
    assert llm["healthy"] is True


def test_llm_degraded_and_fallback_active_when_on_secondary(health_client):
    state = {"healthy": True, "google_fallback_count": 12, "vertex_failover_count": 2}
    with patch("llm.client.get_llm_path_state", return_value=state), \
         patch("llm.client.get_llm_provider_summary",
               return_value=_summary("gemini", "anthropic")):
        llm = _llm(health_client)
    assert llm["fallback_active"] is True
    assert llm["provider"] == "gemini"  # the leg actually serving
    assert llm["status"] == "degraded"
    assert llm["primary_provider"] == "anthropic"
    assert llm["google_fallback_count"] == 12
    assert llm["vertex_failover_count"] == 2


def test_llm_degraded_when_unhealthy_even_on_primary(health_client):
    state = {"healthy": False}
    with patch("llm.client.get_llm_path_state", return_value=state), \
         patch("llm.client.get_llm_provider_summary",
               return_value=_summary("anthropic", "anthropic")):
        llm = _llm(health_client)
    assert llm["healthy"] is False
    assert llm["fallback_active"] is False
    assert llm["status"] == "degraded"


def test_llm_provider_falls_back_to_primary_when_active_none(health_client):
    # active_provider None (nothing served yet) → report the primary, not None.
    state = {"healthy": True}
    with patch("llm.client.get_llm_path_state", return_value=state), \
         patch("llm.client.get_llm_provider_summary",
               return_value=_summary(None, "anthropic")):
        llm = _llm(health_client)
    assert llm["provider"] == "anthropic"
    assert llm["fallback_active"] is False
    assert llm["status"] == "ok"


def test_subsystem_status_preserves_extra_fields():
    """Regression: SubsystemStatus must NOT drop extra observability fields.

    With extra="ignore" the response model silently stripped ib_gateway's
    data_source / per_symbol_freshness / watchdog and llm's provider /
    fallback_active, so the dashboard never received them. extra="allow" keeps
    them. This locks that behavior at the model level (no wiring dependency).
    """
    from api.models import SubsystemStatus

    s = SubsystemStatus(
        status="ok",
        data_source="ibkr",
        per_symbol_freshness={"MES": 4.2},
        provider="gemini",
        fallback_active=True,
    )
    dumped = s.model_dump()
    assert dumped["data_source"] == "ibkr"
    assert dumped["per_symbol_freshness"] == {"MES": 4.2}
    assert dumped["provider"] == "gemini"
    assert dumped["fallback_active"] is True


def test_llm_unknown_when_helper_raises(health_client):
    state = {"healthy": True}
    with patch("llm.client.get_llm_path_state", return_value=state), \
         patch("llm.client.get_llm_provider_summary", side_effect=RuntimeError("boom")):
        resp = health_client.get("/health/full")
    assert resp.status_code == 200  # never 5xx on an LLM read failure
    llm = resp.json()["subsystems"]["llm"]
    assert llm["status"] == "unknown"
    assert "error" in llm
