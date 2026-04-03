"""
Offline contract tests for POST /strategies/rl/evaluate.

These tests verify that the endpoint returns 422 Unprocessable Entity when
the request body is missing or lacks required fields.  No trained RL model is
needed — Pydantic validation fires before any model inference occurs.

All heavy / unavailable dependencies are mocked via sys.modules before
`main.app` is imported, following the pattern established in
test_auth_and_rate_limit.py and test_session4_contract.py.

Run:
    cd engine && .venv/Scripts/python -m pytest tests/test_rl_evaluate_offline.py -v
"""

from __future__ import annotations

import sys
import unittest.mock as mock

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Mock all heavy modules BEFORE importing main.app so that unavailable
# dependencies (ib_insync, apscheduler, custom agents, etc.) do not cause
# ImportError during collection.
# ---------------------------------------------------------------------------

_MODULES_TO_MOCK = [
    "data.market_data",
    "risk.safety_layer",
    "risk.pnl_monitor",
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
    "execution.ib_order_manager",
    "notifications.whatsapp",
    "strategies.rl_trainer",
    "strategies.rl_config",
    "apscheduler",
    "apscheduler.schedulers",
    "apscheduler.schedulers.asyncio",
    "apscheduler.triggers.cron",
]

_saved_modules: dict = {}
for _mod_name in _MODULES_TO_MOCK:
    _saved_modules[_mod_name] = sys.modules.get(_mod_name)
    sys.modules[_mod_name] = mock.MagicMock()

# Must import config and main AFTER injecting mocks above.
from config import settings  # noqa: E402
from main import app  # noqa: E402

# Restore real modules so that other test files collected in the same session
# receive the genuine implementations rather than our MagicMocks.
for _mod_name, _original in _saved_modules.items():
    if _original is None:
        sys.modules.pop(_mod_name, None)
    else:
        sys.modules[_mod_name] = _original

# Clean parent module attributes for dotted names so that subsequent imports
# find the real sub-module rather than a stale MagicMock reference on the
# parent's __dict__.
for _mod_name in _MODULES_TO_MOCK:
    if "." in _mod_name:
        _parent, _attr = _mod_name.rsplit(".", 1)
        _parent_mod = sys.modules.get(_parent)
        if _parent_mod is not None and hasattr(_parent_mod, _attr):
            try:
                delattr(_parent_mod, _attr)
            except AttributeError:
                pass

# ---------------------------------------------------------------------------
# Shared client + auth header
# ---------------------------------------------------------------------------

client = TestClient(app, raise_server_exceptions=False)

_AUTH = {"X-API-Key": settings.API_KEY}

_ENDPOINT = "/strategies/rl/evaluate"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRLEvaluateOffline:
    """
    Offline 422-validation tests for POST /strategies/rl/evaluate.

    Each test sends a malformed (or empty) request body and asserts that
    FastAPI/Pydantic returns 422 Unprocessable Entity before any model
    inference code is reached.
    """

    def test_evaluate_missing_body_422(self):
        """POST /strategies/rl/evaluate with no body must return 422."""
        resp = client.post(_ENDPOINT, headers=_AUTH)
        assert resp.status_code == 422, (
            f"Expected 422 for missing body, got {resp.status_code}. " f"Body: {resp.text}"
        )

    def test_evaluate_empty_body_422(self):
        """POST /strategies/rl/evaluate with empty JSON object must return 422."""
        resp = client.post(_ENDPOINT, json={}, headers=_AUTH)
        assert resp.status_code == 422, (
            f"Expected 422 for empty body, got {resp.status_code}. " f"Body: {resp.text}"
        )

    def test_evaluate_missing_start_422(self):
        """POST /strategies/rl/evaluate without start_date must return 422."""
        resp = client.post(
            _ENDPOINT,
            json={"end_date": "2024-01-31"},
            headers=_AUTH,
        )
        assert resp.status_code == 422, (
            f"Expected 422 for missing start_date, got {resp.status_code}. " f"Body: {resp.text}"
        )

    def test_evaluate_missing_end_422(self):
        """POST /strategies/rl/evaluate without end_date must return 422."""
        resp = client.post(
            _ENDPOINT,
            json={"start_date": "2024-01-01"},
            headers=_AUTH,
        )
        assert resp.status_code == 422, (
            f"Expected 422 for missing end_date, got {resp.status_code}. " f"Body: {resp.text}"
        )
