from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _healthy_snapshot(**overrides):
    health = {
        "status": "ok",
        "timestamp": "2026-08-28T00:00:00+00:00",
        "live_trading": False,
        "paper_mode": True,
        "kill_switch_active": False,
        "database": "connected",
        "ibgateway_alive": True,
        "ibgateway_port": 4002,
        "ibkr_execution_connected": True,
        "execution_connected_verified": True,
        "ib_execution_stale": False,
        "ibkr_data_connected": False,
        "ibkr_broker_probe_ok": True,
        "ibkr_degraded_reason": None,
        "schwab_connected": False,
        "llm_path_healthy": True,
        "tradingview_mcp_healthy": True,
        "tv_mcp_status": "healthy",
        "market_data_fresh": True,
        "market_data_stale_symbols": [],
        "pending_approvals": {"count": 0, "oldest_age_min": None},
    }
    health.update(overrides)
    return health


def _instrument_state(**overrides):
    instruments = {
        "active_symbols": ["MES"],
        "halted_symbols": ["M2K", "MCL", "MGC", "MNQ"],
        "enabled_config_symbols": ["MES"],
        "default_briefing_symbols": ["MES"],
    }
    instruments.update(overrides)
    return instruments


def test_build_paper_pipeline_readiness_ready():
    from routers.readiness_router import build_paper_pipeline_readiness

    data = build_paper_pipeline_readiness(_healthy_snapshot(), _instrument_state())

    assert data["status"] == "ready"
    assert data["summary"]["ready"] is True
    assert data["summary"]["active_symbols"] == ["MES"]
    assert data["summary"]["halted_symbols"] == ["M2K", "MCL", "MGC", "MNQ"]
    assert data["summary"]["market_data_source"] == "tradingview_mcp"
    assert data["summary"]["failed_required"] == []


def test_build_paper_pipeline_readiness_blocks_live_trading():
    from routers.readiness_router import build_paper_pipeline_readiness

    data = build_paper_pipeline_readiness(
        _healthy_snapshot(live_trading=True, paper_mode=False),
        _instrument_state(),
    )

    assert data["status"] == "blocked"
    assert "paper_mode_only" in data["summary"]["failed_required"]


def test_build_paper_pipeline_readiness_blocks_halted_active_symbol():
    from routers.readiness_router import build_paper_pipeline_readiness

    data = build_paper_pipeline_readiness(
        _healthy_snapshot(),
        _instrument_state(active_symbols=["MES", "MGC"], enabled_config_symbols=["MES", "MGC"]),
    )

    assert data["status"] == "blocked"
    assert "active_symbols_unhalted" in data["summary"]["failed_required"]


def test_build_paper_pipeline_readiness_degrades_for_pending_approvals():
    from routers.readiness_router import build_paper_pipeline_readiness

    data = build_paper_pipeline_readiness(
        _healthy_snapshot(pending_approvals={"count": 2, "oldest_age_min": 7.5}),
        _instrument_state(),
    )

    assert data["status"] == "degraded"
    assert data["summary"]["failed_required"] == []
    assert data["summary"]["warnings"] == ["approval_queue_clear"]


def test_paper_pipeline_route_uses_cached_health(monkeypatch):
    from middleware.auth import verify_api_key
    from routers import health_router
    from routers.readiness_router import router

    async def _fake_health():
        return _healthy_snapshot(
            ibgateway_alive=False,
            execution_connected_verified=False,
            ib_execution_stale=True,
        )

    monkeypatch.setattr(health_router, "_health_cached", _fake_health)

    app = FastAPI()
    app.dependency_overrides[verify_api_key] = lambda: "test-key"
    app.include_router(router)

    with TestClient(app) as client:
        resp = client.get("/readiness/paper-pipeline")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "blocked"
    assert "execution_path_verified" in data["summary"]["failed_required"]
    assert data["broker"]["ib_execution_stale"] is True
