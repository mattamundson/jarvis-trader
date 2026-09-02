"""POST /pipeline/run — human gate vs immediate paper (pipeline_router background task)."""

from __future__ import annotations

import sys
import time
import unittest.mock as mock
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

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
    "apscheduler",
    "apscheduler.schedulers",
    "apscheduler.schedulers.asyncio",
    "apscheduler.triggers.cron",
]

_saved_modules: dict = {}
for _mod_name in _MODULES_TO_MOCK:
    _saved_modules[_mod_name] = sys.modules.get(_mod_name)
    sys.modules[_mod_name] = mock.MagicMock()

import main as main_mod  # noqa: E402
from config import settings  # noqa: E402

for _mod_name, _original in _saved_modules.items():
    if _original is None:
        sys.modules.pop(_mod_name, None)
    else:
        sys.modules[_mod_name] = _original

for _mod_name in _MODULES_TO_MOCK:
    if "." in _mod_name:
        _parent, _attr = _mod_name.rsplit(".", 1)
        _parent_mod = sys.modules.get(_parent)
        if _parent_mod is not None and hasattr(_parent_mod, _attr):
            try:
                delattr(_parent_mod, _attr)
            except AttributeError:
                pass

import routers.pipeline_router as pipeline_router_mod  # noqa: E402
from database.manager import DatabaseManager  # noqa: E402

client = TestClient(main_mod.app)
_HEADERS = {"X-API-Key": settings.API_KEY}


def _pipeline_payload(*, requires_human: bool, final_action: str = "buy") -> dict:
    return {
        "final_action": final_action,
        "requires_human": requires_human,
        "confidence": 0.9,
        "final_quantity": 2,
        "summary": "human gate test",
        "trade_decision": {"limit_price": 71.25},
        "analyst_reports": {"technical": {}},
    }


@pytest.fixture
def tmp_db_manager(tmp_path):
    p = tmp_path / "gate.db"
    dm = DatabaseManager(str(p))
    dm.initialize()
    return dm


def _patch_router_deps(tmp_db_manager, mock_tp, mock_pt, mock_safety):
    """Swap pipeline_router injected globals for the test."""
    orig = (
        pipeline_router_mod._trading_pipeline,
        pipeline_router_mod._db_manager,
        pipeline_router_mod._paper_tracker,
        pipeline_router_mod._safety_layer,
    )
    pipeline_router_mod._trading_pipeline = mock_tp
    pipeline_router_mod._db_manager = tmp_db_manager
    pipeline_router_mod._paper_tracker = mock_pt
    pipeline_router_mod._safety_layer = mock_safety
    return orig


def _restore_router_deps(orig):
    (
        pipeline_router_mod._trading_pipeline,
        pipeline_router_mod._db_manager,
        pipeline_router_mod._paper_tracker,
        pipeline_router_mod._safety_layer,
    ) = orig


def test_requires_human_bypassed_in_paper_mode(tmp_db_manager):
    """
    In paper mode (LIVE_TRADING_ENABLED=False), requires_human=True is overridden
    so paper trades are always auto-logged for validation continuity.
    The pending_trade_approvals queue is NOT used in paper mode.
    """
    mock_tp = MagicMock()
    mock_tp.analyze_and_decide = AsyncMock(return_value=_pipeline_payload(requires_human=True))
    mock_pt = MagicMock()
    mock_pt.add_paper_trade.return_value = "paper-tid-bypass"
    mock_safety = MagicMock()
    mock_safety.get_status = MagicMock(return_value={"kill_switch_active": False})

    orig = _patch_router_deps(tmp_db_manager, mock_tp, mock_pt, mock_safety)
    try:
        with patch(
            "notifications.pending_approval_notify.notify_pending_approval_queued",
            new=AsyncMock(),
        ):
            r = client.post(
                "/pipeline/run",
                headers=_HEADERS,
                json={"symbol": "MCL", "is_futures": True},
            )
    finally:
        _restore_router_deps(orig)

    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("status") == "running"

    time.sleep(0.2)
    # Paper mode bypass: trade IS auto-logged even though requires_human=True
    mock_pt.add_paper_trade.assert_called_once()
    # No pending approval row — human gate is bypassed in paper mode
    assert len(tmp_db_manager.list_pending_approvals()) == 0


def test_without_human_logs_paper_no_pending_row(tmp_db_manager):
    mock_tp = MagicMock()
    mock_tp.analyze_and_decide = AsyncMock(return_value=_pipeline_payload(requires_human=False))
    mock_pt = MagicMock()
    mock_pt.add_paper_trade.return_value = "paper-tid-test"
    mock_safety = MagicMock()
    mock_safety.get_status = MagicMock(return_value={"kill_switch_active": False})

    orig = _patch_router_deps(tmp_db_manager, mock_tp, mock_pt, mock_safety)
    try:
        with patch(
            "notifications.pending_approval_notify.notify_pending_approval_queued",
            new=AsyncMock(),
        ):
            r = client.post(
                "/pipeline/run",
                headers=_HEADERS,
                json={"symbol": "MCL", "is_futures": True},
            )
    finally:
        _restore_router_deps(orig)

    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("status") == "running"

    time.sleep(0.2)
    mock_pt.add_paper_trade.assert_called_once()
    assert len(tmp_db_manager.list_pending_approvals()) == 0
