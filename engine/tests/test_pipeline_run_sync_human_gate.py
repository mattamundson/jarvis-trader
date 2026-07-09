"""
POST /pipeline/run — human gate must not be bypassed (run_pipeline_sync).

Discovered during the US-010 naked-row completeness sweep: run_pipeline_sync
(engine/routers/pipeline_router.py, the SYNC pipeline endpoint used by the
dashboard's Analysis "Run Pipeline" button and the watchlist per-symbol scan
loop -- dashboard/app/analysis/page.tsx, dashboard/app/watchlist/page.tsx)
contains two sequential top-level auto-log blocks with no exclusivity guard
between them:

1. A watchlist-gated block that inserts a pending_approval row when the
   pipeline flags requires_human=True (correctly deferring to a human).
2. An unconditional legacy block, with no requires_human/watchlist check at
   all, that opens a live paper trade directly via open_trade().

Because nothing short-circuits between them, block 2 always runs after
block 1 for any non-hold decision -- silently opening the paper trade the
human gate in block 1 was supposed to hold for approval. This defeats
REQUIRE_HUMAN_APPROVAL=True (safety.md non-negotiable) for every trade
routed through this endpoint. The background variant (/pipeline/run/background,
run_pipeline) does NOT have this bug -- see test_pipeline_run_human_gate.py,
which already proves add_paper_trade is never called there when
requires_human=True.

Fix: block 2 now only runs when block 1 did not already record an
approval or a trade on this same decision (tracked via
result.get("pending_approval_id") / result.get("paper_trade_id")).
"""

from __future__ import annotations

import sys
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
        "summary": "sync human gate test",
        "trade_decision": {"limit_price": 71.25},
        "technical": {"current_price": 71.25},
        "analyst_reports": {"technical": {}},
    }


@pytest.fixture
def tmp_db_manager(tmp_path):
    p = tmp_path / "sync_gate.db"
    dm = DatabaseManager(str(p))
    dm.initialize()
    return dm


def _patch_router_deps(tmp_db_manager, mock_tp, mock_pt, mock_safety):
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


def test_sync_requires_human_does_not_also_open_trade(tmp_db_manager):
    """
    The core regression: for a watchlist symbol with requires_human=True,
    only the pending-approval path should fire. open_trade() must NOT also
    be called for the same decision -- that would silently execute a paper
    trade the human gate was supposed to hold for approval.
    """
    mock_tp = MagicMock()
    mock_tp.analyze_and_decide = AsyncMock(return_value=_pipeline_payload(requires_human=True))
    mock_pt = MagicMock()
    mock_pt.open_trade.return_value = "paper-tid-bypass"
    mock_pt.add_paper_trade.return_value = "paper-tid-bypass-2"
    mock_safety = MagicMock()
    mock_safety.get_status = MagicMock(return_value={"kill_switch_active": False})

    orig = _patch_router_deps(tmp_db_manager, mock_tp, mock_pt, mock_safety)
    try:
        with patch(
            "notifications.pending_approval_notify.notify_pending_approval_queued",
            new=AsyncMock(),
        ), patch(
            "notifications.openclaw_notifier.notify_approval_required",
            new=AsyncMock(),
        ), patch.object(settings, "FUTURES_WATCHLIST", ["MCL"]):
            r = client.post(
                "/pipeline/run",
                headers=_HEADERS,
                json={"symbol": "MCL", "is_futures": True},
            )
    finally:
        _restore_router_deps(orig)

    assert r.status_code == 200, r.text
    data = r.json()

    pending = tmp_db_manager.list_pending_approvals()
    assert len(pending) == 1
    assert data.get("pending_approval_id") == pending[0]["approval_id"]

    mock_pt.open_trade.assert_not_called()
    mock_pt.add_paper_trade.assert_not_called()


def test_sync_without_human_still_auto_logs(tmp_db_manager):
    """Non-regression: requires_human=False for a watchlist symbol must still auto-log."""
    mock_tp = MagicMock()
    mock_tp.analyze_and_decide = AsyncMock(return_value=_pipeline_payload(requires_human=False))
    mock_pt = MagicMock()
    mock_pt.add_paper_trade.return_value = "paper-tid-ok"
    mock_safety = MagicMock()
    mock_safety.get_status = MagicMock(return_value={"kill_switch_active": False})

    orig = _patch_router_deps(tmp_db_manager, mock_tp, mock_pt, mock_safety)
    try:
        with patch.object(settings, "FUTURES_WATCHLIST", ["MES"]):
            r = client.post(
                "/pipeline/run",
                headers=_HEADERS,
                json={"symbol": "MES", "is_futures": True},
            )
    finally:
        _restore_router_deps(orig)

    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("paper_trade_id") == "paper-tid-ok"
    mock_pt.add_paper_trade.assert_called_once()
    mock_pt.open_trade.assert_not_called()
    assert len(tmp_db_manager.list_pending_approvals()) == 0


def test_sync_non_watchlist_symbol_legacy_autolog_unaffected(tmp_db_manager):
    """
    Non-regression: a symbol NOT on FUTURES_WATCHLIST never reaches block 1
    at all (its condition excludes non-watchlist symbols); the legacy
    catch-all block 2 is the only one that can act for it, and that
    existing behaviour is preserved untouched by this fix.
    """
    mock_tp = MagicMock()
    mock_tp.analyze_and_decide = AsyncMock(return_value=_pipeline_payload(requires_human=False))
    mock_pt = MagicMock()
    mock_pt.open_trade.return_value = "paper-tid-legacy"
    mock_safety = MagicMock()
    mock_safety.get_status = MagicMock(return_value={"kill_switch_active": False})

    orig = _patch_router_deps(tmp_db_manager, mock_tp, mock_pt, mock_safety)
    try:
        with patch.object(settings, "FUTURES_WATCHLIST", ["MES"]):
            r = client.post(
                "/pipeline/run",
                headers=_HEADERS,
                json={"symbol": "MCL", "is_futures": True},
            )
    finally:
        _restore_router_deps(orig)

    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("paper_trade_id") == "paper-tid-legacy"
    mock_pt.open_trade.assert_called_once()
