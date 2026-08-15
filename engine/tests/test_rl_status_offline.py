"""
Offline tests for RL status/results endpoints and pnl_monitor health.

These tests do NOT require a live engine or real RL training data.  They use
the sys.modules mock pattern (established in test_session4_contract.py) to
import main.app without heavy dependencies, then patch module-level state
objects to supply synthetic data.

Covers the three cases that currently skip in test_integration_rl_endpoints.py:
  - test_results_active_run_returns_200  (line 556 in integration file)
  - test_results_active_run_schema       (line 569 in integration file)
  - test_pnl_monitor_has_valid_starting_balance  (line 846 in integration file)

Run:
    cd engine && .venv/Scripts/python -m pytest tests/test_rl_status_offline.py -v
"""

from __future__ import annotations

import sys
import unittest.mock as mock
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# sys.modules mock block — must happen before importing main / app
# ---------------------------------------------------------------------------

_MODULES_TO_MOCK = [
    "data.market_data",
    "risk.safety_layer",
    "risk.pnl_monitor",
    "google",
    "google.genai",
    "agents.bear_researcher",
    "agents.bull_researcher",
    "agents.debate",
    "agents.fund_manager",
    "agents.fundamental_analyst",
    "agents.news_analyst",
    "agents.risk_manager",
    "agents.social_analyst",
    "agents.technical_analyst",
    "agents.thinkscript_generator",
    "agents.trader",
    "portfolio.tracker",
    "database.schema",
    "schedulers.eod_scheduler",
    "routers.journal_router",
    "routers.webhook_router",
    "services.jarvis_analysis",
    "execution.ib_order_manager",
    "notifications.whatsapp",
    "apscheduler",
    "apscheduler.schedulers",
    "apscheduler.schedulers.asyncio",
    "apscheduler.triggers.cron",
]

_saved_modules: dict = {}
for _mod_name in _MODULES_TO_MOCK:
    _saved_modules[_mod_name] = sys.modules.get(_mod_name)
    sys.modules[_mod_name] = mock.MagicMock()

from config import settings  # noqa: E402
from main import app  # noqa: E402

# Restore real modules so other test files get genuine implementations.
for _mod_name, _original in _saved_modules.items():
    if _original is None:
        sys.modules.pop(_mod_name, None)
    else:
        sys.modules[_mod_name] = _original

# Clean parent module attributes for dotted names.
for _mod_name in _MODULES_TO_MOCK:
    if "." in _mod_name:
        _parent, _attr = _mod_name.rsplit(".", 1)
        _parent_mod = sys.modules.get(_parent)
        if _parent_mod is not None and hasattr(_parent_mod, _attr):
            _original = _saved_modules.get(_mod_name)
            if _original is not None:
                # Restore the real submodule reference (not just delete it) --
                # a later-collected test file's string-based monkeypatch/mock
                # target (e.g. "notifications.whatsapp.send_x") resolves via
                # this attribute, not just via sys.modules.
                setattr(_parent_mod, _attr, _original)
            else:
                try:
                    delattr(_parent_mod, _attr)
                except AttributeError:
                    pass

# ---------------------------------------------------------------------------
# Shared client
# ---------------------------------------------------------------------------

from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(app, raise_server_exceptions=False)

_AUTH = {"X-API-Key": settings.API_KEY}

# ---------------------------------------------------------------------------
# Synthetic test data
# ---------------------------------------------------------------------------

_FAKE_RUN_ID = "test-run-offline-001"

_FAKE_RUN_ENTRY = {
    "run_id": _FAKE_RUN_ID,
    "symbol": "MES",
    "status": "complete",
    "started_at": "2024-01-01T00:00:00+00:00",
    "completed_at": "2024-01-01T01:00:00+00:00",
    "error": None,
    "result": {
        "metrics": {"pf": 2.5, "sharpe": 1.8, "win_rate": 0.62},
        "training_summary": {},
        "model_path": "/models/MES_test.zip",
        "train_bars": 500,
        "test_bars": 100,
        "interval": "1h",
        "timesteps": 50000,
    },
}

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRLResultsOffline:
    """Offline equivalents of TestRLRunResults tests from test_integration_rl_endpoints.py."""

    def test_results_active_run_returns_200(self):
        """
        GET /strategies/rl/results/<run_id> returns HTTP 200 when the run
        exists in the _run_registry — no live training required.
        """
        import routers.strategies_router as strategies_router_mod

        with patch.object(
            strategies_router_mod,
            "_run_registry",
            {_FAKE_RUN_ID: _FAKE_RUN_ENTRY},
        ):
            response = client.get(f"/strategies/rl/results/{_FAKE_RUN_ID}", headers=_AUTH)

        assert response.status_code == 200, (
            f"Expected 200 for run_id={_FAKE_RUN_ID}, "
            f"got {response.status_code}. Body: {response.text}"
        )

    def test_results_active_run_schema(self):
        """
        GET /strategies/rl/results/<run_id> response must contain the required
        schema fields: run_id, symbol, status, started_at.
        """
        import routers.strategies_router as strategies_router_mod

        with patch.object(
            strategies_router_mod,
            "_run_registry",
            {_FAKE_RUN_ID: _FAKE_RUN_ENTRY},
        ):
            response = client.get(f"/strategies/rl/results/{_FAKE_RUN_ID}", headers=_AUTH)

        assert response.status_code == 200, (
            f"Expected 200 for run_id={_FAKE_RUN_ID}, "
            f"got {response.status_code}. Body: {response.text}"
        )

        data = response.json()
        required_fields = ["run_id", "symbol", "status", "started_at"]
        for field in required_fields:
            assert field in data, f"Missing field '{field}' in results response. Body: {data}"

        # Spot-check values match the injected entry.
        assert data["run_id"] == _FAKE_RUN_ID
        assert data["symbol"] == "MES"
        assert data["status"] == "complete"


