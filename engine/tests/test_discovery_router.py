"""
Tests for engine/routers/discovery_router.py

Covered:
  - GET  /discovery/strategies              — success + empty registry
  - GET  /discovery/strategies/kept         — success + empty
  - GET  /discovery/strategies/{name}       — success + 404 not found
  - POST /discovery/strategies/reload       — success
  - POST /discovery/strategies/load         — success + 404 missing file + 400 load error
  - POST /discovery/run-cycle               — success + 503 (generation returned None)
                                               + 500 (generate_strategy raises)
                                               + 500 (evaluate_strategy_file raises)
  - GET  /discovery/evaluation/gates        — success, matches real evaluation_harness constants

Design:
  - Uses a minimal FastAPI app wrapping only discovery_router (no full main.py import).
  - The module-level `_registry` singleton is reset before/after every test so tests
    don't leak state into each other.
  - `strategies.registry.StrategyRegistry` and `strategies.discovery_loop.*` are mocked
    (external dependencies: dynamic strategy loading via importlib, LLM-driven generation,
    and backtest evaluation) — router logic itself (branching, status codes, response
    shaping) is exercised for real.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Path bootstrap — add engine root so routers/strategies/backtest are importable
# ---------------------------------------------------------------------------

_ENGINE_ROOT = str(Path(__file__).parent.parent)
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)

import routers.discovery_router as discovery_router_module  # noqa: E402
from routers.discovery_router import router as discovery_router  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    """FastAPI TestClient wrapping just the discovery_router."""
    app = FastAPI()
    app.include_router(discovery_router)
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture(autouse=True)
def reset_registry_singleton():
    """The router keeps a module-level lazy singleton — reset it around every test."""
    discovery_router_module._registry = None
    yield
    discovery_router_module._registry = None


def _mock_registry(*, count=0, list_all=None, list_kept=None, get_result=None, scan_all=None):
    reg = MagicMock()
    reg.count = count
    reg.list_all.return_value = list_all if list_all is not None else []
    reg.list_kept.return_value = list_kept if list_kept is not None else []
    reg.get.return_value = get_result
    reg.scan_all.return_value = scan_all if scan_all is not None else []
    return reg


# ---------------------------------------------------------------------------
# GET /discovery/strategies
# ---------------------------------------------------------------------------


def test_list_strategies_success(client):
    mock_reg = _mock_registry(count=2, list_all=[{"name": "a"}, {"name": "b"}])
    with patch("strategies.registry.StrategyRegistry", return_value=mock_reg):
        resp = client.get("/discovery/strategies")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total"] == 2
    assert data["strategies"] == [{"name": "a"}, {"name": "b"}]


def test_list_strategies_empty_registry(client):
    mock_reg = _mock_registry(count=0, list_all=[])
    with patch("strategies.registry.StrategyRegistry", return_value=mock_reg):
        resp = client.get("/discovery/strategies")
    assert resp.status_code == 200
    assert resp.json() == {"total": 0, "strategies": []}


# ---------------------------------------------------------------------------
# GET /discovery/strategies/kept
# ---------------------------------------------------------------------------


def test_list_kept_strategies_success(client):
    mock_reg = _mock_registry(list_kept=[{"name": "keeper", "keep": True}])
    with patch("strategies.registry.StrategyRegistry", return_value=mock_reg):
        resp = client.get("/discovery/strategies/kept")
    assert resp.status_code == 200
    assert resp.json() == {"kept": [{"name": "keeper", "keep": True}]}


def test_list_kept_strategies_none_kept(client):
    mock_reg = _mock_registry(list_kept=[])
    with patch("strategies.registry.StrategyRegistry", return_value=mock_reg):
        resp = client.get("/discovery/strategies/kept")
    assert resp.status_code == 200
    assert resp.json() == {"kept": []}


# ---------------------------------------------------------------------------
# GET /discovery/strategies/{name}
# ---------------------------------------------------------------------------


def test_get_strategy_success(client):
    strategy = MagicMock()
    strategy.metadata.return_value = {"name": "sma_trend", "keep": True}
    mock_reg = _mock_registry(get_result=strategy)
    with patch("strategies.registry.StrategyRegistry", return_value=mock_reg):
        resp = client.get("/discovery/strategies/sma_trend")
    assert resp.status_code == 200
    assert resp.json() == {"name": "sma_trend", "keep": True}


def test_get_strategy_not_found(client):
    mock_reg = _mock_registry(get_result=None)
    with patch("strategies.registry.StrategyRegistry", return_value=mock_reg):
        resp = client.get("/discovery/strategies/does_not_exist")
    assert resp.status_code == 404
    assert "does_not_exist" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# POST /discovery/strategies/reload
# ---------------------------------------------------------------------------


def test_reload_strategies_success(client):
    mock_reg = _mock_registry(count=3, scan_all=["a", "b", "c"])
    with patch("strategies.registry.StrategyRegistry", return_value=mock_reg):
        resp = client.post("/discovery/strategies/reload")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["reloaded"] is True
    assert data["total"] == 3
    assert data["loaded"] == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# POST /discovery/strategies/load
# ---------------------------------------------------------------------------


def test_load_strategy_file_not_found(client):
    """Real filesystem check — no strategy file with this name exists on disk."""
    mock_reg = _mock_registry()
    with patch("strategies.registry.StrategyRegistry", return_value=mock_reg):
        resp = client.post(
            "/discovery/strategies/load", params={"filename": "definitely_missing_xyz.py"}
        )
    assert resp.status_code == 404
    assert "definitely_missing_xyz.py" in resp.json()["detail"]


def test_load_strategy_file_success(client):
    strategy = MagicMock()
    strategy.metadata.return_value = {"name": "loaded_strat"}
    mock_reg = _mock_registry(get_result=None)
    mock_reg.load_from_file.return_value = strategy

    with patch("strategies.registry.StrategyRegistry", return_value=mock_reg), patch.object(
        Path, "exists", return_value=True
    ):
        resp = client.post("/discovery/strategies/load", params={"filename": "some_strat.py"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["loaded"] is True
    assert data["strategy"] == {"name": "loaded_strat"}


def test_load_strategy_file_load_error_returns_400(client):
    mock_reg = _mock_registry()
    mock_reg.load_from_file.side_effect = ValueError("Multiple BaseStrategy subclasses")

    with patch("strategies.registry.StrategyRegistry", return_value=mock_reg), patch.object(
        Path, "exists", return_value=True
    ):
        resp = client.post("/discovery/strategies/load", params={"filename": "bad_strat.py"})
    assert resp.status_code == 400
    assert "Multiple BaseStrategy subclasses" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# POST /discovery/run-cycle
# ---------------------------------------------------------------------------


def test_run_discovery_cycle_success(client):
    async_generate = AsyncMock(return_value="strategies/generated/sma_20260709.py")
    eval_result = {
        "verdict": "ELIGIBLE",
        "sharpe": 1.4,
        "calmar": 1.2,
        "pf": 1.6,
        "num_trades": 45,
        "win_rate": 0.55,
        "max_drawdown_pct": 8.0,
        "thoughts": "looks solid",
    }
    with patch("strategies.discovery_loop.generate_strategy", async_generate), patch(
        "strategies.discovery_loop.evaluate_strategy_file", return_value=eval_result
    ):
        resp = client.post("/discovery/run-cycle", params={"symbol": "MES", "interval": "1h"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "ok"
    assert data["eligible"] is True
    assert data["verdict"] == "ELIGIBLE"
    assert data["metrics"]["sharpe"] == 1.4
    assert data["thoughts"] == "looks solid"
    async_generate.assert_awaited_once_with(symbol="MES", interval="1h")


def test_run_discovery_cycle_generation_returns_none_503(client):
    async_generate = AsyncMock(return_value=None)
    with patch("strategies.discovery_loop.generate_strategy", async_generate):
        resp = client.post("/discovery/run-cycle")
    assert resp.status_code == 503
    assert "Strategy generation returned None" in resp.json()["detail"]


def test_run_discovery_cycle_generate_raises_500(client):
    async_generate = AsyncMock(side_effect=RuntimeError("LLM timeout"))
    with patch("strategies.discovery_loop.generate_strategy", async_generate):
        resp = client.post("/discovery/run-cycle")
    assert resp.status_code == 500
    assert "LLM timeout" in resp.json()["detail"]


def test_run_discovery_cycle_evaluate_raises_500(client):
    async_generate = AsyncMock(return_value="strategies/generated/broken.py")
    with patch("strategies.discovery_loop.generate_strategy", async_generate), patch(
        "strategies.discovery_loop.evaluate_strategy_file",
        side_effect=RuntimeError("backtest crashed"),
    ):
        resp = client.post("/discovery/run-cycle")
    assert resp.status_code == 500
    assert "backtest crashed" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# GET /discovery/evaluation/gates
# ---------------------------------------------------------------------------


def test_get_evaluation_gates_matches_real_constants(client):
    from backtest.evaluation_harness import (
        MAX_DRAWDOWN_PCT,
        MIN_CALMAR,
        MIN_EXPOSURE_PCT,
        MIN_PROFIT_FACTOR,
        MIN_SHARPE,
        MIN_TRADES,
    )

    resp = client.get("/discovery/evaluation/gates")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["layer1_statistical_validity"]["min_trades"] == MIN_TRADES
    assert data["layer1_statistical_validity"]["min_exposure_pct"] == MIN_EXPOSURE_PCT
    assert data["layer2_risk_adjusted_return"]["min_sharpe"] == MIN_SHARPE
    assert data["layer2_risk_adjusted_return"]["min_calmar"] == MIN_CALMAR
    assert data["layer2_risk_adjusted_return"]["min_profit_factor"] == MIN_PROFIT_FACTOR
    assert data["layer2_risk_adjusted_return"]["max_drawdown_pct"] == MAX_DRAWDOWN_PCT


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