class TestPnLMonitorOffline:
    """
    Offline equivalent of test_pnl_monitor_has_valid_starting_balance from
    test_integration_rl_endpoints.py.

    The /health/full endpoint reads pnl_monitor from health_router's module-level
    global (injected at startup by main.py).  We patch that global directly so no
    live engine is needed.

    NOTE on schema: /health/full serialises subsystems through the FullHealthResponse
    Pydantic model, which maps each subsystem entry to SubsystemStatus
    (api/models.py).  SubsystemStatus is defined with extra="ignore", so only its
    declared fields survive serialisation.  The declared numeric field for PnL data
    is `daily_pnl`; `starting_balance` and `current_balance` are stripped by
    Pydantic.  We therefore verify `daily_pnl > 0` as the proxy for a live,
    non-zero PnL monitor — which is the spirit of the original integration test.
    """

    def test_pnl_monitor_has_valid_starting_balance(self):
        """
        GET /health/full subsystems.pnl_monitor must report status='ok' and
        daily_pnl > 0 when pnl_monitor is initialised with non-zero balances.

        Patches health_router.pnl_monitor with a MagicMock whose PnL-state
        object returns realistic non-zero values.
        """
        import routers.health_router as health_router_mod

        # Build a mock PnL state object.
        mock_pnl_state = MagicMock()
        mock_pnl_state.source = "paper"
        mock_pnl_state.starting_balance = 10000.0
        mock_pnl_state.current_balance = 10250.0

        # Build the mock PnL monitor.
        mock_pnl_monitor = MagicMock()
        mock_pnl_monitor.get_current_pnl_state.return_value = mock_pnl_state
        mock_pnl_monitor.get_daily_pnl.return_value = 250.0
        mock_pnl_monitor.get_drawdown_pct.return_value = 0.0

        with patch.object(health_router_mod, "pnl_monitor", mock_pnl_monitor):
            response = client.get("/health/full", headers=_AUTH)

        assert response.status_code == 200, (
            f"Expected 200 from /health/full, got {response.status_code}. " f"Body: {response.text}"
        )

        body = response.json()
        pnl = body.get("subsystems", {}).get("pnl_monitor", {})

        assert pnl.get("status") == "ok", f"pnl_monitor status should be 'ok', got: {pnl}"
        # SubsystemStatus.daily_pnl is the declared float field that survives
        # Pydantic serialisation (starting_balance / current_balance are stripped
        # by extra="ignore").  Assert it is positive to confirm the mock was wired.
        assert pnl.get("daily_pnl", 0) > 0, (
            f"daily_pnl should be > 0 when pnl_monitor is initialised, "
            f"got: {pnl.get('daily_pnl')}. Full pnl subsystem: {pnl}"
        )


class TestIBGatewayHealthOffline:
    """Targeted health-router regressions for broker connectivity reporting."""

    @pytest.mark.asyncio
    async def test_health_prefers_safety_layer_execution_connector(self):
        """
        /health and /health/full should reflect the execution connector attached
        to SafetyLayer in paper mode, even if the market-data IB object is absent
        or disconnected.
        """
        import routers.health_router as health_router_mod

        class _ExecIB:
            def is_connected(self):
                return True

            async def health_check(self):
                return {"status": "connected", "mode": "paper"}

        class _FakeSafety:
            _ib_gateway = _ExecIB()

            def get_status(self):
                return {"kill_switch_active": False}

        disconnected_market_data_dm = SimpleNamespace(
            ibkr=SimpleNamespace(is_connected=False)
        )
        fake_safety = _FakeSafety()

        with patch.object(health_router_mod, "data_manager", disconnected_market_data_dm), patch.object(
            health_router_mod, "safety_layer", fake_safety
        ):
            basic = await health_router_mod._health_inner()
            full = await health_router_mod._full_health_inner()

        assert basic["ibkr_connected"] is True
        ib = full.get("subsystems", {}).get("ib_gateway", {})
        assert ib.get("status") == "connected", ib
        assert ib.get("source") == "execution_connector", ib
